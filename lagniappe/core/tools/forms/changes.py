"""Saved Form-change orchestration and guarded batch application."""
import json
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import uuid4

from ...definitions import (
    Action,
    DeferredJobSpec,
    DeferredJobType,
    Fetch,
    FetchReason,
    MutationOperation,
)
from ...entities import Entities
from ...exceptions import MutationConflict, ValidationError
from ..database import get as database_get
from ..database.utility import ExactEntityState
from . import conversions, population
from .contracts import (
    ANSWER_FIELDS,
    NOTICE,
    PENDING,
    RECEIPT,
    PendingFormChange,
    ChangeRejection,
    FormPublication,
    check_size,
    json_value,
    migration_notice,
    pending_change,
    persisted_key,
)

if TYPE_CHECKING:
    from google.cloud.datastore import Entity as DatastoreEntity
    from google.cloud.datastore import Key

    from ...definitions.mutations import MutationEffect
    from ...entities.ai_report import AIReport
    from ...entities.deferred_job import DeferredJob
    from ...entities.form import Form
    from ...entities.history import TaskHistory
    from ...entities.page import Page
    from ...entities.task import Task
    from ...entities.user import User
    from ..deferred_jobs.context import DeferredJobContext
    from .drafts import DraftImages


class SchemaAction(TypedDict):
    id: str
    data: dict[str, object]


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_start_stages_intent_without_enumerating_submissions
# @matrix form-migration : save no-submission-read durable-intent
def start_change(
    form: Form,
    draft: Mapping[str, object],
    save_id: str,
    actor: User,
    *,
    images: DraftImages | None = None,
    report: AIReport | None = None,
    schema_action: SchemaAction | None = None,
) -> FormPublication:
    from .. import dates
    from . import drafts
    from ..deferred_jobs.service import DeferredJobs
    from ..database.assets import cleanup_rejected_attempt

    migration = draft.get("migration")
    if (
        not isinstance(migration, dict)
        or migration.get("version") not in {1, conversions.VERSION}
        or migration.get("clear_invalid") is not True
    ):
        raise ValidationError(
            "Removing or changing a saved field requires a form migration. Use Modify, then Save."
        )
    if form.reserved:
        raise ValidationError("Reserved forms cannot be converted.")
    schema = drafts.validate_draft_schema(draft["schema"], form.form_type)
    operations = conversions.classify_changes(
        form.schema, schema, migration.get("mappings")
    )
    if not operations:
        raise ValidationError("There are no submission changes to apply.")
    pending = pending_change(form.db)
    digest = drafts._digest(draft)
    if pending:
        if pending["id"] != save_id or pending["digest"] != digest:
            raise ValidationError("A form change is already saved. Wait for it to finish before modifying this form.")
        return change_response(form, actor)
    from . import schema_updates
    from ...definitions import AI

    ai_fields = {change["id"] for change in operations if change["rule"] == "ai"}
    instructions = migration.get("instructions") or {}
    if not isinstance(instructions, dict) or set(instructions) - ai_fields or any(
        not isinstance(value, str) or len(value) > 4000 for value in instructions.values()
    ):
        raise ValidationError("Conversion instructions must name AI-converted fields and contain at most 4000 characters each.")
    if ai_fields and report is None and not actor.access(AI.CREATE):
        raise ValidationError("This user does not have the required AI access.")
    if ai_fields or report is not None:
        scope = schema_updates.inspect_scope(form, operations, actor)
        expected_scope = (schema_action or {}).get("data", {}).get("scope_fingerprint")
        if expected_scope and scope["scope_fingerprint"] != expected_scope:
            raise ValidationError(schema_updates.STALE_MESSAGE)
    target = Entities.FORM(cast("DatastoreEntity", deepcopy(form.db)))
    target.name = cast(str, draft["name"]).strip()
    target.set_schema(schema)
    target.generation = form.generation + 1
    drafts._validate_content(schema, draft["html_fields"], images or {})
    html_fields = cast(dict[str, str], draft["html_fields"])
    committed = False
    try:
        image_urls = drafts._stage_content(
            target, html_fields, images or {}
        )
        drafts.stage_form_content(target)
        target.properties.version.update()
        change: PendingFormChange = {
            "id": save_id,
            "digest": digest,
            "source_generation": form.generation,
            "baseline": drafts.builder_draft(form)["baseline"],
            "zone": str(dates.user_timezone(actor)),
            "operations": operations,
            "instructions": deepcopy(instructions),
            "require_visibility": bool(ai_fields or report is not None),
            "phase": "checking",
            "applied": False,
            "image_urls": image_urls,
            "attempt_assets": deepcopy(getattr(target, "_form_attempt_assets", [])),
            "target": {
                "name": target.name,
                "schema": target.schema,
                "assets": target.assets,
                "generation": target.generation,
                "version": cast(str | None, target.version),
                "html_fields": {
                    cast(str, field["id"]): target.get_html_field(cast(str, field["id"])) or ""
                    for field in target.schema
                    if field["type"] == "html"
                },
            },
        }
        if report is not None:
            from ...properties.ai_report_proposal import proposal_fingerprint

            assert schema_action is not None
            change["report"] = report.urlsafe_key
            change["report_fingerprint"] = proposal_fingerprint(report.proposal)
            change["action_id"] = schema_action["id"]
            change["scope_fingerprint"] = cast(str | None, schema_action["data"].get("scope_fingerprint"))
        check_size({**form.db, PENDING: change})
        form._starting_form_change = change
        # Atomic start owns the staged assets from here, even if dispatch acknowledgement fails.
        committed = True
        DeferredJobs.start(
            DeferredJobSpec(
                job_type=DeferredJobType.FORM_CHANGE,
                actor=actor,
                inputs={"form": form},
                parameters={"change_id": save_id, "digest": digest},
                notification_body="Updating form submissions...",
                notification_target=form,
                idempotency_key=f"form-change:{form.hash}:{save_id}",
            )
        )
    except MutationConflict:
        cleanup_rejected_attempt(target)
        raise
    except Exception:
        if not committed:
            cleanup_rejected_attempt(target)
        raise
    current = cast("Form | None", Entities.fetch_one(form.key, request=Fetch.direct()))
    if current is None:
        raise MutationConflict("The Form was deleted during the update.")
    return change_response(current, actor)


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_conversion_failure_status_names_columns_and_checks_target_visibility
# @matrix form-migration : status recovery permissions
def change_response(form: Form, actor: User | None = None) -> FormPublication:
    from . import drafts

    change = pending_change(form.db)
    if not change:
        receipt = json_value(form.db, "form_draft_receipt")
        response = drafts._saved_response(form, cast(dict[str, str], receipt.get("image_urls", {})))
        rejection = json_value(form.db, "form_change_rejection")
        if rejection:
            response["rejected_change"] = cast(ChangeRejection, rejection)
        return response
    job = (
        cast("DeferredJob | None", Entities.fetch_one(job_id, request=Fetch.direct()))
        if (job_id := change.get("job"))
        else None
    )
    target = change["target"]
    error, failed_entity = _conversion_failure_status(change, job, form, actor)
    return {
        "draft": {
            "name": target["name"],
            "schema": target["schema"],
            "form_type": form.form_type,
            "html_fields": target["html_fields"],
            **({"conversion_instructions": change["instructions"]} if change.get("instructions") else {}),
        },
        "baseline": change["baseline"],
        "image_urls": change["image_urls"],
        "pending_change": {
            "id": change["id"],
            "operation": change.get("job"),
            "phase": change["phase"],
            "status": job.status if job else "failed",
            "progress": job.progress if job else {},
            "error": error,
            "failed_entity": failed_entity,
            "can_cancel": not change["applied"],
        },
    }


# @testable false
# @covered-by lagniappe/core/tools/forms/changes.py::change_response
# @reason status messages and permission-checked failure links are exercised through the browser response
def _conversion_failure_status(
    change: PendingFormChange, job: DeferredJob | None, form: Form, actor: User | None
) -> tuple[str | None, dict[str, object] | None]:
    if job is None:
        return "The form update could not be found. Retry to resume it.", None
    error = job.error or {}
    message = cast(str | None, error.get("message"))
    context = cast(dict[str, str], error.get("context") or {})
    fields = change["target"]["schema"]
    # Already-failed jobs retain their old error string after a deployment.
    prefix = "Invalid converted table cell for column "
    if message and message.startswith(prefix) and message.endswith("."):
        column_id = message[len(prefix):-1]
        column = next((
            column for field in fields for column in conversions._columns(field)
            if column["id"] == column_id
        ), None)
        if column:
            title = column.get("title") or "Untitled column"
            expected = {
                "number": "a number", "checkbox": "a checked or unchecked value",
                "date": "a date", "time": "a time", "email": "an email address",
                "tel": "a phone number", "text": "text", "out": "a web link",
            }.get(conversions.field_kind(column) or "", "a value in the expected format")
            message = f'The AI could not produce {expected} for “{title}”.'
    field = next((
        field for field in fields
        if field["id"] == context.get("form_conversion_field")
    ), None)
    if field and field.get("title") and message:
        message = f'{field["title"]}: {message}'
    failed_entity = None
    if actor is not None and context.get("form_conversion_target"):
        from .schema_updates import require_visible

        entity = Entities.fetch_one(
            context["form_conversion_target"], request=Fetch.direct()
        )
        if isinstance(entity, (Entities.PAGE, Entities.TASK)) and (
            entity.properties.form.key == form.key
        ):
            try:
                require_visible(entity, actor)
            except ValidationError:
                pass
            else:
                failed_entity = {
                    "name": entity.name, "url": entity.url, "kind": entity.kind,
                }
    return message, failed_entity


# @testable false
# @covered-by lagniappe/core/tools/forms/changes.py::apply_target
# @reason each batch reloads its durable Form owner and validates the executing actor
def owned_change(context: DeferredJobContext) -> tuple[Form, PendingFormChange]:
    context.ensure_active()
    from ..deferred_jobs.context import required_input

    form = cast("Form | None", Entities.fetch_one(required_input(context, "form").key, request=Fetch.direct()))
    if not form or not form.allowed(Action.EDIT, user=context.actor):
        raise ValidationError(
            "This Form is unavailable or you no longer have permission to update it."
        )
    change = pending_change(form.db)
    if (
        not change
        or change.get("id") != context.parameters["change_id"]
        or change.get("job") != context.job.urlsafe_key
    ):
        raise MutationConflict("This job no longer owns the form change.")
    context.inputs["form"] = form
    return form, change


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_prepare_target_preserves_completion_and_original_answers
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_deleted_migrated_form_retains_completed_submissions_and_history
# @matrix form-migration : completed-task legacy-generation notice masked-write
def prepare_target(
    entity: Page | Task,
    change: PendingFormChange,
    *,
    ai_values: Mapping[str, object] | None = None,
) -> Page | Task:
    values = json_value(entity.db, "submission")
    converted, notice = conversions.convert_submission(
        values,
        change["operations"],
        previous_notice=migration_notice(entity.db),
        generation=entity.generation,
        zone=change["zone"],
        ai_values=ai_values,
    )
    row = deepcopy(entity.db)
    # Suggestions were prepared against the previous form definition.
    row.pop("autofill_reviews", None)
    if (
        entity.entity_kind == "task"
        and cast("Task", entity).completed
        and not row.get("completed_submission")
    ):
        row["completed_submission"] = json.dumps(
            {
                "submission": values,
                "form_key": database_get.urlsafe_key(entity.properties.form.key),
                "generation": entity.generation,
            }
        )
    for name, value in (("submission", converted), (NOTICE, notice)):
        if value:
            row[name] = json.dumps(value)
        else:
            row.pop(name, None)
    row["generation"] = change["target"]["generation"]
    row["schema_version"] = change["target"]["version"]
    row[RECEIPT] = change["id"]
    check_size(row)
    return type(entity)(cast("DatastoreEntity", row))


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_apply_is_guarded_idempotent_and_retries_effects
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_form_editor_migrates_restricted_submissions
# @matrix form-migration : duplicate-delivery guarded-write effects-retry
# @matrix form-migration : partial-read generation removed-link
# @matrix form-migration : form-authority restricted-submissions
def apply_target(
    context: DeferredJobContext,
    raw: DatastoreEntity,
    *,
    ai_values: Mapping[str, object] | None = None,
) -> None:
    from ...mutations import execute_mutation, planner_for
    from ...mutations.base import MutationPlanBuilder

    form, change = owned_change(context)
    entity = population.load_target(raw)
    if not entity:
        return
    if entity.properties.form.key != form.key:
        raise MutationConflict(
            "A submission changed its attached Form during the update."
        )
    applied = entity.db.get(RECEIPT) == change["id"]
    if not applied and entity.generation != change["source_generation"]:
        raise ValidationError(
            "A submission has an unexpected form generation and needs repair."
        )
    if change.get("require_visibility"):
        from .schema_updates import require_visible

        entity = require_visible(entity, context.actor)
    converted = entity if applied else prepare_target(entity, change, ai_values=ai_values)
    if converted.entity_kind == "page":
        # The converted copy needs its own relations for post-commit projections.
        loaded_page = Entities.fetch_one(converted, request=Fetch.direct())
        if loaded_page is None:
            raise MutationConflict("A submission disappeared during the update.")
        converted = loaded_page
    converted.properties.form.attach({persisted_key(form): form})
    converted._form_change_write = True
    builder = MutationPlanBuilder(
        MutationOperation.SAVE, (converted,), registry=Entities, planner_for=planner_for
    )
    if not applied:
        builder.patch(
            converted,
            "submission",
            "generation",
            "schema_version",
            NOTICE,
            RECEIPT,
            "completed_submission",
            "autofill_reviews",
            reason="form-change-submission",
        )
    else:
        builder.cache_refresh(converted, reason="form-change-retry-effects")
    if entity.entity_kind == "task":
        # Recompute linked Page projections with the effective target definition.
        loaded_task = Entities.fetch_one(
            cast("Task", converted), request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)
        )
        if loaded_task is None:
            raise MutationConflict("A submission disappeared during the update.")
        converted = loaded_task
        converted._form_change_write = True
        converted.linked_pages = cast("list[Page]", Entities.fetch(
            *converted.derived_page_keys, request=Fetch.direct()
        ))
        builder.consume_intents(converted)
        builder.patch(converted, "linked_pages", reason="form-change-links")
        for owner in converted.task_list_owners:
            builder.touch(owner, reason="form-change-task-list")
    else:
        for owner in cast("Page", entity).categories:
            builder.touch(owner, reason="form-change-page-list")
    guards: list[tuple[Key, Mapping[str, object] | None]] = [
        (persisted_key(form), {PENDING: form.db.get(PENDING)}),
        (persisted_key(entity), ExactEntityState(dict(entity.db))),
        (
            persisted_key(context.job),
            {"lease_token": context.job.lease_token, "status": "running"},
        ),
    ]
    outcome = execute_mutation(builder.build(), guards=guards)
    if not outcome.post_commit_complete:
        raise RuntimeError(
            "The form update was saved; its display refresh needs retrying."
        )


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_mutation_guard_blocks_locked_and_stale_answer_writes
# @tests tests_unit/test_004k_form_changes.py::test_new_attachments_adopt_current_generation_without_accepting_stale_answers
# @tests tests_unit/test_004k_form_changes.py::test_pending_change_fences_conflicting_writes
# @matrix form-migration : writer-fence stale-generation completion-race creation reassignment
# @matrix form-migration : pending-delete masked-write attachment
def mutation_guards(
    writes: Sequence[MutationEffect], deletes: Collection[MutationEffect]
) -> list[tuple[Key, Mapping[str, object] | None]]:
    """Fence full and masked mutations without adding constructors or DB read hooks."""
    guards: list[tuple[Key, Mapping[str, object] | None]] = []
    for effect in [*writes, *deletes]:
        entity = effect.entity
        kind = getattr(entity, "entity_kind", None)
        if entity is None or kind not in {"page", "task", "form", "model", "category", "users"}:
            continue
        mask = effect.property_mask
        deleting = any(effect is deletion for deletion in deletes)
        if (
            not deleting
            and mask is not None
            and not set(mask) & {*ANSWER_FIELDS, PENDING, "forms"}
        ):
            continue
        if getattr(entity, "_form_change_write", False):
            continue
        if kind == "form":
            persisted = database_get.entity(entity.key)
            if persisted and pending_change(persisted):
                raise ValidationError(
                    "This Form is being updated. Wait for the update to finish."
                )
            if persisted:
                guards.append((persisted_key(entity), {PENDING: persisted.get(PENDING)}))
            continue
        persisted = database_get.entity(entity.key)
        attached_key = cast("Key | None", entity.db.get("form"))
        keys = {
            attached_key,
            (persisted or {}).get("form"),
            *cast("list[Key]", entity.db.get("forms", [])),
            *(persisted or {}).get("forms", []),
        } - {None}
        forms = {form.key: cast("Form", form) for form in Entities.fetch(*keys, request=Fetch.root())}
        for form in forms.values():
            pending = pending_change(form.db)
            if pending:
                raise ValidationError(
                    "This Form is being updated. These changes were not saved; try again when the update finishes."
                )
            guards.append(
                (
                    persisted_key(form),
                    {
                        PENDING: form.db.get(PENDING),
                        "generation": form.db.get("generation"),
                    },
                )
            )
        form = forms.get(attached_key)
        if kind in {"page", "task"} and form and not deleting:
            entity = cast("Page | Task", entity)
            attached = persisted is None or persisted.get("form") != form.key
            if attached:
                if (
                    entity.db.get("submission")
                    and (entity.form is None or entity.form.generation != form.generation)
                ):
                    raise MutationConflict(
                        "The form fields changed before these answers were prepared. Reload and try again."
                    )
                entity.db["generation"] = form.generation
            elif entity.generation != form.generation:
                raise MutationConflict(
                    "The form fields changed. Reload and reconcile your answers before saving."
                )
            if (
                persisted
                and not attached
                and getattr(entity, "_submission_input_generation", entity.generation)
                != form.generation
            ):
                raise MutationConflict(
                    "The form fields changed. Your older answers were not saved."
                )
            if persisted:
                guards.append(
                    (persisted_key(entity), {name: persisted.get(name) for name in ANSWER_FIELDS})
                )
                if (
                    not attached
                    and (persisted.get("generation", 0) or 0) != entity.generation
                ):
                    raise MutationConflict(
                        "The form fields changed. Your older answers were not saved."
                    )
    return guards


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_recovery_retains_partial_changes_and_cancels_only_before_apply
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_failed_preflight_recovers_after_reload
# @matrix form-migration : retry cancellation ownership
def recover_change(form: Form, actor: User, action: str) -> FormPublication:
    from ..deferred_jobs.service import DeferredJobs
    from ...properties.deferred_job_lifecycle import ACTIVE_STATUSES
    from ...mutations import execute_mutation
    from ...mutations.base import RootMutation
    from ..database import deferred_jobs
    from ..deferred_jobs.locks import deferred_job_lock_key

    loaded = cast("Form | None", Entities.fetch_one(form.key, request=Fetch.direct()))
    if not loaded or not loaded.allowed(Action.EDIT, user=actor):
        raise ValidationError("You do not have permission to update this Form.")
    form = loaded
    pending = pending_change(form.db)
    if not pending:
        return change_response(form, actor)
    job_id = pending.get("job")
    if job_id is None:
        raise MutationConflict("The Form update has no job owner.")
    job = cast("DeferredJob | None", Entities.fetch_one(job_id, request=Fetch.direct()))
    if action == "cancel":
        if pending["applied"]:
            raise ValidationError(
                "Some submissions may already be updated. Retry this change to finish it."
            )
        if job:
            DeferredJobs.cancel(job)
        # The owner marker also fences a worker racing the cancellation.
        expected = form.db[PENDING]
        form.db.pop(PENDING)
        form._form_change_write = True
        execute_mutation(
            RootMutation.plan(form, property_mask=(PENDING,)),
            guards=[(persisted_key(form), {PENDING: expected})],
        )
        deferred_jobs.release_deferred_job_lock(
            deferred_job_lock_key(form, "form-change"), job_id
        )
        from ..database.assets import cleanup_rejected_attempt

        form._form_attempt_assets = pending.get("attempt_assets", [])
        cleanup_rejected_attempt(form)
        return change_response(form, actor)
    if action != "retry":
        raise ValidationError("Unknown form update action.")
    if job and job.status in ACTIVE_STATUSES:
        return change_response(form, actor)
    form._starting_form_change = pending
    if job and (job.checkpoint or {}).get("ai_batch"):
        # A replacement worker must retain prepared but not-yet-applied outputs.
        form._starting_form_change = {**pending, "resume_checkpoint": job.checkpoint}
    DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.FORM_CHANGE,
            actor=actor,
            inputs={"form": form},
            parameters={"change_id": pending["id"], "digest": pending["digest"]},
            notification_body="Resuming form update...",
            notification_target=form,
            idempotency_key=f"form-change:{form.hash}:{uuid4()}",
        )
    )
    resumed = cast("Form | None", Entities.fetch_one(form.key, request=Fetch.direct()))
    if resumed is None:
        raise MutationConflict("The Form was deleted during the update.")
    return change_response(resumed, actor)


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_notice_shows_only_changed_fields_and_cells
# @matrix form-migration : informational-notice changed-cells
def notice_projection(entity: Page | Task | TaskHistory) -> list[dict[str, object]]:
    """A read-only display of changed values; no restore choices or writes."""
    from .. import dates

    notice = migration_notice(entity.db)
    current = json_value(entity.db, "submission")
    schema = {field["id"]: field for field in entity.submission_schema}
    result = []
    zone = str(dates.user_timezone())

    # @testable infrastructure
    def display(value, field):
        if value is None:
            return "Not provided"
        try:
            return conversions._text(value, field, zone)
        except (ValueError, TypeError, KeyError):
            return json.dumps(value, ensure_ascii=False)

    # @testable infrastructure
    def changed(label, before, after, source, target, reason):
        if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
            if target is None:
                reason = "deleted"
            elif after is None:
                reason = "invalid"
            result.append(
                {
                    "label": label,
                    "before": display(before, source),
                    "after": display(after, target or source),
                    "reason": reason,
                }
            )

    for key, original in notice.items():
        source, target = original["schema"], schema.get(key)
        before, after = original.get("value"), current.get(key)
        label = source.get("title") or key
        if source["type"] == "table" and target and target["type"] == "table":
            before = before.get("rows", []) if isinstance(before, dict) else before
            after = after.get("rows", []) if isinstance(after, dict) else after
        if (
            source["type"] == "table"
            and target
            and target["type"] == "table"
            and isinstance(before, list)
            and isinstance(after, list)
        ):
            columns = {column["id"]: column for column in conversions._columns(target)}
            for index, row in enumerate(before):
                for column in conversions._columns(source):
                    cell_id = column["id"]
                    next_row = after[index] if index < len(after) else {}
                    changed(
                        f"{label} · Row {index + 1} · {column.get('title', cell_id)}",
                        row.get(cell_id),
                        next_row.get(cell_id),
                        column,
                        columns.get(cell_id),
                        original.get("reason"),
                    )
        else:
            changed(label, before, after, source, target, original.get("reason"))
    return result
