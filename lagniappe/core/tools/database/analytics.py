"""Datastore persistence for analytics and AI observability records."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from google.cloud.datastore import Entity
from google.cloud.datastore import query as datastore_query

from config.datastore import encode_urlsafe_key

from .core import DATA, KINDS


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_save_event
# @reason event persistence is exercised through the route-owned write boundary
def create_event(data: Mapping[str, object]) -> Entity:
    """Persist one application analytics event."""
    key = DATA.datastore.allocate_ids(DATA.datastore.key(KINDS.analytics.value), 1)[0]
    event = DATA.datastore.entity(key=key)
    event.update({"urlsafe_key": encode_urlsafe_key(key), **data})
    DATA.datastore.put(event)
    return event


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_events
# @reason event queries are exercised through the owner analytics dashboard
def events(*, start: datetime | None = None, limit: int = 1000) -> list[Entity]:
    """Fetch analytics events newest first, optionally within a time window."""
    query = DATA.datastore.query(kind=KINDS.analytics.value)
    if start is not None:
        query.add_filter(
            filter=datastore_query.PropertyFilter("created", ">=", start)
        )
    query.order = ["-created"]
    return list(query.fetch(limit=limit))


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::_write_summary
# @reason summary persistence is exercised through the typed observability boundary
def create_ai_observability(
    identifier: str,
    payload: Mapping[str, object],
    *,
    exclude_from_indexes: Sequence[str] = (),
) -> Entity:
    """Persist one privacy-bounded AI observability summary."""
    key = DATA.datastore.key(KINDS.ai_observability.value, identifier)
    entity = DATA.datastore.entity(
        key=key,
        exclude_from_indexes=exclude_from_indexes,
    )
    entity.update(payload)
    DATA.datastore.put(entity)
    return entity


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_ai_records
# @reason summary queries are exercised through the owner analytics dashboard
def ai_observability_records(
    *, start: datetime | None = None, limit: int = 1000
) -> list[Entity]:
    """Fetch AI observability summaries newest first."""
    query = DATA.datastore.query(kind=KINDS.ai_observability.value)
    if start is not None:
        query.add_filter(
            filter=datastore_query.PropertyFilter("created", ">=", start)
        )
    query.order = ["-created"]
    return list(query.fetch(limit=limit))


# @testable false
# @covered-by lagniappe/web/routes/analytics/main.py::_delete_events
# @reason event cleanup is exercised through the analytics retention route
def delete_events(*, before: datetime | None = None, batch_size: int = 500) -> int:
    """Delete analytics events in bounded key-only batches."""
    return _delete_records(KINDS.analytics, before=before, batch_size=batch_size)


# @testable false
# @covered-by lagniappe/core/tools/ai/observability.py::prune_old_records
# @covered-by lagniappe/web/routes/analytics/main.py::_delete_ai_records
# @reason summary cleanup is exercised through retention and owner-clear workflows
def delete_ai_observability(
    *, before: datetime | None = None, batch_size: int = 500, once: bool = False
) -> int:
    """Delete AI observability summaries in bounded key-only batches."""
    return _delete_records(
        KINDS.ai_observability,
        before=before,
        batch_size=batch_size,
        once=once,
    )


# @testable false
# @covered-by lagniappe/core/tools/database/analytics.py::delete_events
# @covered-by lagniappe/core/tools/database/analytics.py::delete_ai_observability
# @reason bounded deletion mechanics are owned by the dataset-specific entry points
def _delete_records(kind, *, before, batch_size, once=False):
    batch_size = max(int(batch_size), 1)
    deleted = 0
    while True:
        query = DATA.datastore.query(kind=kind.value)
        if before is not None:
            query.add_filter(
                filter=datastore_query.PropertyFilter("created", "<", before)
            )
            query.order = ["created"]
        query.keys_only()
        keys = [record.key for record in query.fetch(limit=batch_size)]
        if not keys:
            return deleted
        DATA.datastore.delete_multi(keys)
        deleted += len(keys)
        if once or len(keys) < batch_size:
            return deleted
