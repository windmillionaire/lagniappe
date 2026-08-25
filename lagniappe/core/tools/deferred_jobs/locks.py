"""Target-scoped deferred-job lock collection and browser projection."""

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.properties.deferred_job_lifecycle import ACTIVE_STATUSES
from lagniappe.core.properties.deferred_job_lock import Operation, Scope
from lagniappe.core.tools import database


AUTOFILL_FORM_LOCK_SCOPE = Scope.AUTOFILL_FORM


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lock_resolution_is_target_scoped
# @matrix deferred-jobs : deterministic-key form-lock
def deferred_job_lock_key(target, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Return the deterministic lock key for one target mutation surface."""
    identifier = Scope.identifier(target, scope)
    return database.create_named_key("job_lock", identifier) if identifier else None


# @testable infrastructure
# @covered-by lagniappe/core/tools/deferred_jobs/locks.py::deferred_job_lock_descriptor
def active_deferred_job_lock(target, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Return ``(lock, job)`` while the target's referenced job is active."""
    target_key = getattr(target, "urlsafe_key", target)
    return deferred_job_lock_descriptors([target], scope=scope).get(target_key)


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lock_resolution_is_target_scoped
# @matrix deferred-jobs : form-lock stale-cleanup
def deferred_job_lock_descriptors(targets, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Batch-resolve active locks keyed by target urlsafe key."""
    targets = [target for target in targets or () if target]
    target_keys = [getattr(target, "urlsafe_key", target) for target in targets]
    lock_keys = [deferred_job_lock_key(target, scope) for target in targets]
    locks = {
        lock.target: lock
        for lock in Entities.fetch(*lock_keys, request=Fetch.direct())
        if isinstance(lock, Entities.DEFERRED_JOB_LOCK) and lock.operation
    }
    jobs = {
        job.urlsafe_key: job
        for job in Entities.fetch(
            *(lock.operation for lock in locks.values()), request=Fetch.direct()
        )
        if isinstance(job, Entities.DEFERRED_JOB)
    }
    active = {}
    for target_key in target_keys:
        lock = locks.get(target_key)
        job = jobs.get(lock.operation) if lock else None
        if lock and job and job.status in ACTIVE_STATUSES:
            active[target_key] = (lock, job)
        elif lock:
            database.release_deferred_job_lock(lock.key, lock.operation)
    return active


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_lock_descriptor_is_browser_safe
# @matrix deferred-jobs : browser-projection form-lock
def deferred_job_lock_descriptor(target, scope=AUTOFILL_FORM_LOCK_SCOPE):
    """Return the browser-safe active-operation descriptor for ``target``."""
    active = active_deferred_job_lock(target, scope)
    return Operation.descriptor(*active) if active is not None else None
