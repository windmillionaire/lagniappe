"""Input-file preparation for AI reports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from lagniappe.core.entities import types as models


from lagniappe.core.definitions import LARGE_ASSET_BYTES

from ...summarize import (
    UNREADABLE_PDF_SUMMARY_ERROR,
    can_summarize_file,
    generate_summary,
)

class ReportInputFiles(Protocol):
    @property
    def input_files(self) -> Sequence[models.File]: ...


OVERSIZED_REPORT_SUMMARY = "File too large to summarize."


def _has_report_file_summary(file):
    return bool(str(getattr(file, "summary", None) or "").strip())


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


def _can_summarize_report_file(file):
    if _has_report_file_summary(file) or _report_file_summary_warning(file):
        return False
    return can_summarize_file(file)


def _is_large_report_file(file):
    large = getattr(file, "large", None)
    if large is not None:
        return bool(large)

    size = getattr(file, "size", None)
    try:
        return size is not None and int(size) > LARGE_ASSET_BYTES
    except (TypeError, ValueError):
        return False


def _complete_report_file_summary(file, *, search):
    summarize = file.properties.summarize
    summarize.enabled = True
    summarize.search = search
    summarize.complete = True


def _set_oversized_report_summary(file):
    file.summary = OVERSIZED_REPORT_SUMMARY
    summarize = file.properties.summarize
    summarize.status = OVERSIZED_REPORT_SUMMARY
    summarize.error = None


def summarize_report_input_files(
    report: ReportInputFiles,
    save: Callable[[models.File], object] | None = None,
    search: bool = True,
    raise_quota: bool = True,
    service_tier: str | None = None,
    ensure_active: Callable[[], None] | None = None,
) -> list[models.File]:
    """Generate missing summaries for uploaded files before report planning."""
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
            if service_tier:
                generate_summary(file, raise_quota=raise_quota, service_tier=service_tier)
            else:
                generate_summary(file, raise_quota=raise_quota)

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
