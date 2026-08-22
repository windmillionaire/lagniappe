"""Deferred-job dispatch identity, attempts, deadlines, and lease values."""

import hashlib

from .base_db import DBProperty


class DispatchState(DBProperty):
    _id = "dispatch_state"


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_task_identity_is_deterministic_and_bounded
# @pair deferred-jobs:task-identity
# @pair deferred-jobs:feedback-identity
class TaskIdentity(DBProperty):
    _id = "task_identity"

    @staticmethod
    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_task_identity_is_deterministic_and_bounded
    # @pair deferred-jobs:task-identity
    def create(job, attempt, *, suffix=None):
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
    def feedback(job):
        digest = hashlib.sha256(job.idempotency_key.encode("utf-8")).hexdigest()[:32]
        return f"job-{digest}-feedback"


class DispatchedAt(DBProperty):
    _id = "dispatched_at"


class DeadlineAt(DBProperty):
    _id = "deadline_at"


class Attempt(DBProperty):
    _id = "attempt"


class LeaseToken(DBProperty):
    _id = "lease_token"


class LeaseExpires(DBProperty):
    _id = "lease_expires"


class NextAttemptAt(DBProperty):
    _id = "next_attempt_at"
