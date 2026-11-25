"""Datastore persistence for analytics and AI observability records."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from google.cloud.datastore import Entity
from google.cloud.datastore import query as datastore_query

from config.datastore import encode_urlsafe_key

from .core import DATA, KINDS


def create_event(data: Mapping[str, object]) -> Entity:
    """Persist one application analytics event."""
    key = DATA.datastore.allocate_ids(DATA.datastore.key(KINDS.analytics.value), 1)[0]
    event = DATA.datastore.entity(key=key)
    event.update({"urlsafe_key": encode_urlsafe_key(key), **data})
    DATA.datastore.put(event)
    return event


def events(*, start: datetime | None = None, limit: int = 1000) -> list[Entity]:
    """Fetch analytics events newest first, optionally within a time window."""
    query = DATA.datastore.query(kind=KINDS.analytics.value)
    if start is not None:
        query.add_filter(
            filter=datastore_query.PropertyFilter("created", ">=", start)
        )
    query.order = ["-created"]
    return list(query.fetch(limit=limit))


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


def delete_events(*, before: datetime | None = None, batch_size: int = 500) -> int:
    """Delete analytics events in bounded key-only batches."""
    return _delete_records(KINDS.analytics, before=before, batch_size=batch_size)


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
