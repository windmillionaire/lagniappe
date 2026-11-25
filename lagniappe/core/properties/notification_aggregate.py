"""Durable notification aggregate values and pure state projection."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from google.cloud.datastore import Entity as DatastoreEntity
    from google.cloud.datastore import Key
    from lagniappe.core.entities.entity import Entity


from datetime import datetime, UTC
import uuid

from .base_db import DBProperty


class NotificationCounts(TypedDict):
    ordinary_count: int
    unread_message_count: int
    count: int
    revision: int
    message_revision: int
    generation: str | None


AGGREGATE_ID = "message-aggregate"


def initial_values(parent: Entity | Key, *, ordinary_count: int = 0, unread_message_count: int = 0, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now(UTC)
    return {
        "type": "notification",
        "kind": "notification",
        "notification_type": "aggregate",
        "parent": getattr(parent, "key", parent),
        "ordinary_count": max(0, int(ordinary_count)),
        "unread_message_count": max(0, int(unread_message_count)),
        "aggregate_revision": 0,
        "message_revision": 0,
        "aggregate_generation": str(uuid.uuid4()),
        "created": now,
        "modified": now,
    }


def counts(row: DatastoreEntity | None) -> NotificationCounts:
    values = row or {}
    ordinary = max(0, int(values.get("ordinary_count") or 0))
    messages = max(0, int(values.get("unread_message_count") or 0))
    return {
        "ordinary_count": ordinary,
        "unread_message_count": messages,
        "count": ordinary + messages,
        "revision": int(values.get("aggregate_revision") or 0),
        "message_revision": int(values.get("message_revision") or 0),
        "generation": values.get("aggregate_generation"),
    }


def apply_deltas(row: DatastoreEntity, *, ordinary_delta: int = 0, message_delta: int = 0, now: datetime | None = None) -> DatastoreEntity:
    row["ordinary_count"] = max(
        0, int(row.get("ordinary_count") or 0) + int(ordinary_delta)
    )
    row["unread_message_count"] = max(
        0, int(row.get("unread_message_count") or 0) + int(message_delta)
    )
    row["aggregate_revision"] = int(row.get("aggregate_revision") or 0) + 1
    if int(message_delta) > 0:
        row["message_revision"] = int(row.get("message_revision") or 0) + 1
    row["aggregate_generation"] = row.get("aggregate_generation") or str(uuid.uuid4())
    row["modified"] = now or datetime.now(UTC)
    return row


class OrdinaryCount(DBProperty[int]):
    _id = "ordinary_count"

    @property
    def value(self) -> int:
        return int(super().value or 0)

    @value.setter
    def value(self, value: int | None) -> None:
        self._write_db_value(value)


class UnreadMessageCount(DBProperty[int]):
    _id = "unread_message_count"

    @property
    def value(self) -> int:
        return int(super().value or 0)

    @value.setter
    def value(self, value: int | None) -> None:
        self._write_db_value(value)


class AggregateRevision(DBProperty[int]):
    _id = "aggregate_revision"

    @property
    def value(self) -> int:
        return int(super().value or 0)

    @value.setter
    def value(self, value: int | None) -> None:
        self._write_db_value(value)


class MessageRevision(DBProperty[int]):
    _id = "message_revision"

    @property
    def value(self) -> int:
        return int(super().value or 0)

    @value.setter
    def value(self, value: int | None) -> None:
        self._write_db_value(value)


class AggregateGeneration(DBProperty[str]):
    _id = "aggregate_generation"

    @property
    def value(self) -> str | None:
        return super().value

    @value.setter
    def value(self, value: str | None) -> None:
        self._write_db_value(value)
