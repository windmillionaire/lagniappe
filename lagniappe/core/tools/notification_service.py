"""Canonical durable notification aggregate operations."""

from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps
import time
import uuid

from google.api_core import exceptions as google_exceptions
from google.cloud.datastore import Entity as DatastoreEntity

from .database.core import DATA, KINDS
from .database.filter import Filter, Query
from . import database


AGGREGATE_ID = "message-aggregate"
TRANSACTION_RETRY_DELAYS = (0.05, 0.1, 0.2)


# @testable true
# @tests tests_unit/test_027_messaging.py::test_ordinary_notification_service_mutates_aggregate_once
# @pair notifications:transaction-retry
def retry_transaction(operation):
    # @testable false
    # @covered-by lagniappe/core/tools/notification_service.py::retry_transaction
    # @reason generated decorator wrapper is exercised through the public retry decorator
    @wraps(operation)
    def retried(*args, **kwargs):
        for attempt in range(len(TRANSACTION_RETRY_DELAYS) + 1):
            try:
                return operation(*args, **kwargs)
            except google_exceptions.Aborted:
                if attempt >= len(TRANSACTION_RETRY_DELAYS):
                    raise
                time.sleep(TRANSACTION_RETRY_DELAYS[attempt])

    return retried


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::ensure_notification_aggregate
# @reason deterministic key construction is asserted through aggregate repair and reuse
def aggregate_key(user):
    parent = getattr(user, "key", user)
    return database.create_named_key("notification", AGGREGATE_ID, parent=parent)


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::repair_notification_aggregate
# @reason aggregate defaults are asserted through the public repair boundary
def _new_aggregate(key, *, ordinary_count=0, unread_message_count=0):
    row = DatastoreEntity(key=key)
    now = datetime.now(timezone.utc)
    row.update(
        {
            "type": "notification",
            "kind": "notification",
            "notification_type": "aggregate",
            "parent": key.parent,
            "ordinary_count": max(0, int(ordinary_count)),
            "unread_message_count": max(0, int(unread_message_count)),
            "aggregate_revision": 0,
            "aggregate_generation": str(uuid.uuid4()),
            "created": now,
            "modified": now,
        }
    )
    return row


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair notifications:aggregate-count
def aggregate_counts(row):
    row = row or {}
    ordinary = max(0, int(row.get("ordinary_count") or 0))
    messages = max(0, int(row.get("unread_message_count") or 0))
    return {
        "ordinary_count": ordinary,
        "unread_message_count": messages,
        "count": ordinary + messages,
        "revision": int(row.get("aggregate_revision") or 0),
        "generation": row.get("aggregate_generation"),
    }


# @testable true
# @tests tests_unit/test_027_messaging.py::test_ordinary_notification_service_mutates_aggregate_once
# @pair notifications:cache-failure-isolation
def publish_notification_aggregate(user, aggregate):
    """Best-effort Redis mirroring after a durable aggregate commit."""
    if aggregate is None:
        return None
    try:
        from . import cache

        return cache.publish_notification_aggregate(user, aggregate)
    except Exception as error:
        from ..exceptions import capture

        capture(
            error,
            context={"operation": "notification-aggregate-publish"},
        )
        return None


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::ensure_notification_aggregate
# @reason deterministic lookup is exercised through ensure and repair coverage
def get_notification_aggregate(user):
    return DATA.datastore.get(aggregate_key(user))


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::repair_notification_aggregate
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
# @tests tests_unit/test_027_messaging.py::test_ordinary_notification_service_mutates_aggregate_once
# @pairs notifications:aggregate-repair notifications:idempotency
@retry_transaction
def repair_notification_aggregate(user, *, ordinary_count=None):
    """Create the deterministic zero-capable row, without overwriting one."""
    key = aggregate_key(user)
    existing = DATA.datastore.get(key)
    if existing is not None:
        return existing
    if ordinary_count is None:
        ordinary_count = _ordinary_count(user)
    candidate = _new_aggregate(key, ordinary_count=ordinary_count)
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(key, transaction=transaction)
        if current is not None:
            return current
        transaction.put(candidate)
    return candidate


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::repair_notification_aggregate
# @reason get-or-repair selection is asserted through aggregate repair coverage
def ensure_notification_aggregate(user):
    return get_notification_aggregate(user) or repair_notification_aggregate(user)


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::mutate_aggregate_in_transaction
# @reason counter clamping and revision advancement are asserted through transactional mutations
def _mutate_aggregate(row, *, ordinary_delta=0, message_delta=0):
    row["ordinary_count"] = max(
        0, int(row.get("ordinary_count") or 0) + int(ordinary_delta)
    )
    row["unread_message_count"] = max(
        0, int(row.get("unread_message_count") or 0) + int(message_delta)
    )
    row["aggregate_revision"] = int(row.get("aggregate_revision") or 0) + 1
    row["aggregate_generation"] = row.get("aggregate_generation") or str(uuid.uuid4())
    row["modified"] = datetime.now(timezone.utc)
    return row


# @testable true
# @tests tests_unit/test_027_messaging.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pairs notifications:aggregate-count notifications:revision
def mutate_aggregate_in_transaction(
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
    _mutate_aggregate(
        row,
        ordinary_delta=ordinary_delta,
        message_delta=message_delta,
    )
    transaction.put(row)
    return row


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::apply_ordinary_mutations
# @reason single-row transaction wrapper is exercised through ordinary mutation projection
@retry_transaction
def change_aggregate(user, *, ordinary_delta=0, message_delta=0):
    ensure_notification_aggregate(user)
    with DATA.datastore.transaction() as transaction:
        row = mutate_aggregate_in_transaction(
            transaction,
            user,
            ordinary_delta=ordinary_delta,
            message_delta=message_delta,
        )
    return row


# @testable true
# @tests tests_unit/test_027_messaging.py::test_ordinary_notification_service_mutates_aggregate_once
# @pairs notifications:ordinary-count notifications:revision notifications:idempotency
def apply_ordinary_mutations(*, upserts=(), deletes=()):
    """Advance durable aggregate rows for committed legacy entity mutations."""
    deltas = defaultdict(int)
    users = {}
    for notification in (*tuple(upserts), *tuple(deletes)):
        delta = int(getattr(notification, "_notification_count_delta", 0) or 0)
        parent = getattr(notification, "parent", None)
        if (
            not parent
            or getattr(notification, "notification_type", "ordinary") != "ordinary"
        ):
            continue
        users[parent.urlsafe_key] = parent
        deltas[parent.urlsafe_key] += delta

    aggregates = {}
    for user_id, delta in deltas.items():
        user = users[user_id]
        existing = get_notification_aggregate(user)
        aggregate = (
            change_aggregate(user, ordinary_delta=delta)
            if existing is not None
            else repair_notification_aggregate(user)
        )
        aggregates[user_id] = aggregate
    return aggregates


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::create_ordinary_notification
# @reason deterministic key construction is asserted through idempotent ordinary create
def ordinary_notification_key(user, identifier):
    return database.create_named_key("notification", identifier, parent=user)


# @testable false
# @covered-by lagniappe/core/tools/notification_service.py::create_ordinary_notification
# @reason row construction is exercised through ordinary create coverage
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
# @tests tests_unit/test_027_messaging.py::test_ordinary_notification_service_mutates_aggregate_once
# @pairs notifications:ordinary-create notifications:idempotency notifications:aggregate-count
@retry_transaction
def create_ordinary_notification(user, *, identifier, body, target=None):
    """Idempotently create an ordinary notification and count it atomically."""
    ensure_notification_aggregate(user)
    key = ordinary_notification_key(user, identifier)
    created = False
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(key, transaction=transaction)
        if row is None:
            row = prepare_ordinary_notification(key, user, body=body, target=target)
            mutate_aggregate_in_transaction(transaction, user, ordinary_delta=1)
            transaction.put(row)
            created = True
    from ..definitions import Fetch
    from ..entities import Entities

    notification = Entities.fetch_one(row, request=Fetch.direct())
    if created:
        try:
            from . import notification_email

            notification_email.record_notification_event(
                user,
                row.key,
                body=row.get("body") or body,
                target=notification.target or target,
                now=row.get("created"),
            )
        except Exception as error:
            from ..exceptions import capture

            capture(error, context={"operation": "notification-email-capture"})
    return notification, created


# @testable true
# @tests tests_unit/test_027_messaging.py::test_ordinary_notification_service_mutates_aggregate_once
# @pairs notifications:ordinary-delete notifications:aggregate-count
@retry_transaction
def delete_ordinary_notification(user, notification_key):
    ensure_notification_aggregate(user)
    with DATA.datastore.transaction() as transaction:
        row = DATA.datastore.get(notification_key, transaction=transaction)
        if row is None:
            return False
        if (
            row.key.parent != user.key
            or row.get("notification_type", "ordinary") != "ordinary"
        ):
            raise PermissionError("Notification cannot be deleted.")
        transaction.delete(row.key)
        mutate_aggregate_in_transaction(transaction, user, ordinary_delta=-1)
    return True


# @testable true
# @tests tests_unit/test_027_messaging.py::test_ordinary_notification_service_mutates_aggregate_once
# @pairs notifications:ordinary-clear notifications:aggregate-count
@retry_transaction
def clear_ordinary_notifications(user, keys):
    """Delete exactly the supplied ordinary keys and repair the durable count."""
    ensure_notification_aggregate(user)
    keys = list(dict.fromkeys(keys or ()))
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
            mutate_aggregate_in_transaction(
                transaction, user, ordinary_delta=-len(ordinary)
            )
    return len(ordinary)
