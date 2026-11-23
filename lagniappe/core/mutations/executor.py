"""Execute authoritative mutation effects in durable-first order."""
import json
from collections.abc import Iterable, Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, NotRequired, Protocol, TypedDict, cast

from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.database.assets import cleanup_rejected_attempt
from lagniappe.core.tools.measurements import timed

from ..definitions import (
    MutationEffectType,
    MutationOutcome,
    MutationPhase,
    MutationPlan,
)
from ..exceptions import MutationConflict, capture
from ..tools import cache
from ..tools.notifications import service as notification_service

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..definitions import MutationEffect
    from ..entities.entity import Entity
    from ..entities.types import Notification, Task

    class PreparedWrite(MutationEffect):
        """A durable write after the executor has verified its target."""
        entity: Entity


WRITE_EFFECTS = {MutationEffectType.UPSERT, MutationEffectType.UNLINK}


class _ProjectionChanges(TypedDict):
    upserts: list[Notification]
    deletes: list[Notification]
    aggregates: NotRequired[Mapping[str, Mapping[str, object]]]


class _Updatable(Protocol):
    def update(self) -> object: ...


class _IndexedRow(Protocol):
    exclude_from_indexes: Iterable[str]


class _WriteOptions(TypedDict, total=False):
    guards: list[tuple[Key, Mapping[str, object] | None]]
    deletes: list[Entity]


def _subject(effect: MutationEffect) -> Entity:
    """Read the required entity from a durable or entity-scoped cache effect."""
    if effect.entity is None:
        raise ValueError(f"{effect.effect.value} effect requires an entity")
    return effect.entity


def _prepare_write(effect: MutationEffect) -> None:
    entity = _subject(effect)
    if effect.property_mask is None:
        for name in getattr(entity, "retired_fields", ()):
            entity.db.pop(name, None)

    for name in effect.property_updates:
        if name in entity.properties:
            cast(_Updatable, entity.properties[name]).update()

    if effect.serialize_processes:
        processes = {key: value for key, value in entity.processes.items() if value}
        for key, updates in processes.items():
            entity.db[key] = json.dumps(updates)

    with suppress(AttributeError):
        cast(_IndexedRow, entity.db).exclude_from_indexes = entity.exclude_from_index


def consume_mutation_intents(plan: MutationPlan) -> None:
    for owner, captured in plan.consumed_intents:
        current = list(getattr(owner, "mutation_intents", ()))
        captured_ids = {id(intent) for intent in captured}
        owner._mutation_intents = [
            intent for intent in current if id(intent) not in captured_ids
        ]
    for effect in plan.effects:
        if effect.effect is not MutationEffectType.UPSERT:
            continue
        entity = _subject(effect)
        entity._form_additional_guards = []
        if effect.property_mask is None:
            # Form publication distinguishes restriction changes from content
            # changes; both invalidate submissions, but only restrictions queue work.
            if entity.kind != "form" and getattr(entity, "_permission_sources_changed", False):
                entity._reconcile_restrictions = True
            entity._permission_sources_changed = False
            if entity.kind == "task":
                entity._page_changed = False
            if entity.kind in {"task", "task_history"}:
                entity._completion_transition = None
                entity._completion_write_guards = []
            if entity.kind == "form":
                entity._pending_html = {}
                entity._form_save_guard = None
                entity._form_additional_guards = []
                entity._form_attempt_assets = []
            if entity.kind in {"form_history", "task_history"}:
                entity._form_attempt_assets = []


def _completed(outcome: MutationOutcome, effect_type: MutationEffectType) -> None:
    if effect_type not in outcome.completed_effects:
        outcome.completed_effects.append(effect_type)


def prepare_durable_writes(plan: MutationPlan) -> list[PreparedWrite]:
    writes = [
        effect
        for effect in plan.effects
        if effect.phase is MutationPhase.DURABLE and effect.effect in WRITE_EFFECTS
    ]
    for effect in writes:
        _prepare_write(effect)
    # _prepare_write checked that every write has a concrete subject.
    return cast("list[PreparedWrite]", writes)


def execute_post_commit(
    plan: MutationPlan,
) -> tuple[list[MutationEffectType], list[str]]:
    """Execute declared post-commit effects and return types plus errors."""
    completed = []
    errors = []

    def complete(effect_type: MutationEffectType) -> None:
        if effect_type not in completed:
            completed.append(effect_type)

    post_commit = [
        effect for effect in plan.effects if effect.phase is MutationPhase.POST_COMMIT
    ]
    refresh = [
        _subject(effect)
        for effect in post_commit
        if effect.effect is MutationEffectType.CACHE_REFRESH
    ]
    if refresh:
        from ..tools.cache.restrictions import prepare_changes, dispatch_changes
        changes = prepare_changes(refresh)
        cache.update(*refresh)
        dispatch_changes(changes)
        cache.update_owner_projection(*refresh)
        complete(MutationEffectType.CACHE_REFRESH)

    refreshed = {entity.key for entity in refresh}
    invalidated = [
        _subject(effect) for effect in post_commit
        if effect.effect is MutationEffectType.CACHE_INVALIDATE
        and _subject(effect).key not in refreshed
    ]
    if invalidated:
        cache.invalidate_revisions(*invalidated)
    if any(effect.effect is MutationEffectType.CACHE_INVALIDATE for effect in post_commit):
        complete(MutationEffectType.CACHE_INVALIDATE)

    deleted = [
        _subject(effect)
        for effect in post_commit
        if effect.effect is MutationEffectType.CACHE_DELETE
    ]
    if deleted:
        cache.delete(deleted)
        complete(MutationEffectType.CACHE_DELETE)

    for effect in post_commit:
        if effect.effect is MutationEffectType.CACHE_STATE_DELETE:
            cache.clear_document(cast(str, effect.cache_key))
            complete(MutationEffectType.CACHE_STATE_DELETE)
        elif effect.effect is MutationEffectType.CACHE_SEARCH_DELETE:
            cache.delete_entity_from_search(cast(str, effect.cache_kind), _subject(effect))
            complete(MutationEffectType.CACHE_SEARCH_DELETE)

    notification_upserts = [
        cast("Notification", _subject(effect))
        for effect in post_commit
        if effect.effect is MutationEffectType.NOTIFICATION_UPSERT
    ]
    notification_deletes = [
        cast("Notification", _subject(effect))
        for effect in post_commit
        if effect.effect is MutationEffectType.NOTIFICATION_DELETE
    ]
    if notification_upserts or notification_deletes:
        aggregates = notification_service.apply_ordinary_mutations(
            upserts=notification_upserts,
            deletes=notification_deletes,
        )
        projection_changes: _ProjectionChanges = {
            "upserts": notification_upserts,
            "deletes": notification_deletes,
        }
        if aggregates:
            projection_changes["aggregates"] = aggregates
        cache.update_notification_projection(**projection_changes)
        from ..tools.email.notifications import capture as email_capture

        for notification in notification_upserts:
            try:
                email_capture.record_notification(notification)
            except Exception as error:
                capture(
                    error,
                    context={
                        "operation": "notification-email-capture",
                        "notification_key": getattr(notification, "urlsafe_key", None),
                    },
                )
        if notification_upserts:
            complete(MutationEffectType.NOTIFICATION_UPSERT)
        if notification_deletes:
            complete(MutationEffectType.NOTIFICATION_DELETE)

    operation_upserts = [
        _subject(effect)
        for effect in post_commit
        if effect.effect is MutationEffectType.OPERATION_UPSERT
    ]
    operation_deletes = [
        _subject(effect)
        for effect in post_commit
        if effect.effect is MutationEffectType.OPERATION_DELETE
    ]
    if operation_upserts:
        cache.update_operation_projection(*operation_upserts)
        complete(MutationEffectType.OPERATION_UPSERT)
    if operation_deletes:
        cache.delete_operation_projection(*operation_deletes)
        complete(MutationEffectType.OPERATION_DELETE)

    blob_effects = [
        effect
        for effect in post_commit
        if effect.effect is MutationEffectType.BLOB_DELETE
    ]
    if blob_effects:
        errors.extend(
            database_utility.delete_blobs(
                [
                    effect.path
                    for effect in blob_effects
                    if effect.path is not None and effect.visibility == "private"
                ],
                [
                    effect.path
                    for effect in blob_effects
                    if effect.path is not None and effect.visibility == "public"
                ],
            )
            or []
        )
        complete(MutationEffectType.BLOB_DELETE)

    scheduled_uncomplete = [
        cast("Task", _subject(effect))
        for effect in post_commit
        if effect.effect is MutationEffectType.SCHEDULED_UNCOMPLETE_DISPATCH
    ]
    if scheduled_uncomplete:
        from ..tools.tasks import scheduling

        for task in scheduled_uncomplete:
            scheduling.dispatch_scheduled_uncomplete(task)
        complete(MutationEffectType.SCHEDULED_UNCOMPLETE_DISPATCH)

    if any(
        effect.effect is MutationEffectType.PUBLIC_DISCOVERY_INVALIDATE
        for effect in post_commit
    ):
        cache.invalidate_public_discovery()
        complete(MutationEffectType.PUBLIC_DISCOVERY_INVALIDATE)
    return completed, errors


@timed("entity", "mutation")
def execute_mutation(
    plan: MutationPlan,
    *,
    guards: Iterable[tuple[Key, Mapping[str, object] | None]] | None = None,
) -> MutationOutcome:
    """Execute durable effects before rebuildable cache and blob effects."""
    if not isinstance(plan, MutationPlan):
        raise TypeError("execute_mutation requires a MutationPlan")

    outcome = MutationOutcome(plan.operation)
    durable = [
        effect for effect in plan.effects if effect.phase is MutationPhase.DURABLE
    ]
    writes = prepare_durable_writes(plan)
    deletes = [
        effect for effect in durable if effect.effect is MutationEffectType.DELETE
    ]

    from lagniappe.core.tools.forms.changes import mutation_guards
    form_change_guards = mutation_guards(writes, deletes)

    if writes or (deletes and (guards or form_change_guards)):
        mutation_guards = [*(guards or []), *form_change_guards]
        for effect in writes:
            guard = getattr(effect.entity, "_form_save_guard", None)
            if guard is not None:
                mutation_guards.append(guard)
            for attribute in ("_completion_write_guards", "_form_additional_guards"):
                mutation_guards.extend(getattr(effect.entity, attribute, None) or [])
        options: _WriteOptions = {"guards": mutation_guards} if mutation_guards else {}
        form_deletes = deletes if mutation_guards else [effect for effect in deletes if _subject(effect).entity_kind == "form"]
        if form_deletes:
            # A Form's last generation and its deletion must commit together.
            options["deletes"] = [_subject(effect) for effect in form_deletes]
        try:
            database_utility.save_mutations(
                ((_subject(effect), effect.property_mask) for effect in writes), **options
            )
        except MutationConflict:
            for effect in writes:
                cleanup_rejected_attempt(_subject(effect))
            raise
        for effect in writes:
            _completed(outcome, effect.effect)
        if form_deletes:
            _completed(outcome, MutationEffectType.DELETE)
            deletes = [effect for effect in deletes if effect not in form_deletes]

    if deletes:
        database_utility.delete_entities(_subject(effect) for effect in deletes)
        _completed(outcome, MutationEffectType.DELETE)

    consume_mutation_intents(plan)
    outcome.durable_committed = True

    try:
        completed, errors = execute_post_commit(plan)
        for effect_type in completed:
            _completed(outcome, effect_type)
        outcome.errors.extend(errors)
    except Exception as error:
        capture(
            error,
            context={
                "mutation": {
                    "operation": plan.operation.value,
                    "durable_committed": outcome.durable_committed,
                }
            },
        )
        outcome.errors.append(str(error))

    outcome.post_commit_complete = not outcome.errors
    return outcome
