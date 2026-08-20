"""Validation, repair, references, and selection for AI report proposals."""

import copy
import json
import re

from lagniappe.core import exceptions
from lagniappe.core.properties.schema import SchemaFields

from ..core import ai_model
from ..debug import ai_debug
from ..observability import mark_outcome
from ..prompt import Prompt
from ..references import normalize_hash_references
from .contracts import ALLOWED_ACTIONS, report_proposal_response_schema
from .schedules import validate_task_schedule

ENTITY_PAIR_ACTION_REFERENCES = {
    "add_form_to_page": ("page", ("form",)),
    "add_category": ("page", ("category", "model")),
    "move_page": ("page", ("category", "model")),
    "move_task": ("task", ("to_page", "page")),
}


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/organize_completion.py::complete_organize_submissions
# @reason file reference extraction is asserted through completion behavior tests
def _proposal_file_refs(data):
    refs = []
    for key in ("file", "file_id", "file_ref"):
        if data.get(key):
            refs.append(data[key])
    files = data.get("files") or data.get("file_ids") or data.get("file_refs") or []
    if isinstance(files, str):
        refs.append(files)
    elif isinstance(files, list):
        refs.extend(value for value in files if value)
    return refs


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_complete_form_schema_fields
# @reason safe schema-id completion is asserted through proposal repair behavior
def _schema_field_title(field):
    """Return or derive a readable title without inventing field meaning."""
    for key in ("title", "label", "name"):
        if _proposal_string(field.get(key)):
            return field[key].strip()

    placeholder = field.get("placeholder")
    if _proposal_string(placeholder):
        title = re.sub(
            r"^(?:enter|select|choose|provide|add)\s+(?:a\s+|an\s+|the\s+|your\s+)?",
            "",
            placeholder.strip(),
            flags=re.IGNORECASE,
        ).strip(" .:;-")
        return title or placeholder.strip()

    schema_id = field.get("id")
    if _proposal_string(schema_id):
        parts = [part for part in re.split(r"[^a-zA-Z0-9]+", schema_id) if part]
        field_type = str(field.get("type") or "").lower()
        if parts and parts[0].lower() in {field_type, "field", "row"}:
            parts = parts[1:]
        if parts:
            return " ".join(parts).title()
    return None


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_create_form_field_missing_id
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_completes_additive_schema_field
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_infers_create_form_type_from_usage
# @pair ai-report:deterministic-repair
# @pair ai-report:schema-field-id
# @pair ai-report:schema-update
# @pair ai-report:form-type
# @pair form-schema:deterministic-repair
# @pair form-schema:schema-update
# @pair form-schema:form-type
def _complete_form_schema_fields(proposal):
    """Complete safe mechanical parts of proposed create/add field definitions."""
    if not isinstance(proposal, dict):
        return proposal

    actions = proposal.get("actions")
    if not isinstance(actions, list):
        return proposal
    repaired = copy.deepcopy(proposal)
    changed = False
    create_form_ids = {
        action.get("id")
        for action in repaired["actions"]
        if isinstance(action, dict)
        and action.get("type") == "create_form"
        and _proposal_string(action.get("id"))
    }
    form_usage_types = {action_id: set() for action_id in create_form_ids}
    usage_type_by_action = {
        "create_category": "page",
        "create_page": "page",
        "create_model_task": "task",
        "create_task": "task",
    }
    for usage_action in repaired["actions"]:
        if not isinstance(usage_action, dict):
            continue
        usage_type = usage_type_by_action.get(usage_action.get("type"))
        usage_data = usage_action.get("data")
        if not usage_type or not isinstance(usage_data, dict):
            continue
        form_reference = _first_data_reference(usage_data, "form")
        if isinstance(form_reference, dict):
            form_reference = (
                form_reference.get("action")
                or form_reference.get("id")
                or form_reference.get("key")
            )
        if isinstance(form_reference, str):
            form_reference = _strip_action_reference(form_reference)
        if form_reference in form_usage_types:
            form_usage_types[form_reference].add(usage_type)

    for action in repaired["actions"]:
        if not isinstance(action, dict):
            continue
        data = action.get("data")
        if not isinstance(data, dict):
            continue

        if action.get("type") == "create_form" and not (
            data.get("form_type") or data.get("form-type")
        ):
            usage_types = form_usage_types.get(action.get("id"), set())
            if len(usage_types) == 1:
                data["form_type"] = next(iter(usage_types))
                changed = True

        fields = []
        if action.get("type") == "create_form" and isinstance(data.get("schema"), list):
            fields = data["schema"]
        elif action.get("type") == "update_form_schema" and isinstance(
            data.get("operations"), list
        ):
            fields = [
                operation.get("field")
                for operation in data["operations"]
                if isinstance(operation, dict)
                and (operation.get("op") or operation.get("type")) == "add_field"
            ]
        if not fields:
            continue

        used = set()
        for index, field in enumerate(fields, 1):
            if not isinstance(field, dict):
                continue

            title = _schema_field_title(field)
            if not _proposal_string(field.get("title")) and _proposal_string(title):
                field["title"] = title
                changed = True

            field_type = field.get("type")
            if field_type == "input" and not _proposal_string(field.get("input")):
                field["input"] = "text"
                changed = True

            schema_id = field.get("id")
            if _proposal_string(schema_id):
                used.add(schema_id.strip())
                continue
            if not _proposal_string(field_type) or not _proposal_string(title):
                continue

            prefix = re.sub(r"[^a-z0-9]+", "-", field_type.lower()).strip("-")
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            base = f"{prefix or 'field'}-{slug or index}"
            candidate = base
            suffix = 2
            while candidate in used:
                candidate = f"{base}-{suffix}"
                suffix += 1
            field["id"] = candidate
            used.add(candidate)
            changed = True
    return repaired if changed else proposal


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_infers_unambiguous_add_form_reference
# @pair ai-report:deterministic-repair
# @pair ai-report:page-form
# @pair ai-report:references
def _complete_unambiguous_add_form_references(proposal):
    """Link a form-less page-form action when one earlier page form can fit."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("actions"), list):
        return proposal

    repaired = copy.deepcopy(proposal)
    page_form_actions = []
    changed = False
    for action in repaired["actions"]:
        if not isinstance(action, dict):
            continue
        data = action.get("data")
        if not isinstance(data, dict):
            continue

        if action.get("type") == "create_form":
            form_type = data.get("form_type") or data.get("form-type")
            action_id = action.get("id")
            form_name = data.get("name")
            if (
                form_type == "page"
                and _proposal_string(action_id)
                and _proposal_string(form_name)
            ):
                page_form_actions.append((action_id, form_name.strip()))
            continue

        if action.get("type") != "add_form_to_page" or _first_data_reference(
            data, "form"
        ):
            continue

        declared_name = next(
            (
                data[key].strip()
                for key in ("form_name", "form_display", "form_label")
                if _proposal_string(data.get(key))
            ),
            None,
        )
        candidates = page_form_actions
        if declared_name:
            candidates = [
                candidate
                for candidate in candidates
                if candidate[1].casefold() == declared_name.casefold()
            ]
        if len(candidates) == 1:
            data["form_action"] = candidates[0][0]
            changed = True

    return repaired if changed else proposal


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_review_unresolved_action_references
# @reason missing entity-pair references are asserted through per-action fallback behavior
def _missing_entity_pair_action_reference(action):
    pair = ENTITY_PAIR_ACTION_REFERENCES.get(action.get("type"))
    if not pair:
        return None

    source_root, target_roots = pair
    data = action.get("data")
    if not isinstance(data, dict) or not _first_data_reference(data, source_root):
        return source_root
    if not _first_data_reference(data, *target_roots):
        return target_roots[0]
    return None


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_reviews_ambiguous_missing_add_form_reference
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_reviews_unresolved_references_after_failed_repair
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_downgrades_missing_category_without_sentry_capture
# @pair ai-report:needs-review
# @pair ai-report:references
# @pair ai-report:page-form
# @pair ai-report:per-action-fallback
def _review_unresolved_action_references(
    proposal,
    allowed_actions,
    report_label="Organize",
):
    """Replace actions with unresolved or missing references by review items."""
    allowed = ALLOWED_ACTIONS if allowed_actions is None else allowed_actions
    if "needs_review" not in set(allowed):
        return proposal
    if not isinstance(proposal, dict) or not isinstance(proposal.get("actions"), list):
        return proposal

    reviewed = copy.deepcopy(proposal)
    issues = reviewed.get("issues")
    if not isinstance(issues, list) or any(
        not isinstance(issue, str) for issue in issues
    ):
        issues = []
        reviewed["issues"] = issues

    reviewed_any = False
    valid_ids = set()
    for index, action in enumerate(reviewed["actions"]):
        if not isinstance(action, dict):
            continue
        references = list(_data_action_references(action.get("data") or {}))
        invalid = [reference for reference in references if reference not in valid_ids]
        missing = _missing_entity_pair_action_reference(action)
        if invalid or missing:
            reviewed_any = True
            data = action.get("data")
            if not isinstance(data, dict):
                data = {}
            label = (
                data.get("name")
                or action.get("display_label")
                or action.get("id")
                or f"action {index + 1}"
            )
            question = (
                f"Which existing or proposed {missing} should this action use?"
                if missing
                else (
                    "Which existing or proposed workspace record should this "
                    "action use?"
                )
            )
            review_note = (
                f"Review where {label} belongs before applying this suggested change."
                if report_label == "Ask"
                else (
                    f"Review where {label} belongs before applying this part of "
                    "the organization plan."
                )
            )
            reviewed["actions"][index] = {
                "id": action.get("id") or f"review_action_{index + 1}",
                "type": "needs_review",
                "display_label": str(label),
                "reason": (
                    "This action could not be linked safely to an existing or "
                    "earlier proposed workspace record."
                ),
                "data": {
                    "note": review_note,
                    "questions": [question],
                },
            }
            issue = f"{label} needs review because its workspace reference was unclear."
            if issue not in issues:
                issues.append(issue)
            continue

        action_id = action.get("id")
        if (
            action.get("type") != "needs_review"
            and isinstance(action_id, str)
            and action_id
        ):
            valid_ids.add(action_id)

    if reviewed_any and report_label == "Ask":
        reviewed["summary"] = (
            "Some suggested workspace changes need review before they can be applied."
        )
        answer_html = reviewed.get("answer_html")
        if isinstance(answer_html, str) and answer_html.strip():
            notice = (
                "<p><strong>Action review required:</strong> The workspace "
                "changes described below are suggestions only. They have not "
                "been applied, and the unresolved records must be identified "
                "first.</p>"
            )
            if notice not in answer_html:
                reviewed["answer_html"] = f"{notice}{answer_html}"
    return reviewed


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_downgrades_malformed_action_after_failed_repair
# @pair ai-report:needs-review
# @pair ai-report:per-action-fallback
# @pair ai-report:malformed-data
def _review_invalid_action_shapes(
    proposal,
    allowed_actions,
    report_label="Organize",
    allow_pending_submissions=True,
):
    """Replace only structurally invalid actions with review items."""
    allowed = ALLOWED_ACTIONS if allowed_actions is None else set(allowed_actions)
    if "needs_review" not in set(allowed):
        return proposal
    if not isinstance(proposal, dict) or not isinstance(proposal.get("actions"), list):
        return proposal

    reviewed = copy.deepcopy(proposal)
    issues = reviewed.get("issues")
    if not isinstance(issues, list) or any(
        not isinstance(issue, str) for issue in issues
    ):
        issues = []
        reviewed["issues"] = issues

    reviewed_any = False
    seen_ids = set()
    for index, action in enumerate(reviewed["actions"]):
        error = None
        if not isinstance(action, dict):
            error = "Action must be an object."
            action = {}
        action_type = action.get("type")
        action_id = action.get("id")
        if error is None and action_type == "needs_review":
            if isinstance(action_id, str) and action_id:
                seen_ids.add(action_id)
            continue
        if error is None and action_type not in ALLOWED_ACTIONS:
            error = f"Unknown action type: {action_type}"
        elif error is None and action_type not in allowed:
            error = f"Action type is not allowed: {action_type}"
        elif error is None and action_id and not isinstance(action_id, str):
            error = "Action id must be a string."
        elif error is None and action_id and action_id in seen_ids:
            error = "Action id must be unique."
        elif error is None:
            try:
                _validate_action_data_shape(
                    action,
                    f"{action_id or index + 1} ({action_type})",
                    allow_pending_submissions=allow_pending_submissions,
                )
            except exceptions.AIException as validation_error:
                error = str(validation_error)

        if error is None:
            if isinstance(action_id, str) and action_id:
                seen_ids.add(action_id)
            continue

        reviewed_any = True
        data = action.get("data")
        if not isinstance(data, dict):
            data = {}
        label = (
            data.get("name")
            or action.get("display_label")
            or action_id
            or f"action {index + 1}"
        )
        review_id = (
            action_id
            if isinstance(action_id, str) and action_id not in seen_ids
            else f"review_action_{index + 1}"
        )
        reviewed["actions"][index] = {
            "id": review_id,
            "type": "needs_review",
            "display_label": str(label),
            "reason": "This action did not contain complete executable data.",
            "data": {
                "note": (
                    f"Review the exact data for {label} before applying this "
                    "suggested change."
                    if report_label == "Ask"
                    else (
                        f"Review the exact data for {label} before applying this "
                        "part of the organization plan."
                    )
                ),
                "questions": [
                    "What exact workspace record and values should this action use?"
                ],
            },
        }
        issue = f"{label} needs review because its action data was incomplete."
        if issue not in issues:
            issues.append(issue)

    if reviewed_any and report_label == "Ask":
        reviewed["summary"] = (
            "Some suggested workspace changes need review before they can be applied."
        )
        answer_html = reviewed.get("answer_html")
        if isinstance(answer_html, str) and answer_html.strip():
            notice = (
                "<p><strong>Action review required:</strong> The workspace "
                "changes described below are suggestions only. They have not "
                "been applied, and the unresolved records must be identified "
                "first.</p>"
            )
            if notice not in answer_html:
                reviewed["answer_html"] = f"{notice}{answer_html}"
    return reviewed


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_reviews_files_missing_after_repair
# @pair ai-report:fallback
# @pair ai-report:file-placement
def _report_needs_review_proposal(
    proposal,
    error=None,
    report_label="Organize",
):
    """Return a valid, non-executable proposal when repair cannot be made safe."""
    source = proposal if isinstance(proposal, dict) else {}
    issues = source.get("issues")
    issues = (
        [issue for issue in issues if isinstance(issue, str)]
        if isinstance(issues, list)
        else []
    )
    validation_error = str(error or "")
    is_ask = report_label == "Ask"
    is_form_error = not is_ask and any(
        marker in validation_error
        for marker in ("create_form", "update_form_schema", "data.schema")
    )
    if is_ask:
        display_label = "Suggested changes"
        note = "The suggested workspace changes could not be validated automatically."
        review_note = "Review or revise the suggested changes before applying them."
    elif is_form_error:
        display_label = "Form definition"
        note = "The proposed form fields could not be validated automatically."
        review_note = (
            "Review the proposed form definition or revise this report before "
            "making workspace changes."
        )
    else:
        display_label = "Organization plan"
        note = "The proposed organization plan could not be made safe automatically."
        review_note = (
            "Review the uploaded files and revise this report before making "
            "workspace changes."
        )
    if note not in issues:
        issues.append(note)
    summary = source.get("summary")
    if not isinstance(summary, str) or not summary.strip() or not is_ask:
        summary = "The proposed changes need review before they can be applied."
    confidence = source.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
        or not is_ask
    ):
        confidence = 0
    fallback = {
        "summary": summary,
        "confidence": confidence,
        "issues": issues,
        "actions": [
            {
                "id": "review_organization_plan",
                "type": "needs_review",
                "display_label": display_label,
                "reason": note,
                "data": {
                    "note": review_note,
                    "questions": [],
                },
            }
        ],
    }
    if is_ask and isinstance(source.get("answer_html"), str):
        fallback["answer_html"] = source["answer_html"]
    return fallback


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_reviews_files_missing_after_repair
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_reviews_ambiguous_missing_add_form_reference
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_reviews_unresolved_references_after_failed_repair
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_downgrades_malformed_action_after_failed_repair
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_downgrades_missing_category_without_sentry_capture
# @pair ai-report:fallback
# @pair ai-report:per-action-fallback
def _report_validation_fallback(
    proposal,
    validator,
    validation_options,
    validation_error=None,
    report_label="Organize",
):
    allowed_actions = validation_options.get("allowed_actions")
    allowed = ALLOWED_ACTIONS if allowed_actions is None else allowed_actions
    if "needs_review" not in set(allowed):
        return None

    reviewed = _review_unresolved_action_references(
        proposal,
        allowed_actions,
        report_label=report_label,
    )
    reviewed = _review_invalid_action_shapes(
        reviewed,
        allowed_actions,
        report_label=report_label,
        allow_pending_submissions=validation_options.get(
            "allow_pending_submissions",
            True,
        ),
    )
    reviewed = _review_unresolved_action_references(
        reviewed,
        allowed_actions,
        report_label=report_label,
    )
    try:
        return validator(reviewed, **validation_options)
    except exceptions.AIException as fallback_error:
        fallback = _report_needs_review_proposal(
            reviewed,
            error=fallback_error or validation_error,
            report_label=report_label,
        )
        fallback_options = dict(validation_options)
        fallback_options.pop("required_file_refs", None)
        return validator(fallback, **fallback_options)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_rejects_unknown_actions_and_bad_dependencies
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_rejects_unsafe_schema_update_operations
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_requires_completed_root_task_targets
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_accepts_add_form_to_page_without_category
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_requires_move_entity_references*
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_accepts_rename_and_move_task_target_aliases
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_requires_every_report_file_attachment
# @tests tests_unit/test_020_ai_reports.py::test_validate_proposal_treats_action_like_submission_fields_as_content
# @features ai-report
# @dimensions proposal validation dependencies schema-update page-form no-category move-references rename canonical-target legacy-target file-placement explicit-task-identity submission action-reference-namespace
def validate_proposal(
    proposal,
    allowed_actions=None,
    allow_empty_submission_updates=False,
    require_pending_submission_target=False,
    allow_pending_submissions=False,
    required_file_refs=None,
    validate_reference_kinds=False,
):
    """Validate the JSON action proposal returned by the organize prompt."""
    allowed = ALLOWED_ACTIONS if allowed_actions is None else frozenset(allowed_actions)
    raw_proposal = proposal
    resolved_reference_details = {}
    normalized = normalize_hash_references(
        {
            "proposal": proposal,
            "required_file_refs": list(required_file_refs or ()),
        },
        resolved_details=resolved_reference_details,
    )
    proposal = normalized["proposal"]
    required_file_refs = normalized["required_file_refs"]
    if not isinstance(proposal, dict):
        raise exceptions.AIException("Organize proposal must be a JSON object.")

    issues = proposal.get("issues")
    if issues is None:
        proposal["issues"] = []
    elif not isinstance(issues, list) or any(
        not isinstance(issue, str) for issue in issues
    ):
        raise exceptions.AIException(
            "Organize proposal issues must be a list of strings."
        )

    actions = proposal.get("actions")
    if not isinstance(actions, list):
        raise exceptions.AIException("Organize proposal must include actions.")

    seen_ids = set()
    seen_actions = {}
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise exceptions.AIException("Each organize action must be an object.")

        action_type = action.get("type")
        if action_type not in ALLOWED_ACTIONS:
            raise exceptions.AIException(f"Unknown organize action: {action_type}")
        if action_type not in allowed:
            raise exceptions.AIException(
                f"Organize action not allowed for this user: {action_type}"
            )

        action_id = action.get("id")
        if action_id:
            if not isinstance(action_id, str):
                raise exceptions.AIException("Organize action ids must be strings.")
            if action_id in seen_ids:
                raise exceptions.AIException(
                    f"Duplicate organize action id: {action_id}"
                )

        action_label = f"{action_id or index + 1} ({action_type})"
        _validate_action_data_shape(
            action,
            action_label,
            allow_empty_submission_updates=allow_empty_submission_updates,
            require_pending_submission_target=require_pending_submission_target,
            allow_pending_submissions=allow_pending_submissions,
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
            file_ref
            for file_ref in required_file_refs
            if file_ref not in attached_file_refs
        ]
        if missing_file_refs:
            raise exceptions.AIException(
                "Organize proposal must attach every report input file to a page "
                "or task. Missing report_file_ref values: "
                f"{', '.join(str(file_ref) for file_ref in missing_file_refs)}"
            )

    return proposal


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_invalid_action_type_once
# @pair ai-report:generate
# @pair ai-report:validate
def generate_validated_proposal(
    prompt,
    report_label="Organize",
    validator=None,
):
    """Generate a proposal and allow one repair pass for validation failures."""
    return ai_model.generate_content(
        prompt,
        validator=lambda proposal: validate_or_repair_proposal(
            prompt,
            proposal,
            report_label=report_label,
            validator=validator,
        ),
    )


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_invalid_action_type_once
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_reviews_files_missing_after_repair
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_plan_leaves_form_submission_for_completion
# @tests tests_unit/test_020b_ai_ask.py::test_generate_ask_report_repairs_unusable_answers
# @pair ai-report:ask
# @pair ai-report:validate
# @pair ai-report:repair
# @pair ai-report:fallback
# @pair ai-report:file-placement
# @pair ai-report:submission
def validate_or_repair_proposal(
    prompt,
    proposal,
    report_label="Organize",
    allow_empty_submission_updates=False,
    require_pending_submission_target=False,
    allow_pending_submissions=True,
    validator=None,
):
    """Validate, repair once with the model, then fall back to human review."""
    validator = validator or validate_proposal
    validation_options = {
        "allowed_actions": getattr(prompt, "allowed_actions", None),
        "allow_pending_submissions": allow_pending_submissions,
    }
    if validator is validate_proposal:
        validation_options["allow_empty_submission_updates"] = (
            allow_empty_submission_updates
        )
        validation_options["require_pending_submission_target"] = (
            require_pending_submission_target
        )
    if report_label == "Organize":
        validation_options["required_file_refs"] = _organize_prompt_report_file_refs(
            prompt
        )
        if validator is validate_proposal:
            validation_options["validate_reference_kinds"] = True
    original_proposal = copy.deepcopy(proposal)
    proposal = _complete_form_schema_fields(proposal)
    proposal = _complete_unambiguous_add_form_references(proposal)
    if proposal != original_proposal:
        mark_outcome("local_repair")
    try:
        return validator(proposal, **validation_options)
    except exceptions.AIException as error:
        ai_debug(
            "report.generate.validation_failed",
            report_label=report_label,
            error=str(error),
            **_proposal_debug_summary(proposal),
        )
        repair_prompt = _proposal_repair_prompt(prompt, proposal, error, report_label)
        mark_outcome("model_repair")
        try:
            repaired = ai_model.generate_content(repair_prompt)
        except exceptions.AIQuotaError:
            raise
        except exceptions.AIException as repair_error:
            if report_label not in {"Organize", "Ask"}:
                raise
            fallback = _report_validation_fallback(
                proposal,
                validator,
                validation_options,
                validation_error=error,
                report_label=report_label,
            )
            if fallback is not None:
                mark_outcome("review_fallback")
                return fallback
            exceptions.capture(
                repair_error,
                context={
                    "operation": "report_proposal_repair_generation_failed",
                    "report_label": report_label,
                    "validation_error": str(error),
                },
                level="warning",
            )
            raise
        repaired = _complete_form_schema_fields(repaired)
        repaired = _complete_unambiguous_add_form_references(repaired)
        ai_debug(
            "report.generate.repair_raw_proposal",
            report_label=report_label,
            **_proposal_debug_summary(repaired),
        )
        try:
            return validator(repaired, **validation_options)
        except exceptions.AIException as repair_error:
            if report_label not in {"Organize", "Ask"}:
                raise
            ai_debug(
                "report.generate.repair_validation_failed",
                report_label=report_label,
                first_validation_error=str(error),
                repair_validation_error=str(repair_error),
                **_proposal_debug_summary(repaired),
            )
            fallback = _report_validation_fallback(
                repaired,
                validator,
                validation_options,
                validation_error=repair_error,
                report_label=report_label,
            )
            if fallback is not None:
                mark_outcome("review_fallback")
                return fallback
            exceptions.capture(
                repair_error,
                context={
                    "operation": (
                        f"{report_label.lower()}_proposal_repair_validation_failed"
                    ),
                    "report_label": report_label,
                    "prompt_type": getattr(prompt, "prompt_type", None),
                    "first_validation_error": str(error),
                    "repair_validation_error": str(repair_error),
                    "repaired_proposal": _proposal_debug_summary(repaired),
                },
                level="warning",
            )
            raise


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_or_repair_proposal
# @reason prompt manifest extraction is covered by file-placement repair behavior
def _organize_prompt_report_file_refs(prompt):
    """Return exact report file refs from the Organize prompt manifest."""
    for block in getattr(prompt, "context_blocks", []) or []:
        if block.get("label") != "Report Input Files":
            continue
        value = str(block.get("value") or "").strip()
        if value.startswith("```") and value.endswith("```"):
            value = value.split("\n", 1)[1].rsplit("\n", 1)[0]
        try:
            files = json.loads(value)
        except (TypeError, ValueError):
            return ()
        if not isinstance(files, list):
            return ()
        return tuple(
            file_ref
            for item in files
            if isinstance(item, dict)
            for file_ref in (item.get("report_file_ref") or item.get("hash"),)
            if file_ref
        )
    return ()


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_invalid_action_type_once
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_missing_file_attachments
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_invalid_action_references_once
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_category_used_as_page_reference
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_invalid_action_data_shape
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_missing_add_category_target
# @tests tests_unit/test_020_ai_reports.py::test_generate_organize_report_repairs_empty_form_schema_without_capture
# @tests tests_unit/test_020b_ai_ask.py::test_generate_ask_report_repairs_unusable_answers
# @pair ai-report:repair
# @pair ai-report:file-placement
# @pair ai-report:references
# @pair ai-report:required-data
# @pair ai-report:add-category
# @pair ai-report:empty-form
# @pair ai-report:capture
def _proposal_repair_prompt(source_prompt, proposal, error, report_label):
    allowed_actions = tuple(getattr(source_prompt, "allowed_actions", None) or ())
    output_description = None
    output_format = getattr(source_prompt, "output_format", None)
    if isinstance(output_format, dict):
        output_description = output_format.get("description")

    repair_type = (
        f"{report_label.lower()} report repair"
        if report_label in {"Organize", "Ask", "Create"}
        else None
    )
    prompt = Prompt(
        f"You repair invalid Lagniappe {report_label} report JSON.",
        user=getattr(source_prompt, "user", None),
        type=repair_type,
    )
    if report_label == "Organize":
        prompt.set_instructions_before_context()
    if getattr(source_prompt, "service_tier", None):
        prompt.set_service_tier(source_prompt.service_tier)
    source_tools = getattr(source_prompt, "_tools", None)
    if source_tools and getattr(source_prompt, "user", None):
        if source_tools is True:
            prompt.enable_tools()
        else:
            prompt.enable_tools(*source_tools)
        prompt.set_max_tool_iterations(
            getattr(source_prompt, "max_tool_iterations", None)
        )
        prompt.set_max_tool_file_parts_per_turn(
            getattr(source_prompt, "max_tool_file_parts_per_turn", None)
        )
    prompt.set_allowed_actions(allowed_actions)
    prompt.set_response_schema(
        getattr(source_prompt, "response_schema", None)
        if report_label == "Ask"
        else report_proposal_response_schema(
            allowed_actions,
            require_issues=report_label == "Organize",
            include_submission_fields=report_label != "Organize",
        )
    )
    prompt.add_output_contract("JSON", output_description)
    repair_context_labels = {
        "User Question",
        "User Instructions",
        "Report Input Files",
        "Report Action Permissions",
        "User Feedback",
        "Current Proposal Json",
        "Current Response Json",
    }
    for block in getattr(source_prompt, "context_blocks", []):
        if block.get("label") in repair_context_labels:
            prompt.context_blocks.append(copy.deepcopy(block))
    prompt.add_context("validation_error", str(error))
    prompt.add_context("allowed_actions", list(allowed_actions))
    prompt.add_context("invalid_proposal_json", proposal)
    prompt.add_instructions(
        f"""
Return a complete replacement {report_label} proposal JSON object.
Preserve the intent, issues, and valid actions wherever possible. Preserve the
summary only when it still matches the replacement proposal and does not claim
that unexecuted changes already happened.

Keep internal entity hash tokens in tool calls and executable action data only.
Use human names in summary, answer_html, display labels, reasons, issues, notes,
and questions; if a human name is unavailable, describe the entity generically
rather than displaying its hash token. Describe unexecuted actions as proposed
changes that would or could happen, never as guaranteed future changes.
Do not mention validation errors, repair instructions, or the repair process in
the summary or other user-facing text. Describe only the resulting proposal.

Before returning, inspect every action `type`. Each action `type` must exactly
match one string in Allowed Actions. Do not invent aliases, shorten action
names, or use guessed names. If an invalid action cannot be mapped safely, use
needs_review when it is allowed.

Also inspect action references. Values in keys ending with "_action",
{{"action": "..."}}, "$action_id", "action:action_id", and depends_on must point
to ids of actions earlier in the same actions list. If one contains prose, a
display label, or a missing/later action id, fix it by reordering the actions,
using a valid earlier action id, using an existing entity hash in the normal
entity field, or replacing the affected action with needs_review. Do not put
explanatory text in *_action fields or depends_on.

Also inspect required action data. Every create_page action must include a
non-empty human page name at exactly data.name. The action display_label and
reason fields are human-only labels; they do not execute and must not be the
only place where a page name appears. If no human page name can be put in
data.name, replace that action with needs_review instead of returning an invalid
create_page.
create_form actions must include data.name, data.form_type set to "page" or
"task", and data.schema with at least one field object. Do not create a form
with an empty schema. If there are no useful structured fields, omit the
create_form action or replace it with needs_review instead of creating a blank
form. Every field object in data.schema must include id, type, and title. The
id must be a stable schema field id string such as input-provider-name,
textarea-notes, select-status, date-visit-date, link-provider, or
table-payments; do not return schema fields without ids.
When get_guidelines is available, call get_guidelines("page_form") or
get_guidelines("task_form") before repairing a create_form action, matching its
data.form_type. Call get_guidelines("schema_evolution") before repairing an
update_form_schema action. An add_field operation has the same id, type, and
title requirements as a create_form schema field, and input fields must also
include an input subtype. Do not merely claim a schema was corrected in the
summary; put every correction in the returned action data.
Do not replace a form action with needs_review merely because an id, title, or
input subtype was omitted. Those are mechanical schema requirements: derive
them from the field's stated meaning and the guidelines. Use needs_review only
when the intended field meaning or a safe schema change cannot be determined.
For Organize repairs, create_page and create_task actions may select a form but
must not generate data.submission. A separate completion stage fills resolved
forms after the structural proposal validates.
For completed create_task actions, use data.name for the stable work name rather
than a dated occurrence title. The runner reuses one unambiguous editable task
with the same page, model task, and stable name. Use data.task only to force an
exact existing task hash returned by get_page_tasks, and data.task_action only
to force an earlier report task. Omit both for ordinary repeated work; use a
distinct stable name when the work is distinct.
For Organize repairs, compare the complete Report Input Files list with the
replacement actions. Every exact report_file_ref must appear in a valid
attach_file_to_page or attach_file_to_task action whose page/task target is an
existing entity or an earlier proposal action. Creating a page or task,
summarizing a file, or mentioning a filename does not place the file. Add any
missing attachment actions and preserve all valid existing placements.
add_form_to_page actions must include both an existing or earlier-created page
reference in data.page/data.page_action and an existing or earlier-created page
form reference in data.form/data.form_action. If exactly one earlier page
create_form action is compatible, use its id in data.form_action. If the page
form cannot be identified safely, replace the add_form_to_page action with
needs_review.
add_category actions must include both an existing or earlier-created page
reference in data.page/data.page_action and an existing or earlier-created
category reference through data.category, data.category_action, data.model, or
data.model_action. A readable category_name/model_name is not enough to execute.
If the category cannot be identified from the invalid proposal or available
context, replace the add_category action with needs_review.
move_page actions must include both the existing page in data.page and the
destination category in data.category or data.model. move_task actions must
include both the existing task in data.task and the destination page in
data.to_page. Readable page_name, task_name, or category_name values do not execute;
replace an action with needs_review when its exact entity references cannot be
identified safely.
move_file actions must include data.file, exactly one
source reference using from_page/from_task or their aliases, and exactly one
target reference using to_page/to_task or their aliases. For existing page files,
use get_page_file_list to get the file hash and source page; include display_name
or file_name only as a readable label, not as the executable file reference.
For Organize planning, update_submission_fields must identify exactly one
existing target in data.page or data.task and omit data.updates so the focused
submission completion stage can derive evidence-backed values. In other report
types, data.updates must contain at least one object with exactly one page or
task reference, a schema_id or field_id, and a new_value key.
rename_entity actions must include the existing entity in data.entity and a
non-empty replacement name in data.name. Renaming changes only the entity name;
do not put descriptions or other attribute edits in this action.

The invalid proposal was rejected with this validation error:
{json.dumps(str(error))}
        """,
        section_title="Proposal Validation Repair",
    )
    return prompt


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason recursive dependency extraction is exercised through the validator contract
def _referenced_action_ids(action):
    yield from _explicit_dependency_ids(action)
    data = action.get("data") or {}
    yield from _data_action_references(data)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason explicit dependency normalization is exercised through proposal validation
def _explicit_dependency_ids(action):
    dependencies = action.get("depends_on") or []
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    elif not isinstance(dependencies, list):
        dependencies = [dependencies]

    for dependency in dependencies:
        if isinstance(dependency, str):
            yield _strip_action_reference(dependency)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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
        expected = " or ".join(sorted(expected_kinds))
        name = details.get("name")
        target = f" {name!r}" if name else ""
        raise exceptions.AIException(
            f"Action {action_label} uses {actual_kind}{target} as its "
            f"{field} reference; expected {expected}."
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason reference-marker normalization is part of dependency validation
def _strip_action_reference(value):
    if value.startswith("$"):
        return value[1:]
    if value.startswith("action:"):
        return value.split(":", 1)[1]
    return value


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _validate_action_data_shape(
    action,
    action_label,
    allow_empty_submission_updates=False,
    require_pending_submission_target=False,
    allow_pending_submissions=True,
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
        _validate_create_task_action_data(data, action_label)
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
    if action_type == "update_submission_fields":
        _validate_submission_update_action_data(
            data,
            action_label,
            allow_empty=allow_empty_submission_updates,
            require_pending_target=require_pending_submission_target,
        )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason rename shape errors are exercised through proposal validation tests
def _validate_rename_entity_action_data(data, action_label):
    if not _first_data_reference(data, "entity"):
        raise exceptions.AIException(f"Action {action_label} requires data.entity.")
    if not _proposal_string(data.get("name")):
        raise exceptions.AIException(f"Action {action_label} requires data.name.")


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason schema action shape is exercised through public proposal validation tests
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _validate_create_task_action_data(data, action_label):
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
    if data.get("schedule") is not None:
        if _is_completed_task_action_data(data):
            raise exceptions.AIException(
                f"Action {action_label} cannot schedule a completed occurrence."
            )
        data["schedule"] = validate_task_schedule(data["schedule"])


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_validate_create_task_action_data
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_validate_completed_task_target_action
# @reason completion marker normalization is exercised through proposal validation
def _is_completed_task_action_data(data):
    return bool(
        data.get("completed_on") or data.get("completed-on") or data.get("completed")
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_validate_completed_task_target_action
# @reason action-reference aliases are exercised through proposal validation
def _data_action_reference(data, root):
    value = data.get(f"{root}_action")
    if isinstance(value, str) and value:
        return _strip_action_reference(value)

    value = data.get(root)
    if isinstance(value, dict) and isinstance(value.get("action"), str):
        return _strip_action_reference(value["action"])
    if isinstance(value, str) and value.startswith(("$", "action:")):
        return _strip_action_reference(value)
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason form/submission pairing errors are exercised through proposal validation tests
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
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


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _first_data_reference(data, *keys):
    for key in keys:
        for candidate in (key, f"{key}_id", f"{key}_ref", f"{key}_action"):
            value = data.get(candidate)
            if value:
                return value
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason readable form labels are validated like executable form references
def _has_form_reference_or_label(data):
    if _first_data_reference(data, "form"):
        return True
    return any(
        bool(data.get(key)) for key in ("form_name", "form_display", "form_label")
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason action-shape errors are exercised through proposal validation tests
def _proposal_string(value):
    return isinstance(value, str) and value.strip()


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::validate_proposal
# @reason recursive action-reference extraction is covered through proposal validation
def _data_action_references(value, key=None):
    # Form field ids are user-defined and may legitimately be ``action`` or end
    # in ``_action``. Submission values are content, never proposal references,
    # so keep that namespace opaque to the dependency walk.
    if key == "submission":
        return

    if isinstance(value, dict):
        action = value.get("action")
        if isinstance(action, str):
            yield _strip_action_reference(action)
        for child_key, child in value.items():
            yield from _data_action_references(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _data_action_references(child, key)
    elif isinstance(value, str):
        if value.startswith("$") or value.startswith("action:"):
            yield _strip_action_reference(value)
        elif key and key.endswith("_action"):
            yield _strip_action_reference(value)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_skip_proposal_actions_marks_dependencies
# @features ai-report
# @dimensions proposal skip dependencies
def skip_proposal_actions(proposal, index):
    """Mark one proposal action and all dependent actions as skipped."""
    proposal = validate_proposal(proposal)
    actions = proposal.get("actions") or []
    if index < 0 or index >= len(actions):
        raise exceptions.ValidationError("Action not found.")

    skipped_indexes = _dependent_action_indexes(actions, index)
    for action_index in skipped_indexes:
        actions[action_index]["skip"] = True

    return sorted(action_index + 1 for action_index in skipped_indexes)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_toggle_proposal_action_skip_restores_dependencies
# @features ai-report
# @dimensions proposal skip restore dependencies
def toggle_proposal_action_skip(proposal, index):
    """Toggle skipped state for an action and its dependent actions."""
    proposal = validate_proposal(proposal)
    actions = proposal.get("actions") or []
    if index < 0 or index >= len(actions):
        raise exceptions.ValidationError("Action not found.")

    changed_indexes = _dependent_action_indexes(actions, index)
    return _set_proposal_action_skip(actions, index, changed_indexes)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_toggle_proposal_action_skip_restores_dependencies
# @features ai-report
# @dimensions proposal skip grouped-display restore dependencies
def toggle_proposal_action_indexes(proposal, index, indexes, include_dependencies=True):
    """Toggle skipped state for a display group of proposal actions."""
    proposal = validate_proposal(proposal)
    actions = proposal.get("actions") or []
    if index < 0 or index >= len(actions):
        raise exceptions.ValidationError("Action not found.")

    changed_indexes = set()
    for action_index in indexes or []:
        if action_index < 0 or action_index >= len(actions):
            raise exceptions.ValidationError("Action not found.")
        if include_dependencies:
            changed_indexes.update(_dependent_action_indexes(actions, action_index))
        else:
            changed_indexes.add(action_index)

    if include_dependencies:
        changed_indexes.update(_dependent_action_indexes(actions, index))
    else:
        changed_indexes.add(index)
    return _set_proposal_action_skip(actions, index, changed_indexes)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::toggle_proposal_action_skip
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::toggle_proposal_action_indexes
# @reason shared skip state mutation is verified through public toggle helpers
def _set_proposal_action_skip(actions, index, changed_indexes):
    skip = actions[index].get("skip") is not True
    for action_index in changed_indexes:
        if skip:
            actions[action_index]["skip"] = True
        else:
            actions[action_index].pop("skip", None)

    return {
        "changed": sorted(action_index + 1 for action_index in changed_indexes),
        "skipped": [
            action_index + 1
            for action_index, action in enumerate(actions)
            if action.get("skip") is True
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::skip_proposal_actions
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::toggle_proposal_action_skip
# @reason dependency walk is verified through public proposal mutation helpers
def _dependent_action_indexes(actions, index):
    skipped_ids = set()
    skipped_indexes = {index}
    action = actions[index]
    if action.get("id"):
        skipped_ids.add(action["id"])

    changed = True
    while changed:
        changed = False
        for action_index, action in enumerate(actions):
            if action_index in skipped_indexes:
                continue
            dependencies = set(_referenced_action_ids(action))
            if dependencies.intersection(skipped_ids):
                skipped_indexes.add(action_index)
                if action.get("id"):
                    skipped_ids.add(action["id"])
                changed = True

    return skipped_indexes


# @testable false
# @covered-by lagniappe/core/tools/ai/organize.py::generate_organize_report
# @reason debug-only proposal summary is not behavior-bearing
def _proposal_debug_summary(proposal):
    if not isinstance(proposal, dict):
        return {"proposal_type": type(proposal).__name__}

    actions = proposal.get("actions") or []
    return {
        "summary_present": bool(proposal.get("summary")),
        "issue_count": len(proposal.get("issues") or []),
        "issues": proposal.get("issues") or [],
        "action_count": len(actions) if isinstance(actions, list) else None,
        "actions": [
            _proposal_action_debug_summary(action)
            for action in actions
            if isinstance(action, dict)
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_proposal_debug_summary
# @reason debug-only action summary is not behavior-bearing
def _proposal_action_debug_summary(action):
    data = action.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    submission = data.get("submission")
    schema = data.get("schema")
    operations = data.get("operations")
    return {
        "id": action.get("id"),
        "type": action.get("type"),
        "display_label": action.get("display_label"),
        "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "schema_field_count": len(schema) if isinstance(schema, list) else None,
        "schema_fields": (
            [_schema_field_debug_summary(field) for field in schema]
            if isinstance(schema, list)
            else None
        ),
        "schema_operations": (
            [_schema_operation_debug_summary(operation) for operation in operations]
            if isinstance(operations, list)
            else None
        ),
        "page": _debug_ref(data, "page"),
        "project": _debug_ref(data, "project"),
        "model": _debug_ref(data, "model"),
        "form": _debug_ref(data, "form"),
        "completed": data.get("completed") is True,
        "completed_on": data.get("completed_on") or data.get("completed-on"),
        "file_refs": _debug_file_refs(data),
        "submission_key_present": "submission" in data,
        "submission_field_count": (
            len(submission) if isinstance(submission, dict) else None
        ),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_proposal_action_debug_summary
# @reason compact schema diagnostics are exercised through failed-repair capture tests
def _schema_field_debug_summary(field):
    if not isinstance(field, dict):
        return {"field_type": type(field).__name__}
    return {
        "id": field.get("id"),
        "type": field.get("type"),
        "input": field.get("input"),
        "title_present": bool(_proposal_string(field.get("title"))),
        "label_present": bool(_proposal_string(field.get("label"))),
        "keys": sorted(field),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_proposal_action_debug_summary
# @reason compact schema diagnostics are exercised through failed-repair capture tests
def _schema_operation_debug_summary(operation):
    if not isinstance(operation, dict):
        return {"operation_type": type(operation).__name__}
    return {
        "op": operation.get("op") or operation.get("type"),
        "schema_id": operation.get("schema_id") or operation.get("field_id"),
        "field": _schema_field_debug_summary(operation.get("field")),
        "option_keys": (
            sorted(operation["option"])
            if isinstance(operation.get("option"), dict)
            else None
        ),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_proposal_action_debug_summary
# @reason debug-only reference summary is not behavior-bearing
def _debug_ref(data, name):
    return (
        data.get(name)
        or data.get(f"{name}_id")
        or data.get(f"{name}_ref")
        or data.get(f"{name}_action")
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals.py::_proposal_action_debug_summary
# @reason debug-only file reference summary is not behavior-bearing
def _debug_file_refs(data):
    refs = []
    for key in ("file", "file_id", "file_ref"):
        value = data.get(key)
        if value:
            refs.append(value)
    files = data.get("files") or data.get("file_ids") or data.get("file_refs") or []
    if isinstance(files, str):
        refs.append(files)
    elif isinstance(files, list):
        refs.extend(files)
    return refs
