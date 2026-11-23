"""Deferred-job dispatch identity, attempts, deadlines, and lease values."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities import types as models


import hashlib

from .base_db import DBProperty


class DispatchState(DBProperty[str]):
    _id = "dispatch_state"


class TaskIdentity(DBProperty[str]):
    _id = "task_identity"

    @staticmethod
    def create(job: models.DeferredJob, attempt: int, *, suffix: str | None = None) -> str:
        digest = hashlib.sha256(job.idempotency_key.encode("utf-8")).hexdigest()[:32]
        task_id = f"job-{digest}-a{int(attempt)}"
        if suffix:
            bounded = "".join(
                character
                for character in str(suffix).lower()
                if character.isalnum() or character == "-"
            )[:40]
            if bounded:
                task_id = f"{task_id}-{bounded}"
        return task_id

    @staticmethod
    def feedback(job: models.DeferredJob) -> str:
        digest = hashlib.sha256(job.idempotency_key.encode("utf-8")).hexdigest()[:32]
        return f"job-{digest}-feedback"


class DispatchedAt(DBProperty[datetime]):
    _id = "dispatched_at"


class DeadlineAt(DBProperty[datetime]):
    _id = "deadline_at"


class Attempt(DBProperty[int]):
    _id = "attempt"


class LeaseToken(DBProperty[str]):
    _id = "lease_token"


class LeaseExpires(DBProperty[datetime]):
    _id = "lease_expires"


class NextAttemptAt(DBProperty[datetime]):
    _id = "next_attempt_at"
