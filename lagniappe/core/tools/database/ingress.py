"""Ingress cursor and row-commit transactions."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

from google.cloud.datastore import Entity as Row
from google.cloud.datastore import Key

from .core import DATA
from .utility import _put_mutation, update_site_fingerprints

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity as DomainEntity

    from .get import Identifier


class StatusUpdate(TypedDict):
    updated: bool
    reason: str
    entity: Row | dict[str, object] | None
    execution: NotRequired[dict[str, object]]


class RowCommit(TypedDict):
    committed: bool
    reason: str
    entity: NotRequired[Row | dict[str, object]]
    execution: NotRequired[dict[str, object]]


def _ingress_key(identifier):
    if isinstance(identifier, Key):
        return identifier
    if hasattr(identifier, "key"):
        return identifier.key
    from .get import datastore_key

    return datastore_key(identifier)


def _ingress_execution(entity):
    raw = entity.get("execution", "{}")
    try:
        execution = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        execution = {}
    return execution if isinstance(execution, dict) else {}


def update_ingress_status(
    identifier: Identifier,
    status: str,
    now: datetime,
    *,
    expected_cursor: int | None = None,
    error: str | None = None,
) -> StatusUpdate:
    """Atomically stop or fail active ingress work without replacing its cursor."""
    key = _ingress_key(identifier)
    if key is None:
        return {"updated": False, "reason": "missing", "entity": None}
    with DATA.datastore.transaction() as transaction:
        entity = DATA.datastore.get(key, transaction=transaction)
        if entity is None:
            return {"updated": False, "reason": "missing", "entity": None}
        execution = _ingress_execution(entity)
        cursor = int(execution.get("cursor") or 0)
        if expected_cursor is not None and cursor != int(expected_cursor):
            return {
                "updated": False,
                "reason": "cursor",
                "entity": entity,
                "execution": execution,
            }
        current = execution.get("status", "idle")
        if current not in {"queued", "running", "stop_requested"}:
            return {
                "updated": False,
                "reason": current,
                "entity": entity,
                "execution": execution,
            }
        execution["status"] = status
        if error is None:
            execution.pop("error", None)
        else:
            execution["error"] = error
        execution.pop("lease_token", None)
        execution.pop("lease_expires", None)
        entity["execution"] = json.dumps(execution)
        entity["modified"] = now
        transaction.put(entity)
        return {
            "updated": True,
            "reason": status,
            "entity": entity,
            "execution": execution,
        }


def commit_ingress_row(
    identifier: Identifier,
    expected_cursor: int,
    ingress_entity: DomainEntity,
    writes: Iterable[tuple[DomainEntity, Iterable[str] | None]],
    now: datetime,
) -> RowCommit:
    """Commit one planned row and advance its ingress cursor atomically."""
    key = _ingress_key(identifier)
    if key is None:
        return {"committed": False, "reason": "missing"}

    raw_writes = {
        entity.key: (entity.db, property_mask)
        for entity, property_mask in writes
        if getattr(entity, "key", None) and entity.key != key
    }
    fingerprints = update_site_fingerprints(
        ingress_entity.db, *(raw for raw, _ in raw_writes.values())
    )

    with DATA.datastore.transaction() as transaction:
        stored = DATA.datastore.get(key, transaction=transaction)
        if stored is None:
            return {"committed": False, "reason": "missing"}
        stored_execution = _ingress_execution(stored)
        if int(stored_execution.get("cursor") or 0) != int(expected_cursor):
            return {
                "committed": False,
                "reason": "cursor",
                "entity": stored,
                "execution": stored_execution,
            }
        if stored_execution.get("status") not in {"queued", "running"}:
            return {
                "committed": False,
                "reason": "state",
                "entity": stored,
                "execution": stored_execution,
            }

        candidate = ingress_entity.db
        candidate_execution = _ingress_execution(candidate)
        candidate_execution["cursor"] = expected_cursor + 1
        candidate_execution.pop("lease_token", None)
        candidate_execution.pop("lease_expires", None)
        candidate["execution"] = json.dumps(candidate_execution)
        candidate["modified"] = now

        for raw, property_mask in raw_writes.values():
            _put_mutation(transaction, raw, property_mask)
        for fingerprint in fingerprints:
            transaction.put(fingerprint)
        transaction.put(candidate)
        return {
            "committed": True,
            "reason": (
                "stopped"
                if candidate_execution.get("status") == "stopped"
                else "committed"
            ),
            "entity": candidate,
            "execution": candidate_execution,
        }
