"""Saved form changes, explicit generation readers, and guarded batch application."""

from copy import deepcopy
import json
from uuid import uuid4

from ..definitions import (
    Action,
    DeferredJobSpec,
    DeferredJobType,
    Fetch,
    FetchReason,
    MutationOperation,
)
from ..entities import Entities
from ..exceptions import MutationConflict, ValidationError
from . import form_conversions as conversions
from .database import get as database_get
from .database.core import KINDS
from .database.filter import Filter, Query
from .database.utility import ExactEntityState


PENDING = "pending_form_change"
NOTICE = "pre_migration"
RECEIPT = "form_change_receipt"
BATCH_SIZE = 50
ANSWER_FIELDS = (
    "form",
    "submission",
    "generation",
    "completed",
    "completed_submission",
    "assets",
)


# @testable false
# @covered-by lagniappe/core/tools/form_changes.py::start_change
# @covered-by lagniappe/core/tools/form_changes.py::apply_target
# @reason persisted JSON is read explicitly at job, mutation, and projection boundaries
def json_value(raw, name):
    value = raw.get(name)
    value = json.loads(value) if isinstance(value, str) else deepcopy(value)
    if value is not None and not isinstance(value, dict):
        raise ValidationError("Saved form change data needs repair.")
    return value or {}


# @testable false
# @covered-by lagniappe/core/tools/form_changes.py::apply_target
# @reason bounded records are checked before any live answer is changed
def check_size(raw):
    if (
        len(json.dumps(dict(raw), default=str, ensure_ascii=False).encode())
        > 900 * 1024
    ):
        raise ValidationError(
            "A submission or Form is too large to retain its changed values. No further changes were applied."
        )


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_pending_definition_resolves_each_generation
# @matrix form-migration : partial-read generation
def target_definition(form, change=None):
    change = change or json_value(form.db, PENDING)
    if not change:
        return form
    target = change["target"]
    row = deepcopy(form.db)
    row.pop(PENDING, None)
    for name in ("schema", "assets"):
        row[name] = json.dumps(target[name])
    for name in ("name", "generation", "version"):
        row[name] = target[name]
    result = Entities.FORM(row)
    result._pending_html = deepcopy(target["html_fields"])
    return result


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_pending_definition_resolves_each_generation
# @matrix form-migration : partial-read generation
def effective_definition(entity, form):
    if not form:
        return form
    change = json_value(getattr(form, "db", {}), PENDING)
    if change and entity.generation == change["target"]["generation"]:
        return target_definition(form, change)
    return form


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_start_stages_intent_without_enumerating_submissions
# @matrix form-migration : save no-submission-read durable-intent
def start_change(form, draft, save_id, actor, *, images=None, report=None, schema_action=None):
    from . import dates, form_drafts
    from .deferred_jobs.service import DeferredJobs
    from .database.assets import cleanup_rejected_attempt

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
    schema = form_drafts.validate_draft_schema(draft["schema"], form.form_type)
    operations = conversions.classify_changes(
        form.schema, schema, migration.get("mappings")
    )
    if not operations:
        raise ValidationError("There are no submission changes to apply.")
    pending = json_value(form.db, PENDING)
    digest = form_drafts._digest(draft)
    if pending:
        if pending["id"] != save_id or pending["digest"] != digest:
            raise ValidationError("A form change is already saved. Wait for it to finish before modifying this form.")
        return change_response(form, actor)
    from . import form_schema_updates
    from ..definitions import AI

    ai_fields = {change["id"] for change in operations if change["rule"] == "ai"}
    instructions = migration.get("instructions") or {}
    if not isinstance(instructions, dict) or set(instructions) - ai_fields or any(
        not isinstance(value, str) or len(value) > 4000 for value in instructions.values()
    ):
        raise ValidationError("Conversion instructions must name AI-converted fields and contain at most 4000 characters each.")
    if ai_fields and report is None and not actor.access(AI.CREATE):
        raise ValidationError("This user does not have the required AI access.")
    if ai_fields or report is not None:
        scope = form_schema_updates.inspect_scope(form, operations, actor)
        expected_scope = (schema_action or {}).get("data", {}).get("scope_fingerprint")
        if expected_scope and scope["scope_fingerprint"] != expected_scope:
            raise ValidationError(form_schema_updates.STALE_MESSAGE)
    target = Entities.FORM(deepcopy(form.db))
    target.name = draft["name"].strip()
    target.set_schema(schema)
    target.generation = form.generation + 1
    form_drafts._validate_content(schema, draft["html_fields"], images or {})
    committed = False
    try:
        image_urls = form_drafts._stage_content(
            target, draft["html_fields"], images or {}
        )
        form_drafts.stage_form_content(target)
        target.properties.version.update()
        change = {
            "id": save_id,
            "digest": digest,
            "source_generation": form.generation,
            "baseline": form_drafts.builder_draft(form)["baseline"],
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
                "version": target.version,
                "html_fields": {
                    field["id"]: target.get_html_field(field["id"]) or ""
                    for field in target.schema
                    if field["type"] == "html"
                },
            },
        }
        if report is not None:
            from ..properties.ai_report_proposal import proposal_fingerprint

            change["report"] = report.urlsafe_key
            change["report_fingerprint"] = proposal_fingerprint(report.proposal)
            change["action_id"] = schema_action["id"]
            change["scope_fingerprint"] = schema_action["data"].get("scope_fingerprint")
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
    current = Entities.fetch_one(form.key, request=Fetch.direct())
    return change_response(current, actor)


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_conversion_failure_status_names_columns_and_checks_target_visibility
# @matrix form-migration : status recovery permissions
def change_response(form, actor=None):
    from . import form_drafts

    change = json_value(form.db, PENDING)
    if not change:
        receipt = json_value(form.db, "form_draft_receipt")
        response = form_drafts._saved_response(form, receipt.get("image_urls", {}))
        rejection = json_value(form.db, "form_change_rejection")
        if rejection:
            response["rejected_change"] = rejection
        return response
    job = (
        Entities.fetch_one(change["job"], request=Fetch.direct())
        if change.get("job")
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
# @covered-by lagniappe/core/tools/form_changes.py::change_response
# @reason status messages and permission-checked failure links are exercised through the browser response
def _conversion_failure_status(change, job, form, actor):
    if job is None:
        return "The form update could not be found. Retry to resume it.", None
    error = job.error or {}
    message = error.get("message")
    context = error.get("context") or {}
    fields = change["target"]["schema"]
    # Already-failed jobs retain their old error string after a deployment.
    prefix = "Invalid converted table cell for column "
    if message and message.startswith(prefix) and message.endswith("."):
        column_id = message[len(prefix):-1]
        column = next((
            column for field in fields for column in field.get("columns", [])
            if column["id"] == column_id
        ), None)
        if column:
            title = column.get("title") or "Untitled column"
            expected = {
                "number": "a number", "checkbox": "a checked or unchecked value",
                "date": "a date", "time": "a time", "email": "an email address",
                "tel": "a phone number", "text": "text", "out": "a web link",
            }.get(conversions.field_kind(column), "a value in the expected format")
            message = f'The AI could not produce {expected} for “{title}”.'
    field = next((
        field for field in fields
        if field["id"] == context.get("form_conversion_field")
    ), None)
    if field and field.get("title") and message:
        message = f'{field["title"]}: {message}'
    failed_entity = None
    if actor is not None and context.get("form_conversion_target"):
        from .form_schema_updates import require_visible

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
# @covered-by lagniappe/core/tools/form_changes.py::apply_target
# @reason each batch reloads its durable Form owner and validates the executing actor
def owned_change(context):
    context.ensure_active()
    form = Entities.fetch_one(context.input("form").key, request=Fetch.direct())
    if not form or not form.allowed(Action.EDIT, user=context.actor):
        raise ValidationError(
            "This Form is unavailable or you no longer have permission to update it."
        )
    change = json_value(form.db, PENDING)
    if (
        not change
        or change.get("id") != context.parameters["change_id"]
        or change.get("job") != context.job.urlsafe_key
    ):
        raise MutationConflict("This job no longer owns the form change.")
    context.inputs["form"] = form
    return form, change


# @testable false
# @covered-by lagniappe/core/tools/form_changes.py::apply_target
# @reason application and preflight use the same uncapped membership query, one bounded page at a time
def target_batch(form, cursor=None):
    return (
        Query(KINDS.instances)
        .filter(Filter().eq("form", form.key))
        .order("__key__")
        .limit(BATCH_SIZE)
        .cursor(cursor)
        .fetch()
    )


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_form_authority_migrates_restricted_submissions
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_form_editor_migrates_restricted_submissions
# @matrix form-migration : form-authority restricted-submissions
def load_target(raw):
    if raw.get("type") not in {"page", "task"}:
        return None
    # The owning form authorizes schema migration across all attached submissions.
    # Page/Task permissions still govern viewing and directly editing their values.
    return Entities.fetch_one(raw, request=Fetch.direct())


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_prepare_target_preserves_completion_and_original_answers
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_deleted_migrated_form_retains_completed_submissions_and_history
# @matrix form-migration : completed-task legacy-generation notice masked-write
def prepare_target(entity, change, *, ai_values=None):
    values = json_value(entity.db, "submission")
    converted, notice = conversions.convert_submission(
        values,
        change["operations"],
        previous_notice=json_value(entity.db, NOTICE),
        generation=entity.generation,
        zone=change["zone"],
        ai_values=ai_values,
    )
    row = deepcopy(entity.db)
    if (
        entity.entity_kind == "task"
        and entity.completed
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
    return type(entity)(row)


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_apply_is_guarded_idempotent_and_retries_effects
# @tests tests_e2e/003_forms/test_003g_form_changes.py::test_form_editor_migrates_restricted_submissions
# @matrix form-migration : duplicate-delivery guarded-write effects-retry
# @matrix form-migration : partial-read generation removed-link
# @matrix form-migration : form-authority restricted-submissions
def apply_target(context, raw, *, ai_values=None):
    from ..mutations import execute_mutation
    from ..mutations.base import MutationPlanBuilder

    form, change = owned_change(context)
    entity = load_target(raw)
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
        from .form_schema_updates import require_visible

        entity = require_visible(entity, context.actor)
    converted = entity if applied else prepare_target(entity, change, ai_values=ai_values)
    if converted.entity_kind == "page":
        # The converted copy needs its own relations for post-commit projections.
        converted = Entities.fetch_one(converted, request=Fetch.direct())
    converted.properties.form.attach({form.key: form})
    converted._form_change_write = True
    builder = MutationPlanBuilder(
        MutationOperation.SAVE, (converted,), registry=Entities
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
            reason="form-change-submission",
        )
    else:
        builder.cache_refresh(converted, reason="form-change-retry-effects")
    if entity.entity_kind == "task":
        # Recompute linked Page projections with the effective target definition.
        converted = Entities.fetch_one(
            converted, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)
        )
        converted._form_change_write = True
        converted.linked_pages = Entities.fetch(
            *converted.derived_page_keys, request=Fetch.direct()
        )
        builder.consume_intents(converted)
        builder.patch(converted, "linked_pages", reason="form-change-links")
        for owner in converted.task_list_owners:
            builder.touch(owner, reason="form-change-task-list")
    else:
        for owner in entity.categories:
            builder.touch(owner, reason="form-change-page-list")
    guards = [
        (form.key, {PENDING: form.db.get(PENDING)}),
        (entity.key, ExactEntityState(dict(entity.db))),
        (
            context.job.key,
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
def mutation_guards(writes, deletes):
    """Fence full and masked mutations without adding constructors or DB read hooks."""
    guards = []
    for effect in [*writes, *deletes]:
        entity = effect.entity
        kind = getattr(entity, "entity_kind", None)
        if kind not in {"page", "task", "form", "model", "category", "users"}:
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
            if persisted and json_value(persisted, PENDING):
                raise ValidationError(
                    "This Form is being updated. Wait for the update to finish."
                )
            if persisted:
                guards.append((entity.key, {PENDING: persisted.get(PENDING)}))
            continue
        persisted = database_get.entity(entity.key)
        keys = {
            entity.db.get("form"),
            (persisted or {}).get("form"),
            *entity.db.get("forms", []),
            *(persisted or {}).get("forms", []),
        } - {None}
        forms = {form.key: form for form in Entities.fetch(*keys, request=Fetch.root())}
        for form in forms.values():
            pending = json_value(form.db, PENDING)
            if pending:
                raise ValidationError(
                    "This Form is being updated. These changes were not saved; try again when the update finishes."
                )
            guards.append(
                (
                    form.key,
                    {
                        PENDING: form.db.get(PENDING),
                        "generation": form.db.get("generation"),
                    },
                )
            )
        form = forms.get(entity.db.get("form"))
        if kind in {"page", "task"} and form and not deleting:
            attached = persisted is None or persisted.get("form") != form.key
            if attached:
                if (
                    entity.db.get("submission")
                    and entity.form.generation != form.generation
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
                    (entity.key, {name: persisted.get(name) for name in ANSWER_FIELDS})
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
def recover_change(form, actor, action):
    from .deferred_jobs.service import DeferredJobs
    from ..properties.deferred_job_lifecycle import ACTIVE_STATUSES
    from ..mutations import execute_mutation
    from ..mutations.base import RootMutation
    from .database import deferred_jobs
    from .deferred_jobs.locks import deferred_job_lock_key

    form = Entities.fetch_one(form.key, request=Fetch.direct())
    if not form or not form.allowed(Action.EDIT, user=actor):
        raise ValidationError("You do not have permission to update this Form.")
    pending = json_value(form.db, PENDING)
    if not pending:
        return change_response(form, actor)
    job = Entities.fetch_one(pending["job"], request=Fetch.direct())
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
            guards=[(form.key, {PENDING: expected})],
        )
        deferred_jobs.release_deferred_job_lock(
            deferred_job_lock_key(form, "form-change"), pending["job"]
        )
        from .database.assets import cleanup_rejected_attempt

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
    return change_response(Entities.fetch_one(form.key, request=Fetch.direct()), actor)


# @testable true
# @tests tests_unit/test_004k_form_changes.py::test_notice_shows_only_changed_fields_and_cells
# @matrix form-migration : informational-notice changed-cells
def notice_projection(entity):
    """A read-only display of changed values; no restore choices or writes."""
    from . import dates

    notice = json_value(entity.db, NOTICE)
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
            columns = {column["id"]: column for column in target.get("columns", [])}
            for index, row in enumerate(before):
                for column in source.get("columns", []):
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
