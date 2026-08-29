"""Input-file preparation for Organize reports."""

from lagniappe.core.definitions import LARGE_ASSET_BYTES

from ...summarize import (
    UNREADABLE_PDF_SUMMARY_ERROR,
    can_summarize_file,
    generate_summary,
)

OVERSIZED_REPORT_SUMMARY = "File too large to summarize."


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/completion/files.py::summarize_report_input_files
# @covered-by lagniappe/core/tools/ai/reporting/completion/service.py::complete_organize_submissions
# @reason summary presence is exercised through organize summary and completion tests
def _has_report_file_summary(file):
    return bool(str(getattr(file, "summary", None) or "").strip())


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/completion/files.py::summarize_report_input_files
# @covered-by lagniappe/core/tools/ai/reporting/completion/service.py::complete_organize_submissions
# @reason warning projection is exercised through the report prepass and result
def _report_file_summary_warning(file):
    summarize = getattr(getattr(file, "properties", None), "summarize", None)
    if getattr(summarize, "error", None) != UNREADABLE_PDF_SUMMARY_ERROR:
        return None
    label = (
        getattr(file, "filename", None)
        or getattr(file, "name", None)
        or "the uploaded PDF"
    )
    return f"Could not read {label}. The PDF may be encrypted or password-protected."


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/completion/files.py::summarize_report_input_files
# @reason summary eligibility is exercised through the report summary prepass
def _can_summarize_report_file(file):
    if _has_report_file_summary(file) or _report_file_summary_warning(file):
        return False
    return can_summarize_file(file)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/completion/files.py::summarize_report_input_files
# @reason large-file metadata fallback is exercised through the summary prepass
def _is_large_report_file(file):
    large = getattr(file, "large", None)
    if large is not None:
        return bool(large)

    size = getattr(file, "size", None)
    try:
        return size is not None and int(size) > LARGE_ASSET_BYTES
    except (TypeError, ValueError):
        return False


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/completion/files.py::summarize_report_input_files
# @reason summary state mutation is asserted through the public prepass
def _complete_report_file_summary(file, *, search):
    summarize = file.properties.summarize
    summarize.enabled = True
    summarize.search = search
    summarize.complete = True


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/completion/files.py::summarize_report_input_files
# @reason oversized fallback state is asserted through the public prepass
def _set_oversized_report_summary(file):
    file.summary = OVERSIZED_REPORT_SUMMARY
    summarize = file.properties.summarize
    summarize.status = OVERSIZED_REPORT_SUMMARY
    summarize.error = None


# @testable true
# @tests tests_unit/test_020d_ai_report_prompts.py::test_summarize_report_input_files_saves_missing_summaries
# @tests tests_unit/test_020d_ai_report_prompts.py::test_summarize_report_input_files_falls_back_for_large_files
# @tests tests_unit/test_020d_ai_report_prompts.py::test_unreadable_pdf_is_saved_skipped_and_reported
# @matrix ai-report : active-request fallback large-file quota search-opt-in summary-prepass unreadable-pdf
def summarize_report_input_files(
    report,
    save=None,
    search=True,
    raise_quota=True,
    service_tier=None,
    ensure_active=None,
):
    """Generate missing summaries for report files before Organize planning."""
    summarized = []
    for file in report.input_files:
        attempted_summary = False
        if ensure_active:
            ensure_active()
        if _has_report_file_summary(file):
            continue

        large = _is_large_report_file(file)
        if _can_summarize_report_file(file):
            attempted_summary = True
            summary_options = {"raise_quota": raise_quota}
            if service_tier:
                summary_options["service_tier"] = service_tier
            generate_summary(file, **summary_options)

        if _report_file_summary_warning(file):
            if save and attempted_summary:
                if ensure_active:
                    ensure_active()
                save(file)
            continue

        if not _has_report_file_summary(file) and large:
            _set_oversized_report_summary(file)

        if _has_report_file_summary(file):
            _complete_report_file_summary(file, search=search)
            summarized.append(file)
            if save:
                if ensure_active:
                    ensure_active()
                save(file)
    return summarized
