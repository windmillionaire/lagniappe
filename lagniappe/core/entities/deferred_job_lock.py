"""Durable target-scoped ownership for a deferred operation."""

from .entity import Entity
from ..properties import deferred_job_lock


# @testable infrastructure
class DeferredJobLock(Entity):
    """Small deterministic record coupling a target form to one active job."""

    entity_kind = "job_lock"

    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "target",
                "operation",
                "idempotency_key",
                "scope",
            }
        )

    @property
    def to_cache(self):
        return {}

    @property
    def required(self):
        return []

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "target": deferred_job_lock.Target,
                "operation": deferred_job_lock.Operation,
                "idempotency_key": deferred_job_lock.IdempotencyKey,
                "scope": deferred_job_lock.Scope,
            }
        )
        return properties

    @classmethod
    def create(cls, data):
        lock = cls(data["key"])
        lock.kind = cls.entity_kind
        lock.name = data.get("name") or data.get("scope") or "deferred-job-lock"
        lock.target = data["target"]
        lock.operation = data["operation"]
        lock.idempotency_key = data["idempotency_key"]
        lock.scope = data["scope"]
        return lock
