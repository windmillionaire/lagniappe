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


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_task_identity_is_deterministic_and_bounded
# @matrix deferred-jobs : feedback-identity task-identity
class TaskIdentity(DBProperty[str]):
    _id = "task_identity"

    @staticmethod
    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_task_identity_is_deterministic_and_bounded
    # @pair deferred-jobs:task-identity
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
    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_task_identity_is_deterministic_and_bounded
    # @pair deferred-jobs:feedback-identity
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
