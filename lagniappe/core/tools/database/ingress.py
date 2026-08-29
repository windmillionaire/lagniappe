"""Ingress cursor and row-commit transactions."""

import json

from google.cloud.datastore import Key

from .core import DATA
from .utility import _put_mutation, update_site_fingerprints


# @testable false
# @covered-by lagniappe/core/tools/database/ingress.py::commit_ingress_row
# @reason shared key normalization is exercised through public ingress cursor helpers
def _ingress_key(identifier):
    if isinstance(identifier, Key):
        return identifier
    if hasattr(identifier, "key"):
        return identifier.key
    from .get import datastore_key

    return datastore_key(identifier)


# @testable false
# @covered-by lagniappe/core/tools/database/ingress.py::commit_ingress_row
# @reason stored execution decoding is exercised through public ingress cursor helpers
def _ingress_execution(entity):
    raw = entity.get("execution", "{}")
    try:
        execution = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        execution = {}
    return execution if isinstance(execution, dict) else {}


# @testable true
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_status_update_is_cursor_checked
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_stop_is_durable_and_preserves_current_row_boundary
# @matrix ingress : compare-and-set cursor failure status stop
def update_ingress_status(identifier, status, now, *, expected_cursor=None, error=None):
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


# @testable true
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_row_commit_requires_expected_cursor_and_applies_masks
# @tests tests_unit/test_006d_ingress_service.py::test_ingress_row_commit_rejects_duplicate_cursor
# @matrix ingress : compare-and-set cursor duplicate-delivery durable-commit property-mask
def commit_ingress_row(identifier, expected_cursor, ingress_entity, writes, now):
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
