"""Durable ledger construction and restoration for report execution."""

import hashlib

from lagniappe.core import exceptions
from lagniappe.core.properties.ai_report_proposal import (
    proposal_fingerprint as proposal_fingerprint,
)

from .actions.references import (
    _load_result_entity,
)
from .actions.results import (
    _remember_created,
)

REPORT_LEDGER_VERSION = 1


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason action identity is asserted through public retry behavior
def _action_idempotency_key(report, proposal_fingerprint, index, action):
    value = ":".join(
        (
            report.urlsafe_key,
            proposal_fingerprint,
            str(index),
            str(action.get("id") or ""),
            str(action.get("type") or ""),
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason ledger construction is asserted through public retry behavior
def _new_report_ledger(report, proposal, proposal_fingerprint):
    return {
        "ledger_version": REPORT_LEDGER_VERSION,
        "proposal_fingerprint": proposal_fingerprint,
        "status": "running",
        "actions": [
            {
                "id": action.get("id"),
                "type": action.get("type"),
                "display_label": action.get("display_label"),
                "idempotency_key": _action_idempotency_key(
                    report,
                    proposal_fingerprint,
                    index,
                    action,
                ),
                "status": "pending",
                "attempts": 0,
            }
            for index, action in enumerate(proposal.get("actions") or [])
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason ledger validation is exercised through public resume behavior
def _validate_report_ledger(proposal, result):
    actions = proposal.get("actions") or []
    records = result.get("actions") or []
    if len(actions) != len(records):
        raise exceptions.ValidationError("Stored report recovery ledger is invalid.")
    for action, record in zip(actions, records):
        if (
            record.get("id") != action.get("id")
            or record.get("type") != action.get("type")
            or not record.get("idempotency_key")
        ):
            raise exceptions.ValidationError(
                "Stored report recovery ledger does not match the proposal."
            )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason created-reference restoration is exercised through dependent retries
def _restore_completed_action_entities(result):
    created = {}
    for record in result.get("actions") or []:
        if record.get("status") != "complete":
            continue
        _restore_created_action_entity(created, record)
    return created


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason created-reference restoration is exercised through dependent retries
def _restore_created_action_entity(created, record):
    if not str(record.get("type") or "").startswith("create_"):
        return
    entity = _load_result_entity(record.get("entity"))
    if entity is None:
        return
    action = {"id": record.get("id")}
    _remember_created(created, action, entity)
