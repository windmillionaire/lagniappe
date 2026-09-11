"""Creator-owned report history deletion and upload cleanup."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai
from lagniappe.core.tools.ai import external_operations
from lagniappe.core.tools.database import agent_api as agent_api_store
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs


# @testable true
# @tests tests_unit/test_020i_report_history.py::test_report_delete_preserves_referenced_files_and_fences_cleanup
# @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
# @matrix ai-report : delete file-cleanup guarded-delete
def delete_report_record(report, *, guarded=False):
    """Reuse ordinary deletion, with a revision fence for bulk/API requests."""
    if report.origin == "api" and (report.deferred_job or report.status == "undoing"):
        return agent_api_store.PLAN_OPERATION_BUSY

    files_to_delete = [file for file in report.input_files if not file.has_references]
    if guarded or report.origin == "api":
        snapshot = external_operations.report_snapshot(report)
        deferred_job = report.deferred_job
        upload_manifest = report.upload_manifest
        outcome = external_operations.delete_plan_if_idle(
            report, snapshot, report, *files_to_delete
        )
        if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
            return outcome

        # Cleanup must follow the durable fence: a stale or busy request must
        # not destroy uploads still owned by the authoritative report.
        DeferredJobs.cancel(deferred_job)
        report.upload_manifest = upload_manifest
        ai.cleanup_report_upload_manifest(report)
    else:
        DeferredJobs.cancel(report.deferred_job)
        ai.cleanup_report_upload_manifest(report)
        Entities.delete(report, *files_to_delete)
    return agent_api_store.PLAN_OPERATION_COMMITTED


# @testable true
# @tests tests_unit/test_020i_report_history.py::test_bulk_delete_scopes_ownership_state_snapshot_and_partial_failures
# @tests tests_e2e/002_home/test_002n_home_report_filters.py::test_delete_executed_reports_confirms_snapshot_and_preserves_workspace
# @matrix ai-report : bulk-delete delete-snapshot ownership delete-failure
def delete_executed_reports(user, keys):
    """Delete only the supplied, still-executed proposals owned by this user."""
    results = {"deleted": [], "skipped": [], "failed": []}
    for key in dict.fromkeys(keys):
        try:
            report = Entities.fetch_one(key, request=Fetch.direct())
            if (
                not isinstance(report, Entities.REPORT)
                or report.properties.parent.key != user.key
                or report.tool not in {"create", "organize"}
                or report.status != "complete"
                or report.pending
            ):
                results["skipped"].append(key)
                continue
            outcome = delete_report_record(report, guarded=True)
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
