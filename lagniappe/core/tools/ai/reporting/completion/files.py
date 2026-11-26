"""Input-file preparation for AI reports."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import nullcontext
from contextvars import copy_context
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from lagniappe.core.entities import types as models


from lagniappe.core.definitions import LARGE_ASSET_BYTES, DeferredJobPhase

from ...core import ai_model
from ...debug import ai_debug
from ...observability import current_execution_control
from ...provider_policy import PROVIDER_REQUEST_ERRORS
from ...summarize import (
    PDF_PAGE_LIMIT_SUMMARY_ERROR,
    UNREADABLE_PDF_SUMMARY_ERROR,
    can_summarize_file,
    generate_summary,
)

class ReportInputFiles(Protocol):
    @property
    def input_files(self) -> Sequence[models.File]: ...


OVERSIZED_REPORT_SUMMARY = "File too large to summarize."
DIRECT_UPLOAD_TOKEN_BUDGET = 32_000
SUMMARY_WORKERS = 4


def use_original_report_files(report: ReportInputFiles) -> bool:
    """Choose direct planning only when the whole fresh bundle fits."""
    parts = []
    total_bytes = 0
    for file in report.input_files:
        size = file.size
        part = file.properties.file.uri_to_ai
        if not part or size is None or size <= 0 or file.has_references or not file.hash:
            return False
        if _has_report_file_summary(file) or _report_file_summary_warning(file):
            return False
        total_bytes += size
        if total_bytes > LARGE_ASSET_BYTES:
            return False
        parts.append(part)
    if not parts:
        return False
    # UTF-8 bytes conservatively bound tokens for small text-only uploads.
    if total_bytes <= DIRECT_UPLOAD_TOKEN_BUDGET and all(p["mime_type"].startswith("text/") for p in parts):
        return True
    try:
        tokens = ai_model.count_file_tokens(parts)
    except PROVIDER_REQUEST_ERRORS as error:
        ai_debug("report.upload_token_count.unavailable", error_type=type(error).__name__)
        return False
    return tokens is not None and 0 < tokens <= DIRECT_UPLOAD_TOKEN_BUDGET


def _has_report_file_summary(file):
    return bool(str(getattr(file, "summary", None) or "").strip())


def _report_file_summary_warning(file):
    summarize = getattr(getattr(file, "properties", None), "summarize", None)
    error = getattr(summarize, "error", None)
    if error not in {UNREADABLE_PDF_SUMMARY_ERROR, PDF_PAGE_LIMIT_SUMMARY_ERROR}:
        return None
    label = (
        getattr(file, "filename", None)
        or getattr(file, "name", None)
        or "the uploaded PDF"
    )
    if error == PDF_PAGE_LIMIT_SUMMARY_ERROR:
        return f"Could not read {label}. {PDF_PAGE_LIMIT_SUMMARY_ERROR}"
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
    """Generate missing summaries concurrently and checkpoint each completed file."""
    def prepare(file: models.File) -> bool:
        attempted_summary = _can_summarize_report_file(file)
        if attempted_summary:
            if service_tier:
                generate_summary(file, raise_quota=raise_quota, service_tier=service_tier)
            else:
                generate_summary(file, raise_quota=raise_quota)

        if _report_file_summary_warning(file):
            return attempted_summary

        if not _has_report_file_summary(file) and _is_large_report_file(file):
            _set_oversized_report_summary(file)

        if _has_report_file_summary(file):
            _complete_report_file_summary(file, search=search)
            return True
        return False

    # Duplicate references describe one stored File and must never race a save.
    unique_files = {}
    for file in report.input_files:
        unique_files.setdefault(file.key or id(file), file)
    files = list(unique_files.values())
    missing = ((index, file) for index, file in enumerate(files) if not _has_report_file_summary(file))
    completed: set[int] = set()
    pending = {}
    failure = None
    control = current_execution_control()
    phase = control.hold_phase(DeferredJobPhase.SUMMARIZING) if control else nullcontext()
    with phase, ThreadPoolExecutor(max_workers=SUMMARY_WORKERS) as workers:
        while True:
            while failure is None and len(pending) < SUMMARY_WORKERS:
                item = next(missing, None)
                if item is None:
                    break
                if ensure_active:
                    ensure_active()
                index, file = item
                future = workers.submit(copy_context().run, prepare, file)
                pending[future] = (index, file)
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                index, file = pending.pop(future)
                try:
                    changed = future.result()
                except Exception as error:
                    # Drain work already started and retain its successes for a retry.
                    failure = failure or error
                    continue
                if changed:
                    if ensure_active:
                        ensure_active()
                    if save:
                        save(file)
                    if _has_report_file_summary(file):
                        completed.add(index)
    if failure is not None:
        raise failure
    return [files[index] for index in sorted(completed)]
