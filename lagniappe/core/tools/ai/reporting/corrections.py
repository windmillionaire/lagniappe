"""Linked corrective reports and guarded supersession of executed plans."""

from copy import deepcopy
import json

from google.cloud.datastore import Entity as DatastoreEntity

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.database.utility import ExactEntityState
from .entity_updates import _fingerprint


# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_correction_snapshot_and_approval_reject_changed_source
# @matrix ai-report : correction ownership supersession
def link_correction(report, source, user):
    """Retain bounded source evidence without changing its retry eligibility."""
    _check_source(source, user)
    snapshot = {"proposal": deepcopy(source.proposal), "result": deepcopy(source.result)}
    if len(json.dumps(snapshot, default=str).encode()) > 250 * 1024:
        raise ValidationError("This execution is too large for a corrective snapshot. Create a new plan from current workspace state.")
    report.db["correction"] = _unindexed_snapshot({"source": source.urlsafe_key, "fingerprint": _fingerprint(snapshot), **snapshot})
    report.input_files = list(source.input_files)
    return report


# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_correction_snapshot_and_approval_reject_changed_source
# @matrix ai-report : correction ownership supersession
def approve_correction(report, user):
    """Atomically fence source retries when the browser approves a correction."""
    correction = report.db.get("correction")
    if not correction:
        return
    source = Entities.fetch_one(correction["source"], request=Fetch.direct())
    if source and source.db.get("superseded_by") == report.urlsafe_key:
        return
    _check_source(source, user)
    if correction["fingerprint"] != _fingerprint({"proposal": source.proposal, "result": source.result}):
        raise ValidationError("The original execution changed. Create a fresh correction before approving it.")
    guards = [(source.key, ExactEntityState(deepcopy(dict(source.db)))), (report.key, ExactEntityState(deepcopy(dict(report.db))))]
    source.db["superseded_by"] = report.urlsafe_key
    source._form_additional_guards = guards
    Entities.save(source, report)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/corrections.py::link_correction
# @covered-by lagniappe/core/tools/ai/reporting/corrections.py::approve_correction
# @reason correction creation and approval enforce the same stopped creator-owned source
def _check_source(source, user):
    if not isinstance(source, Entities.REPORT) or not source.available or source.properties.user.key != user.key:
        raise ValidationError("Choose an available plan that you created.")
    if source.pending or source.status not in {"complete", "failed"} or not source.proposal or not isinstance(source.result, dict) or source.result.get("status") not in {"complete", "failed"} or not isinstance(source.result.get("actions"), list):
        raise ValidationError("Wait for execution to stop before creating a corrective plan.")
    if source.db.get("superseded_by"):
        raise ValidationError("This execution already has an approved correction.")
    from .schema_updates import migration_pending
    if migration_pending(source):
        raise ValidationError("Finish or recover the active Form migration before correcting this plan.")
    if any(record.get("status") == "applying" or (record.get("status") == "failed" and record.get("expected")) for record in source.result.get("actions", [])):
        raise ValidationError("Reconcile the interrupted execution with Retry before creating a correction.")
# @testable true
# @tests tests_unit/test_032g_entity_patches.py::test_corrections_share_evidence_across_origins_and_fence_source_retries
# @matrix ai-report : correction ownership supersession
def save_correction(report, source):
    guards = [(source.key, ExactEntityState(deepcopy(dict(source.db))))]
    source.db["correction_children"] = list(dict.fromkeys([*source.db.get("correction_children", []), report.urlsafe_key]))
    for file in report.input_files:
        guards.append((file.key, ExactEntityState(deepcopy(dict(file.db)))))
        file.db["report_refs"] = list(dict.fromkeys([*file.db.get("report_refs", []), source.urlsafe_key, report.urlsafe_key]))
    report._form_additional_guards = guards
    Entities.save(source, report, *report.input_files)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/corrections.py::link_correction
# @reason correction snapshots must exclude nested answer and execution content from indexes
def _unindexed_snapshot(value):
    """Exclude every embedded snapshot property, including long answer HTML."""
    if isinstance(value, dict):
        result = DatastoreEntity(exclude_from_indexes=tuple(value))
        result.update({key: _unindexed_snapshot(child) for key, child in value.items()})
        return result
    if isinstance(value, list):
        return [_unindexed_snapshot(child) for child in value]
    return value
