"""Execute authoritative mutation effects in durable-first order."""

import json

from ..definitions import (
    MutationEffectType,
    MutationOutcome,
    MutationPhase,
    MutationPlan,
)
from ..exceptions import capture
from ..tools import cache
from lagniappe.core.tools.database import utility as database_utility
from ..tools.notifications import service as notification_service


WRITE_EFFECTS = {MutationEffectType.UPSERT, MutationEffectType.UNLINK}


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_save_entities_updates_hash_before_requires
# @tests tests_unit/test_002_entity_general_properties.py::test_save_entities_updates_and_persists_user_before_owned_page
# @matrix requires : hash-before-requires persisted-requires
# @pairs entities:save-order users:user-before-page
def _prepare_write(effect):
    entity = effect.entity
    for name in effect.property_updates:
        if name in entity.properties:
            entity.properties[name].update()

    if effect.serialize_processes:
        processes = {key: value for key, value in entity.processes.items() if value}
        for key, updates in processes.items():
            entity.db[key] = json.dumps(updates)

    try:
        entity.db.exclude_from_indexes = entity.exclude_from_index
    except AttributeError:
        pass


# @testable infrastructure
def consume_mutation_intents(plan):
    for owner, captured in plan.consumed_intents:
        current = list(getattr(owner, "mutation_intents", ()))
        captured_ids = {id(intent) for intent in captured}
        owner._mutation_intents = [
            intent for intent in current if id(intent) not in captured_ids
        ]


# @testable infrastructure
def _completed(outcome, effect_type):
    if effect_type not in outcome.completed_effects:
        outcome.completed_effects.append(effect_type)


# @testable infrastructure
def prepare_durable_writes(plan):
    writes = [
        effect
        for effect in plan.effects
        if effect.phase is MutationPhase.DURABLE and effect.effect in WRITE_EFFECTS
    ]
    for effect in writes:
        _prepare_write(effect)
    return writes


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_public_discovery_invalidation_runs_after_durable_write
# @matrix mutations : durable-first
# @matrix public-pages public-directory sitemap : invalidation
def execute_post_commit(plan):
    """Execute declared post-commit effects and return types plus errors."""
    completed = []
    errors = []

    # @testable infrastructure
    def complete(effect_type):
        if effect_type not in completed:
            completed.append(effect_type)

    post_commit = [
        effect for effect in plan.effects if effect.phase is MutationPhase.POST_COMMIT
    ]
    refresh = [
        effect.entity
        for effect in post_commit
        if effect.effect is MutationEffectType.CACHE_REFRESH
    ]
    if refresh:
        cache.update(*refresh)
        cache.update_owner_projection(*refresh)
        complete(MutationEffectType.CACHE_REFRESH)

    deleted = [
        effect.entity
        for effect in post_commit
        if effect.effect is MutationEffectType.CACHE_DELETE
    ]
    if deleted:
        cache.delete(deleted)
        complete(MutationEffectType.CACHE_DELETE)

    for effect in post_commit:
        if effect.effect is MutationEffectType.CACHE_STATE_DELETE:
            cache.clear_document(effect.cache_key)
            complete(MutationEffectType.CACHE_STATE_DELETE)
        elif effect.effect is MutationEffectType.CACHE_SEARCH_DELETE:
            cache.delete_entity_from_search(effect.cache_kind, effect.entity)
            complete(MutationEffectType.CACHE_SEARCH_DELETE)

    notification_upserts = [
        effect.entity
        for effect in post_commit
        if effect.effect is MutationEffectType.NOTIFICATION_UPSERT
    ]
    notification_deletes = [
        effect.entity
        for effect in post_commit
        if effect.effect is MutationEffectType.NOTIFICATION_DELETE
    ]
    if notification_upserts or notification_deletes:
        aggregates = notification_service.apply_ordinary_mutations(
            upserts=notification_upserts,
            deletes=notification_deletes,
        )
        projection_changes = {
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
        effect.entity
        for effect in post_commit
        if effect.effect is MutationEffectType.OPERATION_UPSERT
    ]
    operation_deletes = [
        effect.entity
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
                    if effect.visibility == "private"
                ],
                [
                    effect.path
                    for effect in blob_effects
                    if effect.visibility == "public"
                ],
            )
            or []
        )
        complete(MutationEffectType.BLOB_DELETE)

    scheduled_uncomplete = [
        effect.entity
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


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_save_executes_datastore_before_cache_and_reports_cache_failure
# @tests tests_unit/test_022_mutation_contracts.py::test_save_plan_is_serializable_and_preserves_intents_until_commit
# @matrix mutations : cache-failure durable-first mutation-plan post-commit-outcome save typed-intent-preservation
def execute_mutation(plan):
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

    if writes:
        database_utility.save_mutations(
            (effect.entity, effect.property_mask) for effect in writes
        )
        for effect in writes:
            _completed(outcome, effect.effect)

    if deletes:
        database_utility.delete_entities(effect.entity for effect in deletes)
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
