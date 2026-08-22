"""Target-scoped deferred-job lock values and operation descriptors."""

import hashlib

from .base_db import DBProperty


class Target(DBProperty):
    _id = "target"


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lock_properties_own_identity_and_projection
# @pair deferred-jobs:browser-projection
class Operation(DBProperty):
    _id = "operation"

    @staticmethod
    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lock_properties_own_identity_and_projection
    # @pair deferred-jobs:browser-projection
    def descriptor(lock, job):
        return {
            "locked": True,
            "scope": lock.scope,
            "operation": job.urlsafe_key,
            "revision": int(job.status_revision or 0),
        }


class IdempotencyKey(DBProperty):
    _id = "idempotency_key"


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lock_properties_own_identity_and_projection
# @pair deferred-jobs:lock-identity
class Scope(DBProperty):
    _id = "scope"

    AUTOFILL_FORM = "form-autofill"

    @staticmethod
    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lock_properties_own_identity_and_projection
    # @pair deferred-jobs:lock-identity
    def identifier(target, scope=AUTOFILL_FORM):
        target_key = getattr(target, "urlsafe_key", target)
        if not target_key:
            return None
        return hashlib.sha256(f"{scope}:{target_key}".encode("utf-8")).hexdigest()
