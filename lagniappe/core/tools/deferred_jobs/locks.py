"""Target-scoped deferred-job lock collection and browser projection."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from google.cloud.datastore import Key
    from ...entities.entity import Entity

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.properties.deferred_job_lifecycle import ACTIVE_STATUSES
from lagniappe.core.properties.deferred_job_lock import Operation, Scope
from lagniappe.core.tools.database import deferred_jobs as database_deferred_jobs
from lagniappe.core.tools.database import utility as database_utility


class LockView(Protocol):
    @property
    def scope(self) -> str | None: ...


class LockJobView(Protocol):
    @property
    def urlsafe_key(self) -> str: ...
    @property
    def status_revision(self) -> int | None: ...


type ActiveLock = tuple[LockView, LockJobView]


@dataclass(frozen=True)
class _PendingLock:
    scope: str


@dataclass(frozen=True)
class _PendingJob:
    urlsafe_key: str
    status_revision: int = 0


def _target_key(target: Entity | str) -> str:
    return target if isinstance(target, str) else target.urlsafe_key


AUTOFILL_FORM_LOCK_SCOPE = Scope.AUTOFILL_FORM


def deferred_job_lock_key(target: Entity | str, scope: str = AUTOFILL_FORM_LOCK_SCOPE) -> Key | None:
    """Return the deterministic lock key for one target mutation surface."""
    identifier = Scope.identifier(target, scope)
    return database_utility.create_named_key("job_lock", identifier) if identifier else None


def active_deferred_job_lock(target: Entity | str | None, scope: str = AUTOFILL_FORM_LOCK_SCOPE) -> ActiveLock | None:
    """Return ``(lock, job)`` while the target's referenced job is active."""
    if target is None:
        return None
    target_key = _target_key(target)
    return deferred_job_lock_descriptors([target], scope=scope).get(target_key)


def deferred_job_lock_descriptors(targets: Iterable[Entity | str | None] | None, scope: str = AUTOFILL_FORM_LOCK_SCOPE) -> dict[str, ActiveLock]:
    """Batch-resolve active locks keyed by target urlsafe key."""
    targets = [target for target in targets or () if target]
    target_keys = [_target_key(target) for target in targets]
    lock_keys = [deferred_job_lock_key(target, scope) for target in targets]
    form_keys = {
        getattr(target, "db", {}).get("form")
        for target in targets
        if scope == AUTOFILL_FORM_LOCK_SCOPE
        and getattr(target, "entity_kind", None) in {"page", "task"}
    } - {None}
    # Lock fields and pending Form changes are stored on the roots. Read both
    # fresh in one lookup; neither needs its relations to find the job.
    roots = Entities.fetch(*lock_keys, *form_keys, request=Fetch.root())
    locks = {
        lock.target: lock
        for lock in roots
        if isinstance(lock, Entities.DEFERRED_JOB_LOCK) and lock.operation
    }
    jobs = {
        job.urlsafe_key: job
        for job in Entities.fetch(
            *(lock.operation for lock in locks.values()), request=Fetch.direct()
        )
        if isinstance(job, Entities.DEFERRED_JOB)
    }
    active: dict[str, ActiveLock] = {}
    for target_key in target_keys:
        lock = locks.get(target_key)
        job = jobs.get(lock.operation) if lock and lock.operation else None
        if lock and job and job.status in ACTIVE_STATUSES:
            active[target_key] = (cast(LockView, lock), job)
        elif lock:
            database_deferred_jobs.release_deferred_job_lock(lock.key, lock.operation)
    if scope == AUTOFILL_FORM_LOCK_SCOPE:
        from ..forms.contracts import PENDING, pending_change

        pending: dict[Key, str] = {}
        for form in roots:
            if form.key is None or form.key not in form_keys or not form.db.get(PENDING):
                continue
            change = pending_change(form.db)
            job_id = change.get("job") if change else None
            if not job_id:
                raise ValidationError("Saved form change data needs repair.")
            pending[form.key] = job_id
        pending_jobs = {
            job.urlsafe_key: job
            for job in Entities.fetch(*pending.values(), request=Fetch.direct())
        } if pending else {}
        for target in targets:
            form_key = getattr(target, "db", {}).get("form")
            if form_key is not None and (job_id := pending.get(form_key)):
                job = pending_jobs.get(job_id) or _PendingJob(urlsafe_key=job_id)
                active[_target_key(target)] = (_PendingLock(Scope.FORM_CHANGE), cast(LockJobView, job))
    return active


def deferred_job_lock_descriptor(target: Entity | str, scope: str = AUTOFILL_FORM_LOCK_SCOPE) -> dict[str, object] | None:
    """Return the browser-safe active-operation descriptor for ``target``."""
    active = active_deferred_job_lock(target, scope)
    return Operation.descriptor(*active) if active is not None else None
