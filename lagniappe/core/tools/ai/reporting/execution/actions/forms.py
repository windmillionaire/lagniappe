"""Form schema and submission mutation report actions."""

import copy

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.properties.schema import SchemaValidationError, canonicalize_schema

from .common import (
    SUBMISSION_UPDATE_ROWS_ERROR,
    _data,
    _require_allowed,
    _unique_entities,
)
from .results import (
    _entity_result,
)
from .references import (
    _load_result_entity,
    _resolve_entity,
)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_skips_empty_submission_update_and_continues
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_detail_skips_schema_section_and_runs_submission_updates
# @pair ai-report:batch-field-patch
# @pair ai-report:deterministic-run
# @pair ai-report:empty-update
# @pair submission:continue
# @pair submission:deterministic-run
# @pair submission:empty-update
# @pair submission:recoverable
def _update_submission_fields(action, _report, user, created):
    data = _data(action)
    updates = data.get("updates") or []
    if not isinstance(updates, list):
        raise exceptions.ValidationError("Submission update action requires updates.")
    if not updates:
        raise exceptions.ValidationError(SUBMISSION_UPDATE_ROWS_ERROR)

    applied = []
    skipped = []
    previous = []
    to_save = []
    for index, update in enumerate(updates, 1):
        if not isinstance(update, dict):
            skipped.append({"index": index, "reason": "Update row must be an object."})
            continue

        entity = _resolve_submission_update_entity(update, created)
        _require_allowed(
            entity.allowed(Action.EDIT, user=user),
            "You do not have permission to update this submission.",
        )
        schema_id = update.get("schema_id") or update.get("field_id")
        if not isinstance(schema_id, str) or not schema_id.strip():
            skipped.append({"index": index, "reason": "Missing schema_id."})
            continue
        schema_id = schema_id.strip()

        before = _submission_previous_value(entity, schema_id)
        try:
            changed, note = _apply_submission_field_update(
                entity,
                schema_id,
                update.get("new_value"),
            )
        except Exception as error:
            skipped.append(
                {
                    "index": index,
                    "entity": _entity_result(entity),
                    "schema_id": schema_id,
                    "reason": str(error),
                }
            )
            continue

        if not changed:
            skipped.append(
                {
                    "index": index,
                    "entity": _entity_result(entity),
                    "schema_id": schema_id,
                    "reason": note or "Value did not change.",
                }
            )
            continue

        record = {
            "index": index,
            "entity": _entity_result(entity),
            "schema_id": schema_id,
        }
        applied.append(record)
        previous.append(
            {
                **record,
                "had_value": before["had_value"],
                "previous_value": before["value"],
            }
        )
        to_save.append(entity)

    return (
        None,
        _unique_entities(to_save),
        {
            "updates": {"applied": applied, "skipped": skipped},
            "previous": previous,
            "note": _update_summary_note("Updated", applied, skipped),
        },
    )


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_rejects_schema_update_without_form_edit_permission
# @pair ai-report:schema-update
# @pair ai-report:deterministic-run
# @pair ai-report:permission-failure
# @pair form-schema:deterministic-run
# @pair form-schema:schema-update
# @pair form-schema:permission-failure
def _update_form_schema(action, _report, user, created):
    data = _data(action)
    form = _resolve_entity(
        data.get("form")
        or data.get("form_id")
        or data.get("form_ref")
        or data.get("form_action"),
        created,
        expected=Entities.FORM,
    )
    _require_allowed(
        form.allowed(Action.EDIT, user=user),
        "You do not have permission to update this form schema.",
    )
    if getattr(form, "reserved", False):
        raise exceptions.ValidationError("Reserved forms cannot be updated by reports.")

    operations = data.get("operations") or []
    if not isinstance(operations, list):
        raise exceptions.ValidationError("Schema update action requires operations.")

    previous_schema = copy.deepcopy(form.schema or [])
    schema = copy.deepcopy(previous_schema)
    applied = []
    skipped = []
    for index, operation in enumerate(operations, 1):
        if not isinstance(operation, dict):
            skipped.append({"index": index, "reason": "Operation must be an object."})
            continue
        op = operation.get("op") or operation.get("type")
        if op == "add_field":
            result = _schema_add_field(schema, operation.get("field"))
        elif op == "add_select_option":
            result = _schema_add_select_option(schema, operation)
        else:
            result = None, "Unsupported schema operation."

        change, reason = result
        if change:
            applied.append({"index": index, **change})
        else:
            skipped.append({"index": index, "reason": reason})

    if applied:
        form.set_schema(schema)

    return (
        form,
        [form] if applied else [],
        {
            "form": _entity_result(form),
            "schema_updates": {"applied": applied, "skipped": skipped},
            "previous_schema": previous_schema,
            "note": _update_summary_note("Updated schema with", applied, skipped),
        },
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_submission_fields
# @reason row entity resolution is covered through batch submission report-run tests
def _resolve_submission_update_entity(update, created):
    page_reference = (
        update.get("page")
        or update.get("page_id")
        or update.get("page_ref")
        or update.get("page_action")
    )
    task_reference = (
        update.get("task")
        or update.get("task_id")
        or update.get("task_ref")
        or update.get("task_action")
    )
    if bool(page_reference) == bool(task_reference):
        raise exceptions.ValidationError(
            "Submission update rows require exactly one page or task reference."
        )
    if page_reference:
        return _resolve_entity(page_reference, created, expected=Entities.PAGE)
    return _resolve_entity(task_reference, created, expected=Entities.TASK)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_submission_fields
# @reason previous value capture is covered through undo tests
def _submission_previous_value(entity, schema_id):
    submission = getattr(entity, "submission", None)
    if not isinstance(submission, dict):
        submission = {}
    return {
        "had_value": schema_id in submission,
        "value": copy.deepcopy(submission.get(schema_id)),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_submission_fields
# @reason validation behavior is covered through batch submission report-run tests
def _apply_submission_field_update(entity, schema_id, value):
    if not getattr(entity, "form", None):
        return False, "Target has no form."

    submission = entity.properties.submission
    field = submission.fields.get(schema_id)
    if not field:
        return False, "Field is not in the target's current form schema."

    before = _submission_previous_value(entity, schema_id)
    field.reset()
    field.validate_ai(value)
    entity.save_submission()
    after = _submission_previous_value(entity, schema_id)
    changed = (
        before["had_value"] != after["had_value"] or before["value"] != after["value"]
    )
    if not changed:
        return False, "Value did not change after validation."
    return True, None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_form_schema
# @reason schema operation parsing is covered through schema update report-run tests
def _schema_add_field(schema, raw_field):
    field = _safe_schema_field(raw_field)
    if not field:
        return None, "Field definition is not valid for additive schema updates."
    if any(existing.get("id") == field["id"] for existing in schema):
        return None, f"Field {field['id']} already exists."

    schema.append(field)
    return {
        "op": "add_field",
        "schema_id": field["id"],
        "label": field.get("label") or field.get("title") or field["id"],
    }, None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_form_schema
# @reason schema operation parsing is covered through schema update report-run tests
def _schema_add_select_option(schema, operation):
    schema_id = operation.get("schema_id") or operation.get("field_id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        return None, "Missing schema_id."
    schema_id = schema_id.strip()

    field = next(
        (
            candidate
            for candidate in schema
            if isinstance(candidate, dict) and candidate.get("id") == schema_id
        ),
        None,
    )
    if not field:
        return None, f"Field {schema_id} was not found."
    if field.get("type") not in {"select", "radio"}:
        return None, f"Field {schema_id} is not a select or radio field."

    option = operation.get("option") or {}
    value = option.get("value") if isinstance(option, dict) else None
    label = option.get("label") if isinstance(option, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None, "Option value is required."
    if not isinstance(label, str) or not label.strip():
        return None, "Option label is required."
    value = value.strip()
    label = label.strip()

    options = field.setdefault("options", [])
    if not isinstance(options, list):
        field["options"] = options = []
    if any(
        option.get("value") == value for option in options if isinstance(option, dict)
    ):
        return None, f"Option {value} already exists."

    options.append({"value": value, "label": label})
    return {
        "op": "add_select_option",
        "schema_id": schema_id,
        "value": value,
        "label": label,
    }, None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_form_schema
# @reason field sanitization is covered through schema update report-run tests
def _safe_schema_field(raw_field):
    if not isinstance(raw_field, dict):
        return None
    field = copy.deepcopy(raw_field)
    schema_id = field.get("id")
    if not isinstance(schema_id, str) or not schema_id.strip():
        return None
    field["id"] = schema_id.strip()
    if field.get("type") in {"html", "signature"}:
        return None

    field["required"] = False
    field.pop("visibility", None)
    try:
        return canonicalize_schema([field])[0]
    except (IndexError, SchemaValidationError):
        return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_submission_fields
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_form_schema
# @reason user-facing notes are asserted through report-run result tests
def _update_summary_note(prefix, applied, skipped):
    count = len(applied or [])
    skipped_count = len(skipped or [])
    if count and skipped_count:
        return f"{prefix} {count}; skipped {skipped_count}."
    if count:
        return f"{prefix} {count}."
    if skipped_count:
        return f"No changes applied; skipped {skipped_count}."
    return "No changes applied."


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @pair ai-report:batch-field-patch
# @pair ai-report:undo
def _undo_submission_updates(action, user):
    restored = []
    skipped = []
    to_save = []
    for previous in action.get("previous") or []:
        entity = _load_result_entity(previous.get("entity"))
        if entity is None:
            skipped.append({**previous, "reason": "Entity is missing."})
            continue
        _require_allowed(
            entity.allowed(Action.EDIT, user=user),
            "You do not have permission to restore this submission.",
        )
        schema_id = previous.get("schema_id")
        if not schema_id:
            skipped.append({**previous, "reason": "Missing schema_id."})
            continue
        _restore_submission_field(
            entity,
            schema_id,
            previous.get("had_value"),
            previous.get("previous_value"),
        )
        restored.append(
            {
                "entity": _entity_result(entity),
                "schema_id": schema_id,
            }
        )
        to_save.append(entity)

    if to_save:
        Entities.save(*_unique_entities(to_save))
    return {
        "updates": {"applied": restored, "skipped": skipped},
        "note": _update_summary_note("Restored", restored, skipped),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_undo_submission_updates
# @reason field restoration is covered through public undo tests
def _restore_submission_field(entity, schema_id, had_value, previous_value):
    if getattr(entity, "form", None):
        field = entity.properties.submission.fields.get(schema_id)
        if field is not None:
            if had_value:
                field.db_value = previous_value
            else:
                field.unset()
            entity.save_submission()
            return

    submission = dict(getattr(entity, "submission", None) or {})
    if had_value:
        submission[schema_id] = previous_value
    else:
        submission.pop(schema_id, None)
    entity.properties.submission.value = submission or None
    if getattr(entity, "form", None):
        entity.db["schema_version"] = entity.form.version


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @pair ai-report:schema-update
# @pair ai-report:undo
def _undo_form_schema_update(action, user):
    form = _load_result_entity(action.get("entity")) or _load_result_entity(
        action.get("form")
    )
    if form is None:
        return {"note": "Form already missing."}
    _require_allowed(
        form.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this form schema.",
    )
    previous_schema = action.get("previous_schema")
    if not isinstance(previous_schema, list):
        return {"entity": _entity_result(form), "note": "Previous schema missing."}

    form.set_schema(previous_schema)
    Entities.save(form)
    return {
        "entity": _entity_result(form),
        "note": "Restored previous form schema.",
    }
