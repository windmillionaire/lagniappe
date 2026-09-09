"""File movement, attachment, and summary report actions."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities

from .references import (
    _add_file_to_endpoint,
    _file_attached_to_endpoint,
    _resolve_entity,
    _resolve_file_endpoint,
    _resolve_file_entity,
    _resolve_report_file,
)
from .common import (
    _data,
    _require_allowed,
    _unique_entities,
)
from .results import (
    _entity_result,
    _file_summary_result,
)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_moves_file_and_records_manual_page_cleanup_with_undo
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_moves_file_by_exact_source_attachment_name
# @matrix ai-report : deterministic-run move-file readable-file-fallback
# @matrix files : deterministic-run manual-cleanup move-file readable-file-fallback undo
def _move_file(action, _report, user, created):
    data = _data(action)
    source = _resolve_file_endpoint(data, created, endpoint="source")
    target = _resolve_file_endpoint(data, created, endpoint="target")
    file = _resolve_file_entity(data, created, source=source)
    if getattr(source, "entity_kind", None) == getattr(
        target, "entity_kind", None
    ) and getattr(source, "key", None) == getattr(target, "key", None):
        raise exceptions.ValidationError("File move source and target are the same.")

    _require_allowed(
        source.allowed(Action.EDIT, user=user),
        "You do not have permission to move files from this source.",
    )
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to move files to this target.",
    )
    if not _file_attached_to_endpoint(file, source):
        raise exceptions.ValidationError("File is not attached to the source.")

    file.move_to(target)
    metadata = {
        "target": _entity_result(target),
        "moved": {
            "from": _entity_result(source),
            "to": _entity_result(target),
        },
        "previous": {
            "source": _entity_result(source),
            "target": _entity_result(target),
        },
        "file_summary": _file_summary_result(file),
    }
    return file, _unique_entities([file, source, target]), metadata


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_rejects_file_as_attachment_target_without_guessing_prior_page
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_rejects_attachment_target_guessing_from_page_name
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_marks_missing_file_placements_failed_and_continues
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_rejects_category_used_as_attachment_page
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_attach_file_targets_created_task
# @matrix ai-report : attachment attachments deterministic-run exact-page-name page-reference partial-result prior-task-page repair validation created-task persistence submission-completion task-attachment
# @matrix files : attachment exact-page-name page-reference prior-task-page repair
# @matrix files tasks : task-attachment
def _attach_file(action, report, user, created):
    data = _data(action)
    target = _resolve_entity(
        data.get("entity") or data.get("entity_action"),
        created,
    )
    if not isinstance(target, (Entities.PAGE, Entities.TASK, Entities.TASK_HISTORY)):
        raise exceptions.ValidationError(
            "Attachment target must be a Page, Task or task history."
        )
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to attach files to this target.",
    )
    file = _resolve_report_file(data.get("file"), report)
    if file.has_references:
        _require_allowed(file.allowed(Action.EDIT, user=user), "You do not have permission to move this file.")
    _add_file_to_endpoint(file, target)
    return file, [file, target], {"file_summary": _file_summary_result(file)}


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_resolves_report_file_by_exact_url_and_file_prefix
# @tests tests_unit/test_020g_ai_report_actions_forms.py::test_run_report_creates_form_category_page_and_project_chain
# @pair ai-report:file-summary
def _summarize_file(action, report, _user, _created):
    data = _data(action)
    file = _resolve_report_file(
        data.get("file") or data.get("file_id") or data.get("file_ref"),
        report,
    )
    summary = (data.get("summary") or data.get("description") or "").strip()
    if not summary:
        raise exceptions.ValidationError("Summarize file actions require summary text.")
    summarize = file.properties.summarize
    summarize.enabled = True
    summarize.search = data.get("search", True) is not False
    summarize.status = "Summary saved from report."
    summarize.error = None
    retrieval_terms = data.get("retrieval_terms")
    if isinstance(retrieval_terms, list):
        retrieval_terms = [
            term.strip()
            for term in retrieval_terms
            if isinstance(term, str) and term.strip()
        ][:2]
    else:
        retrieval_terms = []
    summarize.retrieval_terms = retrieval_terms or None
    summarize.complete = True
    file.summary = summary
    return file, [file], {"file_summary": _file_summary_result(file)}
