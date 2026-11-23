"""Notification aggregate, ordinary-record, and query persistence."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key
from google.cloud.datastore.transaction import Transaction

from ...properties import notification_aggregate
from ..files.html import strip_tags
from .core import DATA, KINDS
from .filter import Filter, Query, Results
from .get import datastore_key
from .transactions import retry_aborted
from .utility import create_named_key, stored_key

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity as DomainEntity
    from lagniappe.core.entities.user import User

    from .get import Identifier


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::repair_notification_aggregate
# @reason deterministic key construction is asserted through aggregate repair
def aggregate_key(user: User) -> Key:
    parent = getattr(user, "key", user)
    return create_named_key(
        "notification", notification_aggregate.AGGREGATE_ID, parent=parent
    )


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::repair_notification_aggregate
# @reason exact aggregate defaults are asserted through repair
def new_aggregate(
    key: Key, *, ordinary_count: int = 0, unread_message_count: int = 0
) -> DatastoreEntity:
    parent = key.parent
    if parent is None:
        raise ValueError("A notification aggregate must have a parent user key.")
    row = DatastoreEntity(key=key)
    row.update(
        notification_aggregate.initial_values(
            parent,
            ordinary_count=ordinary_count,
            unread_message_count=unread_message_count,
        )
    )
    return row


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::ensure_notification_aggregate
# @reason deterministic lookup is exercised through ensure
def get_notification_aggregate(user: User) -> DatastoreEntity | None:
    return DATA.datastore.get(aggregate_key(user))


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::repair_notification_aggregate
# @reason legacy ancestor counting is an internal cold-repair fallback
def _ordinary_count(user):
    rows = (
        Query(KINDS.activity, ancestor=getattr(user, "key", user))
        .filter(Filter().eq("type", "notification"))
        .fetch_all()
    )
    return sum(
        1
        for row in rows
        if row.get("notification_type", "ordinary") == "ordinary"
    )


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-repair idempotency
@retry_aborted
def repair_notification_aggregate(
    user: User, *, ordinary_count: int | None = None
) -> DatastoreEntity:
    key = aggregate_key(user)
    existing = DATA.datastore.get(key)
    if existing is not None:
        return existing
    if ordinary_count is None:
        ordinary_count = _ordinary_count(user)
    candidate = new_aggregate(key, ordinary_count=ordinary_count)
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(key, transaction=transaction)
        if current is not None:
            return current
        transaction.put(candidate)
    return candidate


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @pair notifications:aggregate-repair
def ensure_notification_aggregate(user: User) -> DatastoreEntity:
    return get_notification_aggregate(user) or repair_notification_aggregate(user)


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-count revision
def mutate_notification_aggregate(
    transaction: Transaction,
    user: User,
    *,
    ordinary_delta: int = 0,
    message_delta: int = 0,
) -> DatastoreEntity:
    key = aggregate_key(user)
    row = DATA.datastore.get(key, transaction=transaction)
    if row is None:
        raise RuntimeError("Notification aggregate must be repaired before mutation.")
    notification_aggregate.apply_deltas(
        row,
        ordinary_delta=ordinary_delta,
        message_delta=message_delta,
    )
    transaction.put(row)
    return row


# @testable false
# @covered-by lagniappe/core/tools/notifications/service.py::apply_ordinary_mutations
# @reason single-row transaction wrapper is exercised through ordinary mutation projection
@retry_aborted
def change_notification_aggregate(
    user: User, *, ordinary_delta: int = 0, message_delta: int = 0
) -> DatastoreEntity:
    ensure_notification_aggregate(user)
    with DATA.datastore.transaction() as transaction:
        return mutate_notification_aggregate(
            transaction,
            user,
            ordinary_delta=ordinary_delta,
            message_delta=message_delta,
        )


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::create_ordinary_notification_record
# @reason deterministic key construction is asserted through idempotent creation
def ordinary_notification_key(user: User, identifier: str) -> Key:
    return create_named_key("notification", identifier, parent=user)


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : body html-stripping
def prepare_ordinary_notification(
    key: Key, user: User, *, body: str, target: DomainEntity | None = None
) -> DatastoreEntity:
    now = datetime.now(UTC)
    row = DatastoreEntity(key=key, exclude_from_indexes=("body",))
    row.update(
        {
            "type": "notification",
            "kind": "notification",
            "notification_type": "ordinary",
            "parent": user.key,
            "target": getattr(target, "key", target),
            "body": strip_tags(body).strip() if body else None,
            "pending": False,
            "created": now,
            "modified": now,
        }
    )
    return row


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-count idempotency ordinary-create
@retry_aborted
def create_ordinary_notification_record(
    user: User, *, identifier: str, body: str, target: DomainEntity | None = None
) -> tuple[DatastoreEntity, bool, DatastoreEntity | None]:
    ensure_notification_aggregate(user)
    key = ordinary_notification_key(user, identifier)
    created = False
    aggregate = None
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(key, transaction=transaction)
        if row is None:
            row = prepare_ordinary_notification(key, user, body=body, target=target)
            aggregate = mutate_notification_aggregate(
                transaction, user, ordinary_delta=1
            )
            transaction.put(row)
            created = True
    return row, created, aggregate


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-count ordinary-delete
@retry_aborted
def delete_ordinary_notification_record(
    user: User, notification_key: Key
) -> tuple[bool, DatastoreEntity | None]:
    ensure_notification_aggregate(user)
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(notification_key, transaction=transaction)
        if row is None:
            return False, None
        if (
            stored_key(row).parent != user.key
            or row.get("notification_type", "ordinary") != "ordinary"
        ):
            raise PermissionError("Notification cannot be deleted.")
        transaction.delete(row.key)
        aggregate = mutate_notification_aggregate(
            transaction, user, ordinary_delta=-1
        )
    return True, aggregate


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-count ordinary-clear
@retry_aborted
def clear_ordinary_notification_records(
    user: User, keys: Iterable[Key]
) -> tuple[int, DatastoreEntity | None]:
    ensure_notification_aggregate(user)
    keys = list(dict.fromkeys(keys or ()))
    aggregate = None
    with DATA.datastore.transaction() as transaction:
        rows = DATA.datastore.get_multi(keys, transaction=transaction) if keys else []
        ordinary = [
            row
            for row in rows
            if row
            and stored_key(row).parent == user.key
            and row.get("notification_type", "ordinary") == "ordinary"
        ]
        for row in ordinary:
            transaction.delete(row.key)
        if ordinary:
            aggregate = mutate_notification_aggregate(
                transaction, user, ordinary_delta=-len(ordinary)
            )
    return len(ordinary), aggregate


# @testable true
# @tests tests_unit/test_002j_notes.py::test_notification_keys_query_returns_only_ancestor_keys
# @matrix notifications : cold-seed keys-only
def notification_keys(parent: Identifier) -> list[Key]:
    parent_key = datastore_key(parent)
    if not parent_key:
        return []
    records = (
        Query(KINDS.activity)
        .ancestor(parent_key)
        .filter(
            Filter().eq("type", "notification").eq("notification_type", "ordinary")
        )
        .keys_only()
        .fetch_all()
    )
    return [stored_key(record) for record in records]


# @testable true
# @tests tests_unit/test_002j_notes.py::test_notification_page_is_bounded_and_excludes_aggregate_rows
# @matrix notifications : bounded-page cursor ordinary-discriminator
def notifications_page(
    parent: Identifier, start_cursor: str | None = None, limit: int = 25
) -> Results[DatastoreEntity]:
    parent_key = datastore_key(parent)
    if not parent_key:
        from .get import _empty_results

        return _empty_results()
    return (
        Query(KINDS.activity)
        .ancestor(parent_key)
        .filter(
            Filter().eq("type", "notification").eq("notification_type", "ordinary")
        )
        .order("-created")
        .limit(limit)
        .cursor(start_cursor)
        .fetch()
    )
