"""Durable ledger construction and restoration for report execution."""

from __future__ import annotations

from typing import Required, TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from lagniappe.core.entities import types as models
    from lagniappe.core.tools.ai.reporting.contracts.actions import ReportProposal


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

class ActionRecord(TypedDict, total=False):
    id: str | None
    type: str
    display_label: str | None
    idempotency_key: Required[str]
    status: str
    attempts: int
    prepared: bool
    expected: dict[str, object]
    before: dict[str, object]
    note: str
    error: str
    document_at: str
    document_after: dict[str, str | None]
    entity: dict[str, object]
    migration_id: str
    batch_skipped: bool


class ReportLedger(TypedDict, total=False):
    ledger_version: int
    proposal_fingerprint: str
    status: str
    actions: Required[list[ActionRecord]]
    failed_at: int


REPORT_LEDGER_VERSION = 1


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


def _new_report_ledger(
    report: models.AIReport, proposal: ReportProposal, proposal_fingerprint: str
) -> ReportLedger:
    return {
        "ledger_version": REPORT_LEDGER_VERSION,
        "proposal_fingerprint": proposal_fingerprint,
        "status": "running",
        "actions": [
            {
                "id": action.get("id"),
                "type": action["type"],
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


def _validate_report_ledger(proposal, result):
    actions = proposal.get("actions") or []
    records = result.get("actions") or []
    if len(actions) != len(records):
        raise exceptions.ValidationError("Stored report recovery ledger is invalid.")
    for action, record in zip(actions, records, strict=True):
        if (
            record.get("id") != action.get("id")
            or record.get("type") != action.get("type")
            or not record.get("idempotency_key")
        ):
            raise exceptions.ValidationError(
                "Stored report recovery ledger does not match the proposal."
            )


def _restore_completed_action_entities(result):
    created = {}
    for record in result.get("actions") or []:
        if record.get("status") != "complete":
            continue
        _restore_created_action_entity(created, record)
    return created


def _restore_created_action_entity(created, record):
    if not str(record.get("type") or "").startswith("create_"):
        return
    entity = _load_result_entity(record.get("entity"))
    if entity is None:
        return
    action = {"id": record.get("id")}
    _remember_created(created, action, entity)
