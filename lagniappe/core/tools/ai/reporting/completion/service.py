"""Submission-completion orchestration for Organize reports."""

from lagniappe.core import exceptions

from ...core import ai_model
from ...debug import ai_debug
from .context import (
    _apply_completed_submission_update,
    _completion_file_contexts_for_action,
    _completion_form_info,
    _completion_prompt_context,
    _completion_results_debug_summary,
    _completion_target_context,
    _completion_target_debug_summary,
    _completion_target_type,
    _form_info_with_schema_updates,
    _inject_completion_form_reference,
    _submission_completion_context,
)
from .files import _report_file_summary_warning
from .prompt import (
    organize_submission_completion_prompt,
    validate_organize_submission_results,
)
from ..proposals.validation import validate_proposal
from ..proposals.references import _first_data_reference, _has_form_reference_or_label


# @testable true
# @tests tests_unit/test_020f_ai_report_completion.py::test_complete_organize_submissions_uses_one_focused_prompt
# @tests tests_unit/test_020f_ai_report_completion.py::test_complete_organize_submissions_preserves_empty_form_records
# @tests tests_unit/test_020f_ai_report_completion.py::test_complete_organize_submissions_updates_existing_task_submission
# @tests tests_unit/test_020d_ai_report_prompts.py::test_unreadable_pdf_is_saved_skipped_and_reported
# @matrix ai-report : evidence-mapping existing-task focused-prompt issue partial-update persistence preservation submission-completion unreadable-pdf
# @matrix form-schema submission : empty issue preservation submission-completion
def complete_organize_submissions(
    proposal,
    report,
    user,
    generate=None,
    allow_empty_submission_updates=False,
    service_tier=None,
):
    """Complete every form-backed Organize target in one focused model call."""
    proposal = validate_proposal(
        proposal,
        allow_empty_submission_updates=True,
        require_pending_submission_target=True,
        allow_pending_submissions=True,
        user=user,
    )
    actions = proposal.get("actions") or []
    context = _submission_completion_context(proposal, report, user)
    targets = []
    request_actions = {}
    prior_schema_updates = []

    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        action_type = action.get("type")
        if action_type == "update_form_schema":
            prior_schema_updates.append(action)
            continue
        if action_type not in {
            "create_page",
            "create_task",
            "update_submission_fields",
        }:
            continue

        data = action.get("data") or {}
        if not isinstance(data, dict):
            continue
        form_info = _completion_form_info(action, context)
        if not form_info:
            if _has_form_reference_or_label(data):
                raise exceptions.AIException(
                    f"Organize action {action.get('id') or index + 1} references "
                    "a form that could not be resolved."
                )
            continue
        form_info = _form_info_with_schema_updates(
            form_info,
            prior_schema_updates,
            context,
        )
        expected_type = _completion_target_type(action)
        if form_info.get("form_type") != expected_type:
            raise exceptions.AIException(
                f"Organize action {action.get('id') or index + 1} resolved a "
                f"{form_info.get('form_type') or 'unknown'} form for a "
                f"{expected_type} record."
            )

        if action_type == "create_task" and not _first_data_reference(data, "form"):
            _inject_completion_form_reference(data, form_info)

        request_id = action.get("id") or f"action_{index + 1}"
        files, fallback_files = _completion_file_contexts_for_action(
            action,
            context,
        )
        target = _completion_target_context(
            request_id,
            action,
            form_info,
            files,
            fallback_files,
            context,
        )
        if not target["form"]["schema"]:
            raise exceptions.AIException(
                f"Organize action {request_id} resolved a form without schema fields."
            )
        targets.append(target)
        request_actions[request_id] = (index, action)

    if targets:
        completion_context = _completion_prompt_context(report, proposal, targets)
        ai_debug(
            "organize.submission_completion.start",
            target_count=len(targets),
            targets=[_completion_target_debug_summary(target) for target in targets],
        )
        prompt = organize_submission_completion_prompt(
            completion_context,
            service_tier=service_tier,
        )
        if generate:
            raw_result = generate(prompt)
            results = validate_organize_submission_results(raw_result, targets)
        else:
            results = ai_model.generate_content(
                prompt,
                validator=lambda result: validate_organize_submission_results(
                    result,
                    targets,
                ),
            )
        ai_debug(
            "organize.submission_completion.complete",
            target_count=len(targets),
            results=_completion_results_debug_summary(results),
        )
        for target in targets:
            request_id = target["action_id"]
            index, action = request_actions[request_id]
            result = results.get(request_id, {})
            submission = result.get("submission")
            if action.get("type") == "update_submission_fields":
                _apply_completed_submission_update(
                    proposal,
                    action,
                    target,
                    submission,
                    result.get("empty_reason"),
                )
            elif isinstance(submission, dict) and submission:
                data = action.setdefault("data", {})
                data["submission"] = submission
                data.pop("submission_empty_reason", None)
            else:
                reason = result.get("empty_reason") or (
                    "No submission fields were filled from the available evidence."
                )
                data = action.setdefault("data", {})
                data["submission"] = {}
                data["submission_empty_reason"] = reason
                issue = f"{action.get('display_label') or request_id}: {reason}"
                if issue not in proposal["issues"]:
                    proposal["issues"].append(issue)

    for file in getattr(report, "input_files", []) or []:
        issue = _report_file_summary_warning(file)
        if issue and issue not in proposal["issues"]:
            proposal["issues"].append(issue)

    return validate_proposal(
        proposal,
        allow_empty_submission_updates=allow_empty_submission_updates,
        allow_pending_submissions=False,
        user=user,
    )
