"""Target-scoped deferred-job lock values and operation descriptors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.tools.deferred_jobs.locks import LockJobView, LockView
    from lagniappe.core.entities.entity import Entity


import hashlib

from .base_db import DBProperty


class Target(DBProperty[str]):
    _id = "target"


class Operation(DBProperty[str]):
    _id = "operation"

    @staticmethod
    def descriptor(lock: LockView, job: LockJobView) -> dict[str, object]:
        return {
            "locked": True,
            "blocks_edit": lock.scope == Scope.FORM_CHANGE,
            "scope": lock.scope,
            "operation": job.urlsafe_key,
            "revision": int(job.status_revision or 0),
        }


class IdempotencyKey(DBProperty[str]):
    _id = "idempotency_key"


class Scope(DBProperty[str]):
    _id = "scope"

    AUTOFILL_FORM = "form-autofill"
    FORM_CHANGE = "form-change"

    @staticmethod
    def identifier(target: Entity | str | None, scope: str = AUTOFILL_FORM) -> str | None:
        target_key = getattr(target, "urlsafe_key", target)
        if not target_key:
            return None
        return hashlib.sha256(f"{scope}:{target_key}".encode()).hexdigest()
