"""Creator-owned report history deletion and upload cleanup."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...entities.ai_report import AIReport
    from ...entities.user import User

from contextlib import suppress
from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import agent_api as agent_api_store
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

from . import external_operations
from .reporting import uploads as report_uploads


def delete_report_record(report: AIReport) -> str:
    """Fence every deletion against concurrent execution and correction links."""
    from .reporting.schema_updates import migration_pending

    if not report.available:
        snapshot = external_operations.report_snapshot(report)
        files_to_delete = [file for file in report.input_files if not file.has_references and not _other_report_references(file, report)]
        outcome = external_operations.delete_plan_if_idle(report, snapshot, report, *files_to_delete)
        if outcome == agent_api_store.PLAN_OPERATION_COMMITTED:
            # Obsolete payloads cannot prevent deletion of the report.
            with suppress(ValueError, TypeError, AttributeError, KeyError):
                report_uploads.cleanup_report_upload_manifest(report)
        return outcome
    if migration_pending(report):
        return agent_api_store.PLAN_OPERATION_BUSY
    if report.origin == "api" and report.deferred_job:
        return agent_api_store.PLAN_OPERATION_BUSY

    files_to_delete = [file for file in report.input_files if not file.has_references and not _other_report_references(file, report)]
    snapshot = external_operations.report_snapshot(report)
    deferred_job = report.deferred_job
    upload_manifest = report.upload_manifest
    outcome = external_operations.delete_plan_if_idle(
        report, snapshot, report, *files_to_delete
    )
    if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
        return outcome

    # Even an unlinked source can acquire its first correction concurrently.
    # Fence deletion before cleaning up evidence owned by the current report.
    DeferredJobs.cancel(deferred_job)
    report.upload_manifest = upload_manifest
    report_uploads.cleanup_report_upload_manifest(report)
    return agent_api_store.PLAN_OPERATION_COMMITTED


def delete_executed_reports(user: User, keys: Iterable[str]) -> dict[str, list[str]]:
    """Delete only the supplied, still-executed proposals owned by this user."""
    results = {"deleted": [], "skipped": [], "failed": []}
    for key in dict.fromkeys(keys):
        try:
            report = Entities.fetch_one(key, request=Fetch.direct())
            if (
                not isinstance(report, Entities.REPORT)
                or report.properties.parent.key != user.key
                or not report.available
                or report.output_kind != "proposal"
                or report.status != "complete"
                or report.pending
            ):
                results["skipped"].append(key)
                continue
            outcome = delete_report_record(report)
            result = (
                "deleted"
                if outcome == agent_api_store.PLAN_OPERATION_COMMITTED
                else "skipped"
            )
            results[result].append(key)
        except Exception as error:
            exceptions.capture(
                error,
                context={"operation": "delete_executed_report", "report_key": key},
            )
            results["failed"].append(key)

    if results["deleted"]:
        Entities.touch(user)
    return results


def _other_report_references(file, report):
    return any(Entities.fetch_one(reference, request=Fetch.root()) is not None for reference in file.db.get("report_refs", []) if reference != report.urlsafe_key)
