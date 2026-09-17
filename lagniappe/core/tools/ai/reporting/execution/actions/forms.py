"""Form schema and submission mutation report actions."""

import copy

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities

from .common import _data, _require_allowed
from .results import (
    _entity_result,
)
from .references import _resolve_entity


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_rejects_schema_update_without_form_edit_permission
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_adds_schema_fields_persists_all_task_values_and_completes
# @matrix ai-report submission : schema-update
# @matrix ai-report form-schema : deterministic-run permission-failure schema-update
# @matrix ai-report submission : persistence
def _update_form_schema(action, report, user, created, context):
    from lagniappe.core.definitions import Fetch
    from lagniappe.core.tools import (
        form_changes,
        form_conversions,
        form_drafts,
        form_schema_updates,
    )
    from lagniappe.core.tools.deferred_jobs.errors import (
        DeferredJobDependencyPendingError,
        DeferredJobDependencyFailedError,
    )

    data = _data(action)
    form = _resolve_entity(
        data.get("form") or data.get("form_action"), created, expected=Entities.FORM
    )
    _require_allowed(
        form.allowed(Action.EDIT, user=user),
        "You do not have permission to update this form schema.",
    )
    record = context["action_record"]
    migration_id = record.get("migration_id")
    pending = form_changes.json_value(form.db, form_changes.PENDING)
    receipt = form_changes.json_value(form.db, "form_draft_receipt")
    if migration_id and pending.get("id") == migration_id:
        job = Entities.fetch_one(pending.get("job"), request=Fetch.direct())
        if job is None or job.status in {"failed", "cancelled", "superseded"}:
            raise DeferredJobDependencyFailedError(
                "The Form migration needs attention. Retry this report to resume it."
            )
        raise DeferredJobDependencyPendingError(
            "Waiting for Form migration publication."
        )
    if migration_id and receipt.get("id") == migration_id:
        return (
            form,
            [],
            {
                "form": _entity_result(form),
                "schema_updates": {"applied": data["operations"], "skipped": []},
                "note": "Form schema and submissions updated.",
            },
        )
    if (
        data.get("baseline")
        and data["baseline"] != form_drafts.builder_draft(form)["baseline"]
    ):
        raise exceptions.ValidationError(form_schema_updates.STALE_MESSAGE)
    previous = copy.deepcopy(form.schema)
    schema = form_schema_updates.apply_operations(
        previous, data["operations"], form.form_type
    )
    changes = form_conversions.classify_changes(previous, schema)
    if not changes:
        form.set_schema(schema)
        return (
            form,
            [form],
            {
                "form": _entity_result(form),
                "previous_schema": previous,
                "schema_updates": {"applied": data["operations"], "skipped": []},
            },
        )
    if not action.get("_schema_change"):
        raise exceptions.ValidationError(
            "This schema migration needs a fresh preview and user review before execution."
        )
    migration_id = migration_id or record["idempotency_key"]
    record.update(migration_id=migration_id, migration_form=form.urlsafe_key)
    Entities.save(report)
    draft = form_drafts.builder_draft(form)
    draft.pop("baseline")
    draft.update(
        schema=schema,
        image_manifest=[],
        migration={
            "version": form_conversions.VERSION,
            "clear_invalid": True,
        },
    )
    response = form_changes.start_change(
        form, draft, migration_id, user, report=report, schema_action=action
    )
    if response.get("pending_change"):
        raise DeferredJobDependencyPendingError(
            "Waiting for Form migration publication."
        )
    if response.get("rejected_change"):
        raise exceptions.ValidationError(response["rejected_change"]["error"])
    form = Entities.fetch_one(form.key, request=Fetch.direct())
    if form_changes.json_value(form.db, "form_draft_receipt").get("id") != migration_id:
        raise DeferredJobDependencyFailedError(
            "The Form migration did not publish. Refresh the schema preview and review a new proposal."
        )
    return (
        form,
        [],
        {
            "form": _entity_result(form),
            "schema_updates": {"applied": data["operations"], "skipped": []},
            "note": "Form schema and submissions updated.",
        },
    )
