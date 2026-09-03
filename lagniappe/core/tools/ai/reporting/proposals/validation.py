"""Behavior-preserving validation for stored AI report proposals."""

import re

from lagniappe.core import exceptions
from lagniappe.core.properties.schema import SchemaFields
from lagniappe.core.tools import dates

from ...debug import ai_debug
from ...references import normalize_hash_references, render_ai_markdown
from ..contracts.actions import ALLOWED_ACTIONS
from ..schedules import validate_task_schedule
from .references import (
    _data_action_reference,
    _data_action_references,
    _first_data_reference,
    _has_form_reference_or_label,
    _proposal_file_refs,
    _proposal_string,
    _strip_action_reference,
)

ENTITY_PAIR_ACTION_REFERENCES = {
    "add_form_to_page": ("page", ("form",)),
    "add_category": ("page", ("category", "model")),
    "move_page": ("page", ("category", "model")),
    "move_task": ("task", ("to_page", "page")),
}


# @testable true
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_renders_page_document_markdown
# @pairs ai-report:proposal ai-report:validation editor:document markdown:html-sanitization
def normalize_report_markdown(proposal, *, preserve_markdown=False):
    """Render new model-facing Markdown fields into legacy executable HTML."""
    if not isinstance(proposal, dict):
        return proposal
    actions = proposal.get("actions")
    if not isinstance(actions, list):
        return proposal
    for action in actions:
        if not isinstance(action, dict) or action.get("type") != "create_page":
            continue
        data = action.get("data")
        if not isinstance(data, dict) or "document_markdown" not in data:
            continue
        source = data.get("document_markdown")
        if not isinstance(source, str):
            raise exceptions.AIException(
                "Create page document_markdown must be a string."
            )
        data["document"] = render_ai_markdown(source)
        if not preserve_markdown:
            data.pop("document_markdown", None)
    return proposal


# @testable true
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_rejects_unknown_actions_and_bad_dependencies
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_rejects_unsafe_schema_update_operations
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_requires_completed_root_task_targets
# @tests tests_unit/test_020f_ai_report_completion.py::test_validate_proposal_accepts_add_form_to_page_without_category
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_requires_move_entity_references*
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_accepts_rename_and_move_task_target_aliases
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_requires_every_report_file_attachment
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_requires_external_file_summaries
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_treats_action_like_submission_fields_as_content
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_rejects_future_completed_dates
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_rejects_invalid_static_form_content
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_accepts_virtual_user_kind_as_personal_page
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_requires_create_task_page_reference
# @matrix ai-report : action-reference-namespace canonical-target completed-task dependencies explicit-task-identity file-placement file-summary future-date legacy-target move-references no-category page-form proposal rename schema-update submission task-page validation
# @pairs ai-report:reference-kind permissions:personal-page
def validate_proposal(
    proposal,
    allowed_actions=None,
    allow_empty_submission_updates=False,
    require_pending_submission_target=False,
    allow_pending_submissions=False,
    required_file_refs=None,
    require_file_summaries=False,
    validate_reference_kinds=False,
    user=None,
    preserve_document_markdown=False,
    resolved_reference_details=None,
):
    """Validate the JSON action proposal returned by the organize prompt."""
    allowed = ALLOWED_ACTIONS if allowed_actions is None else frozenset(allowed_actions)
    raw_proposal = proposal
    submitted_required_file_refs = list(required_file_refs or ())
    if resolved_reference_details is None:
        resolved_reference_details = {}
    normalized = normalize_hash_references(
        {
            "proposal": proposal,
            "required_file_refs": submitted_required_file_refs,
        },
        resolved_details=resolved_reference_details,
    )
    proposal = normalized["proposal"]
    required_file_refs = normalized["required_file_refs"]
    if not isinstance(proposal, dict):
        raise exceptions.AIException("Report proposal must be a JSON object.")
    proposal = normalize_report_markdown(
        proposal,
        preserve_markdown=preserve_document_markdown,
    )

    issues = proposal.get("issues")
    if issues is None:
        proposal["issues"] = []
    elif not isinstance(issues, list) or any(
        not isinstance(issue, str) for issue in issues
    ):
        raise exceptions.AIException(
            "Report proposal issues must be a list of strings."
        )

    actions = proposal.get("actions")
    if not isinstance(actions, list):
        raise exceptions.AIException("Report proposal must include actions.")

    seen_ids = set()
    seen_actions = {}
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise exceptions.AIException("Each report action must be an object.")

        action_type = action.get("type")
        if action_type not in ALLOWED_ACTIONS:
            raise exceptions.AIException(f"Unknown report action: {action_type}")
        if action_type not in allowed:
            raise exceptions.AIException(
                f"Report action not allowed for this user: {action_type}"
            )

        action_id = action.get("id")
        if action_id:
            if not isinstance(action_id, str):
                raise exceptions.AIException("Report action ids must be strings.")
            if action_id in seen_ids:
                raise exceptions.AIException(
                    f"Duplicate report action id: {action_id}"
                )

        action_label = f"{action_id or index + 1} ({action_type})"
        _validate_action_data_shape(
            action,
            action_label,
            allow_empty_submission_updates=allow_empty_submission_updates,
            require_pending_submission_target=require_pending_submission_target,
            allow_pending_submissions=allow_pending_submissions,
            require_file_summary_terms=require_file_summaries,
            user=user,
        )
        _validate_completed_task_target_action(
            action,
            action_label,
            seen_actions,
        )
        if validate_reference_kinds:
            raw_actions = (
                raw_proposal.get("actions") if isinstance(raw_proposal, dict) else None
            )
            raw_action = (
                raw_actions[index]
                if isinstance(raw_actions, list) and index < len(raw_actions)
                else action
            )
            _validate_existing_reference_kinds(
                raw_action,
                action_label,
                resolved_reference_details,
            )
        _clean_action_dependencies(proposal, action, seen_ids, action_label)

        for dependency in _data_action_references(action.get("data") or {}):
            if dependency not in seen_ids:
                raise exceptions.AIException(
                    f"Action {action_label} depends on unknown or later "
                    f"action {dependency}."
                )

        if action_id:
            seen_ids.add(action_id)
            seen_actions[action_id] = action

    if required_file_refs:
        attached_file_refs = {
            action.get("data", {}).get("file")
            for action in actions
            if isinstance(action, dict)
            and action.get("type") in {"attach_file_to_page", "attach_file_to_task"}
            and action.get("skip") is not True
            and isinstance(action.get("data"), dict)
            and _proposal_string(action["data"].get("file"))
            and (
                _first_data_reference(action["data"], "page")
                if action.get("type") == "attach_file_to_page"
                else _first_data_reference(action["data"], "task")
            )
        }
        missing_file_refs = [
            submitted_file_ref
            for file_ref, submitted_file_ref in zip(
                required_file_refs,
                submitted_required_file_refs,
                strict=True,
            )
            if file_ref not in attached_file_refs
        ]
        if missing_file_refs:
            raise exceptions.AIException(
                "Organize proposal must attach every report input file to a page "
                "or task. Missing report_file_ref values: "
                f"{', '.join(str(file_ref) for file_ref in missing_file_refs)}"
            )

        if require_file_summaries:
            summary_counts = {}
            for action in actions:
                if (
                    not isinstance(action, dict)
                    or action.get("type") != "summarize_file"
                    or action.get("skip") is True
                    or not isinstance(action.get("data"), dict)
                ):
                    continue
                file_ref = action["data"].get("file")
                summary_counts[file_ref] = summary_counts.get(file_ref, 0) + 1

            required_file_ref_set = set(required_file_refs)
            if any(file_ref not in required_file_ref_set for file_ref in summary_counts):
                raise exceptions.AIException(
                    "Organize summarize_file actions must target report input files."
                )

            missing_summary_refs = []
            duplicate_summary_refs = []
            for file_ref, submitted_file_ref in zip(
                required_file_refs,
                submitted_required_file_refs,
                strict=True,
            ):
                count = summary_counts.get(file_ref, 0)
                if count == 0:
                    missing_summary_refs.append(submitted_file_ref)
                elif count > 1:
                    duplicate_summary_refs.append(submitted_file_ref)
            if missing_summary_refs:
                raise exceptions.AIException(
                    "Organize proposal must summarize every report input file. "
                    "Missing report_file_ref values: "
                    f"{', '.join(str(file_ref) for file_ref in missing_summary_refs)}"
                )
            if duplicate_summary_refs:
                raise exceptions.AIException(
                    "Organize proposal must include exactly one summary per report "
                    "input file. Duplicate report_file_ref values: "
                    f"{', '.join(str(file_ref) for file_ref in duplicate_summary_refs)}"
                )

    return proposal


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason reference-kind validation is exercised through proposal repair tests
def _validate_existing_reference_kinds(action, action_label, resolved_details):
    """Reject hash references whose resolved entity kind violates the action."""
    rules = {
        "create_page": (("category", {"category"}),),
        "create_task": (
            ("page", {"page"}),
            ("task", {"task"}),
            ("project", {"project"}),
            ("model", {"model"}),
            ("form", {"form"}),
        ),
        "add_form_to_page": (
            ("page", {"page"}),
            ("category", {"category"}),
            ("form", {"form"}),
        ),
        "add_category": (
            ("page", {"page"}),
            ("category", {"category"}),
        ),
        "move_page": (
            ("page", {"page"}),
            ("category", {"category"}),
        ),
        "move_task": (
            ("task", {"task", "task_history"}),
            ("page", {"page"}),
            ("project", {"project"}),
            ("model", {"model"}),
        ),
        "attach_file_to_page": (("page", {"page"}),),
        "attach_file_to_task": (("task", {"task", "task_history"}),),
        "summarize_file": (("file", {"file"}),),
        "update_submission_fields": (
            ("page", {"page"}),
            ("task", {"task"}),
        ),
        "delete_page": (("page", {"page"}),),
    }
    data = action.get("data") if isinstance(action, dict) else None
    if not isinstance(data, dict):
        return

    for field, expected_kinds in rules.get(action.get("type"), ()):
        reference = _direct_entity_data_reference(data, field)
        match = re.fullmatch(r"hash:([0-9a-z]{12})", reference or "")
        if not match:
            continue
        details = resolved_details.get(match.group(1)) or {}
        actual_kind = details.get("kind")
        if not actual_kind or actual_kind in expected_kinds:
            continue
        if actual_kind == "user" and "page" in expected_kinds:
            # User-owned Pages use the virtual search kind ``user`` while the
            # cached executable id remains the underlying Page key.
            continue
        expected = " or ".join(sorted(expected_kinds))
        name = details.get("name")
        target = f" {name!r}" if name else ""
        raise exceptions.AIException(
            f"Action {action_label} uses {actual_kind}{target} as its "
            f"{field} reference; expected {expected}."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason direct-reference extraction is exercised through reference-kind validation
def _direct_entity_data_reference(data, field):
    for key in (field, f"{field}_id", f"{field}_ref"):
        value = data.get(key)
        if isinstance(value, dict):
            if value.get("action"):
                return None
            value = value.get("id") or value.get("key") or value.get("hash")
        if isinstance(value, str) and value.startswith(("$", "action:")):
            return None
        if value:
            return value
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason dependency cleanup is exercised through proposal validation
def _clean_action_dependencies(proposal, action, seen_ids, action_label):
    if "depends_on" not in action:
        return

    valid = []
    invalid = []
    dependencies = action.get("depends_on") or []
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    elif not isinstance(dependencies, list):
        dependencies = [dependencies]

    for dependency in dependencies:
        if not isinstance(dependency, str):
            invalid.append(repr(dependency))
            continue
        dependency_id = _strip_action_reference(dependency)
        if dependency_id in seen_ids:
            valid.append(dependency)
        else:
            invalid.append(dependency)

    if valid:
        action["depends_on"] = valid
    else:
        action.pop("depends_on", None)

    if invalid:
        ai_debug(
            "report.validate.invalid_dependencies_removed",
            action=action_label,
            invalid_dependency_count=len(invalid),
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _validate_action_data_shape(
    action,
    action_label,
    allow_empty_submission_updates=False,
    require_pending_submission_target=False,
    allow_pending_submissions=True,
    require_file_summary_terms=False,
    user=None,
):
    action_type = action.get("type")
    data = action.get("data") or {}
    if not isinstance(data, dict):
        raise exceptions.AIException(f"Action {action_label} data must be an object.")

    if action_type == "create_form":
        _validate_create_form_action_data(data, action_label)
    if action_type == "update_form_schema":
        _validate_update_form_schema_action_data(data, action_label)
    if action_type == "create_page" and not _proposal_string(data.get("name")):
        raise exceptions.AIException(f"Action {action_label} requires data.name.")
    if action_type in {"create_page", "create_task"}:
        _validate_form_submission_action_data(
            data,
            action_label,
            allow_pending=allow_pending_submissions,
        )
    if action_type == "create_task":
        _validate_create_task_action_data(data, action_label, user=user)
    entity_pair = ENTITY_PAIR_ACTION_REFERENCES.get(action_type)
    if entity_pair:
        source_root, target_roots = entity_pair
        _validate_entity_pair_action_data(
            data,
            action_label,
            source_root,
            target_roots,
        )
    if action_type == "move_file":
        _validate_move_file_action_data(data, action_label)
    if action_type == "rename_entity":
        _validate_rename_entity_action_data(data, action_label)
    if action_type == "summarize_file":
        _validate_file_summary_action_data(
            data,
            action_label,
            require_retrieval_terms=require_file_summary_terms,
        )
    if action_type == "update_submission_fields":
        _validate_submission_update_action_data(
            data,
            action_label,
            allow_empty=allow_empty_submission_updates,
            require_pending_target=require_pending_submission_target,
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason summary shape errors are exercised through proposal validation tests
def _validate_file_summary_action_data(
    data,
    action_label,
    *,
    require_retrieval_terms=False,
):
    if not _proposal_string(data.get("file")):
        raise exceptions.AIException(f"Action {action_label} requires data.file.")
    if not _proposal_string(data.get("summary")):
        raise exceptions.AIException(f"Action {action_label} requires data.summary.")

    terms = data.get("retrieval_terms")
    if terms is None and not require_retrieval_terms:
        return
    if (
        not isinstance(terms, list)
        or len(terms) != 2
        or any(not _proposal_string(term) or len(term.strip()) > 80 for term in terms)
        or len({term.strip().casefold() for term in terms}) != 2
    ):
        raise exceptions.AIException(
            f"Action {action_label} requires exactly two distinct retrieval terms."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason rename shape errors are exercised through proposal validation tests
def _validate_rename_entity_action_data(data, action_label):
    if not _first_data_reference(data, "entity"):
        raise exceptions.AIException(f"Action {action_label} requires data.entity.")
    if not _proposal_string(data.get("name")):
        raise exceptions.AIException(f"Action {action_label} requires data.name.")


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _validate_create_form_action_data(data, action_label):
    if not _proposal_string(data.get("name")):
        raise exceptions.AIException(f"Action {action_label} requires data.name.")

    form_type = data.get("form_type") or data.get("form-type")
    if form_type not in {"page", "task"}:
        raise exceptions.AIException(f"Action {action_label} requires data.form_type.")

    schema = data.get("schema")
    if not isinstance(schema, list) or not schema:
        raise exceptions.AIException(
            f"Action {action_label} requires at least one data.schema field."
        )

    used_ids = set()
    for index, field in enumerate(schema, 1):
        _validate_schema_field_definition(
            field,
            action_label,
            f"data.schema[{index}]",
            used_ids,
        )
        field_type = field.get("type") if isinstance(field, dict) else None
        if field_type == "html":
            if form_type != "task":
                raise exceptions.AIException(
                    f"Action {action_label} static HTML fields require a task form."
                )
            if "html" in field:
                raise exceptions.AIException(
                    f"Action {action_label} static HTML fields must use content_markdown."
                )
            if not _proposal_string(field.get("content_markdown")):
                raise exceptions.AIException(
                    f"Action {action_label} static HTML fields require content_markdown."
                )


# @testable true
# @tests tests_unit/test_020e_ai_report_proposals.py::test_validate_proposal_rejects_unsafe_schema_update_operations
# @matrix form-schema : proposal schema-update validation
def _validate_update_form_schema_action_data(data, action_label):
    if not _first_data_reference(data, "form"):
        raise exceptions.AIException(f"Action {action_label} requires data.form.")

    operations = data.get("operations")
    if not isinstance(operations, list) or not operations:
        raise exceptions.AIException(
            f"Action {action_label} requires at least one data.operations row."
        )

    added_ids = set()
    for index, operation in enumerate(operations, 1):
        operation_label = f"data.operations[{index}]"
        if not isinstance(operation, dict):
            raise exceptions.AIException(
                f"Action {action_label} {operation_label} must be an object."
            )
        operation_type = operation.get("op") or operation.get("type")
        if operation_type == "add_field":
            _validate_schema_field_definition(
                operation.get("field"),
                action_label,
                f"{operation_label}.field",
                added_ids,
            )
            field = operation.get("field")
            if isinstance(field, dict) and field.get("type") == "html":
                raise exceptions.AIException(
                    f"Action {action_label} {operation_label} cannot add static HTML fields."
                )
            continue
        if operation_type == "add_select_option":
            if not _proposal_string(
                operation.get("schema_id") or operation.get("field_id")
            ):
                raise exceptions.AIException(
                    f"Action {action_label} {operation_label} requires schema_id."
                )
            option = operation.get("option")
            if not isinstance(option, dict):
                raise exceptions.AIException(
                    f"Action {action_label} {operation_label} requires option."
                )
            if not _proposal_string(option.get("value")) or not _proposal_string(
                option.get("label")
            ):
                raise exceptions.AIException(
                    f"Action {action_label} {operation_label} option requires "
                    "value and label."
                )
            continue
        raise exceptions.AIException(
            f"Action {action_label} {operation_label} has unsupported op."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason schema field shape is exercised through create/update proposal tests
def _validate_schema_field_definition(field, action_label, field_label, used_ids):
    if not isinstance(field, dict):
        raise exceptions.AIException(
            f"Action {action_label} {field_label} must be an object."
        )
    schema_id = field.get("id")
    if not _proposal_string(schema_id):
        raise exceptions.AIException(
            f"Action {action_label} {field_label} requires id."
        )
    schema_id = schema_id.strip()
    if schema_id in used_ids:
        raise exceptions.AIException(
            f"Action {action_label} {field_label} duplicates id {schema_id}."
        )
    used_ids.add(schema_id)
    if not _proposal_string(field.get("type")):
        raise exceptions.AIException(
            f"Action {action_label} {field_label} requires type."
        )
    if not _proposal_string(field.get("title")):
        raise exceptions.AIException(
            f"Action {action_label} {field_label} requires title."
        )
    if not SchemaFields.validate_type(field):
        raise exceptions.AIException(
            f"Action {action_label} {field_label} has an unsupported or incomplete type."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _validate_create_task_action_data(data, action_label, user=None):
    if not _first_data_reference(data, "page"):
        raise exceptions.AIException(
            f"Action {action_label} requires data.page or data.page_action."
        )

    if _proposal_file_refs(data):
        raise exceptions.AIException(
            f"Action {action_label} should attach task files with "
            "attach_file_to_task, not data.file or data.files."
        )

    task_references = [
        key for key in ("task", "task_id", "task_ref", "task_action") if data.get(key)
    ]
    if len(task_references) > 1:
        raise exceptions.AIException(
            f"Action {action_label} must use only one task target reference."
        )
    if task_references and not _is_completed_task_action_data(data):
        raise exceptions.AIException(
            f"Action {action_label} may target an existing task only for a "
            "completed occurrence."
        )
    raw_completed_on = data.get("completed_on") or data.get("completed-on")
    if not raw_completed_on and isinstance(data.get("completed"), str):
        raw_completed_on = data["completed"]
    if raw_completed_on:
        completed_on = dates.parse_imported_date_as_utc(raw_completed_on)
        if completed_on and completed_on > dates.user_today(user):
            raise exceptions.AIException(
                f"Action {action_label} completion date cannot be in the future."
            )
    if data.get("schedule") is not None:
        if _is_completed_task_action_data(data):
            raise exceptions.AIException(
                f"Action {action_label} cannot schedule a completed occurrence."
            )
        data["schedule"] = validate_task_schedule(data["schedule"])


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason explicit completed-task target validation is exercised through proposal tests
def _validate_completed_task_target_action(action, action_label, seen_actions):
    if action.get("type") != "create_task":
        return
    data = action.get("data") or {}
    reference = _data_action_reference(data, "task")
    if not reference:
        return

    target_action = seen_actions.get(reference)
    target_data = target_action.get("data") if isinstance(target_action, dict) else {}
    if (
        not isinstance(target_action, dict)
        or target_action.get("type") != "create_task"
        or not _is_completed_task_action_data(target_data or {})
        or _first_data_reference(target_data or {}, "task")
    ):
        raise exceptions.AIException(
            f"Action {action_label} task_action must reference an earlier "
            "untargeted completed create_task action."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::_validate_create_task_action_data
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::_validate_completed_task_target_action
# @reason completion marker normalization is exercised through proposal validation
def _is_completed_task_action_data(data):
    return bool(
        data.get("completed_on") or data.get("completed-on") or data.get("completed")
    )


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_rejects_saved_pending_submissions_before_execution
# @matrix form-schema submission : deterministic-run stale-proposal validation
def _validate_form_submission_action_data(data, action_label, allow_pending=True):
    if not _has_form_reference_or_label(data):
        return

    submission = data.get("submission")
    if not isinstance(submission, dict) or not submission:
        if isinstance(submission, dict) and _proposal_string(
            data.get("submission_empty_reason")
        ):
            return
        if allow_pending:
            return
        raise exceptions.AIException(
            f"Action {action_label} uses a form and requires non-empty data.submission."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _validate_move_file_action_data(data, action_label):
    file_reference = _first_data_reference(data, "file")
    if not file_reference:
        raise exceptions.AIException(f"Action {action_label} requires data.file.")

    source_page = _first_data_reference(
        data,
        "from_page",
        "source_page",
        "page_from",
    )
    source_task = _first_data_reference(
        data,
        "from_task",
        "source_task",
        "task_from",
    )
    if bool(source_page) == bool(source_task):
        raise exceptions.AIException(
            f"Action {action_label} requires exactly one source page or task."
        )

    target_page = _first_data_reference(
        data,
        "to_page",
        "target_page",
        "destination_page",
        "page",
    )
    target_task = _first_data_reference(
        data,
        "to_task",
        "target_task",
        "destination_task",
        "task",
    )
    if bool(target_page) == bool(target_task):
        raise exceptions.AIException(
            f"Action {action_label} requires exactly one target page or task."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _validate_entity_pair_action_data(
    data,
    action_label,
    source_root,
    target_roots,
):
    if not _first_data_reference(data, source_root):
        raise exceptions.AIException(
            f"Action {action_label} requires data.{source_root}."
        )
    if not _first_data_reference(data, *target_roots):
        target_label = target_roots[0]
        raise exceptions.AIException(
            f"Action {action_label} requires data.{target_label}."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @reason update-shape errors are exercised through proposal validation tests
def _validate_submission_update_action_data(
    data,
    action_label,
    allow_empty=False,
    require_pending_target=False,
):
    updates = data.get("updates")
    if not isinstance(updates, list) or not updates:
        if allow_empty and (updates is None or updates == []):
            if require_pending_target:
                page_reference = _first_data_reference(data, "page")
                task_reference = _first_data_reference(data, "task")
                if bool(page_reference) == bool(task_reference):
                    raise exceptions.AIException(
                        f"Action {action_label} requires exactly one top-level page or "
                        "task while submission values are pending."
                    )
            return
        raise exceptions.AIException(
            f"Action {action_label} requires at least one data.updates row."
        )

    top_level_page = _first_data_reference(data, "page")
    top_level_task = _first_data_reference(data, "task")
    if top_level_page and top_level_task:
        raise exceptions.AIException(
            f"Action {action_label} may use only one top-level page or task."
        )

    for index, update in enumerate(updates, 1):
        row_label = f"data.updates[{index}]"
        if not isinstance(update, dict):
            raise exceptions.AIException(
                f"Action {action_label} {row_label} must be an object."
            )
        page_reference = _first_data_reference(
            update,
            "page",
            "page_id",
            "page_ref",
            "page_action",
        )
        task_reference = _first_data_reference(
            update,
            "task",
            "task_id",
            "task_ref",
            "task_action",
        )
        if bool(page_reference) == bool(task_reference):
            raise exceptions.AIException(
                f"Action {action_label} {row_label} requires exactly one page or task."
            )
        if not _proposal_string(update.get("schema_id") or update.get("field_id")):
            raise exceptions.AIException(
                f"Action {action_label} {row_label} requires schema_id."
            )
        if "new_value" not in update:
            raise exceptions.AIException(
                f"Action {action_label} {row_label} requires new_value."
            )
