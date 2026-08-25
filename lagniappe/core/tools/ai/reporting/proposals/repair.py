"""Deterministic repair and provider retry orchestration for proposals."""

import copy
import json
import re

from lagniappe.core import exceptions

from ...core import ai_model
from ...debug import ai_debug
from ...observability import mark_outcome
from ...prompt import Prompt
from ..contracts.actions import ALLOWED_ACTIONS
from ..contracts.schema import report_proposal_response_schema
from .diagnostics import _proposal_debug_summary
from .references import (
    _data_action_references,
    _first_data_reference,
    _proposal_string,
    _strip_action_reference,
)
from .validation import (
    ENTITY_PAIR_ACTION_REFERENCES,
    _validate_action_data_shape,
    validate_proposal,
)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/repair.py::_complete_form_schema_fields
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_create_form_field_missing_id
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_completes_additive_schema_field
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_infers_create_form_type_from_usage
# @matrix ai-report : deterministic-repair form-type schema-field-id schema-update
# @matrix form-schema : deterministic-repair form-type schema-update
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_infers_unambiguous_add_form_reference
# @matrix ai-report : deterministic-repair page-form references
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals/repair.py::_review_unresolved_action_references
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_reviews_ambiguous_missing_add_form_reference
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_reviews_unresolved_references_after_failed_repair
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_downgrades_missing_category_without_sentry_capture
# @matrix ai-report : needs-review page-form per-action-fallback references
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_downgrades_malformed_action_after_failed_repair
# @matrix ai-report : malformed-data needs-review per-action-fallback
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_reviews_files_missing_after_repair
# @matrix ai-report : fallback file-placement
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_reviews_files_missing_after_repair
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_reviews_ambiguous_missing_add_form_reference
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_reviews_unresolved_references_after_failed_repair
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_downgrades_malformed_action_after_failed_repair
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_downgrades_missing_category_without_sentry_capture
# @matrix ai-report : fallback per-action-fallback
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_invalid_action_type_once
# @matrix ai-report : generate validate
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_invalid_action_type_once
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_reviews_files_missing_after_repair
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_plan_leaves_form_submission_for_completion
# @tests tests_unit/test_020b_ai_ask.py::test_generate_ask_report_repairs_unusable_answers
# @matrix ai-report : ask fallback file-placement repair submission validate
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
# @covered-by lagniappe/core/tools/ai/reporting/proposals/repair.py::validate_or_repair_proposal
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
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_invalid_action_type_once
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_missing_file_attachments
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_invalid_action_references_once
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_category_used_as_page_reference
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_invalid_action_data_shape
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_missing_add_category_target
# @tests tests_unit/test_020e_ai_report_proposals.py::test_generate_organize_report_repairs_empty_form_schema_without_capture
# @tests tests_unit/test_020b_ai_ask.py::test_generate_ask_report_repairs_unusable_answers
# @matrix ai-report : add-category capture empty-form file-placement references repair required-data
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
