"""Durable target-scoped ownership for a deferred operation."""

from typing import TYPE_CHECKING


from .entity import Entity
from ..properties import deferred_job_lock


if TYPE_CHECKING:
    from . import property_types
    from .entity import EntityProperties


# @testable infrastructure
class DeferredJobLock(Entity):
    """Small deterministic record coupling a target form to one active job."""
    if TYPE_CHECKING:
        scope: str | None
        operation: str | None

        @property
        def properties(self) -> property_types.DeferredJobLockProperties: ...


    entity_kind = "job_lock"

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset(
            {
                "target",
                "operation",
                "idempotency_key",
                "scope",
            }
        )

    @property
    def to_cache(self) -> dict[str, object]:
        return {}

    @property
    def required(self) -> list[str]:
        return []

    def _get_properties(self) -> EntityProperties:
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
