"""Notification aggregate, ordinary-record, and query persistence."""

from datetime import datetime, timezone

from google.cloud.datastore import Entity as DatastoreEntity

from ...properties import notification_aggregate
from .core import DATA, KINDS
from .filter import Filter, Query
from .get import datastore_key
from .transactions import retry_aborted
from .utility import create_named_key


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::repair_notification_aggregate
# @reason deterministic key construction is asserted through aggregate repair
def aggregate_key(user):
    parent = getattr(user, "key", user)
    return create_named_key(
        "notification", notification_aggregate.AGGREGATE_ID, parent=parent
    )


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::repair_notification_aggregate
# @reason exact aggregate defaults are asserted through repair
def new_aggregate(key, *, ordinary_count=0, unread_message_count=0):
    row = DatastoreEntity(key=key)
    row.update(
        notification_aggregate.initial_values(
            key.parent,
            ordinary_count=ordinary_count,
            unread_message_count=unread_message_count,
        )
    )
    return row


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::ensure_notification_aggregate
# @reason deterministic lookup is exercised through ensure
def get_notification_aggregate(user):
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
# @pairs notifications:aggregate-repair notifications:idempotency
@retry_aborted
def repair_notification_aggregate(user, *, ordinary_count=None):
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
def ensure_notification_aggregate(user):
    return get_notification_aggregate(user) or repair_notification_aggregate(user)


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @pairs notifications:aggregate-count notifications:revision
def mutate_notification_aggregate(
    transaction,
    user,
    *,
    ordinary_delta=0,
    message_delta=0,
):
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
def change_notification_aggregate(user, *, ordinary_delta=0, message_delta=0):
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
def ordinary_notification_key(user, identifier):
    return create_named_key("notification", identifier, parent=user)


# @testable false
# @covered-by lagniappe/core/tools/database/notifications.py::create_ordinary_notification_record
# @reason raw row construction is exercised through ordinary notification creation
def prepare_ordinary_notification(key, user, *, body, target=None):
    now = datetime.now(timezone.utc)
    row = DatastoreEntity(key=key, exclude_from_indexes=("body",))
    row.update(
        {
            "type": "notification",
            "kind": "notification",
            "notification_type": "ordinary",
            "parent": user.key,
            "target": getattr(target, "key", target),
            "body": body,
            "pending": False,
            "created": now,
            "modified": now,
        }
    )
    return row


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @pairs notifications:ordinary-create notifications:idempotency notifications:aggregate-count
@retry_aborted
def create_ordinary_notification_record(user, *, identifier, body, target=None):
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
# @pairs notifications:ordinary-delete notifications:aggregate-count
@retry_aborted
def delete_ordinary_notification_record(user, notification_key):
    ensure_notification_aggregate(user)
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(notification_key, transaction=transaction)
        if row is None:
            return False, None
        if (
            row.key.parent != user.key
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
# @pairs notifications:ordinary-clear notifications:aggregate-count
@retry_aborted
def clear_ordinary_notification_records(user, keys):
    ensure_notification_aggregate(user)
    keys = list(dict.fromkeys(keys or ()))
    aggregate = None
    with DATA.datastore.transaction() as transaction:
        rows = DATA.datastore.get_multi(keys, transaction=transaction) if keys else []
        ordinary = [
            row
            for row in rows
            if row
            and row.key.parent == user.key
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
# @pairs notifications:cold-seed notifications:keys-only
def notification_keys(parent):
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
    return [record.key for record in records]


# @testable true
# @tests tests_unit/test_002j_notes.py::test_notification_page_is_bounded_and_excludes_aggregate_rows
# @pairs notifications:bounded-page notifications:ordinary-discriminator notifications:cursor
def notifications_page(parent, start_cursor=None, limit=25):
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
