"""Notification orchestration above durable records and provider effects."""

from collections import defaultdict

from ...properties import notification_aggregate
from .. import database


# @testable false
# @covered-by lagniappe/core/properties/notification_aggregate.py::counts
# @reason thin service spelling preserves an explicit value/service boundary
def aggregate_counts(row):
    return notification_aggregate.counts(row)


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @pair notifications:cache-failure-isolation
def publish_notification_aggregate(user, aggregate):
    """Best-effort Redis mirroring after a durable aggregate commit."""
    if aggregate is None:
        return None
    try:
        from .. import cache

        return cache.publish_notification_aggregate(user, aggregate)
    except Exception as error:
        from ...exceptions import capture

        capture(error, context={"operation": "notification-aggregate-publish"})
        return None


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : idempotency ordinary-count revision
def apply_ordinary_mutations(*, upserts=(), deletes=()):
    """Advance durable aggregate rows for committed entity mutations."""
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
        existing = database.get_notification_aggregate(user)
        aggregate = (
            database.change_notification_aggregate(user, ordinary_delta=delta)
            if existing is not None
            else database.repair_notification_aggregate(user)
        )
        aggregates[user_id] = aggregate
    return aggregates


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-count idempotency ordinary-create
def create_ordinary_notification(user, *, identifier, body, target=None):
    from ...definitions import Fetch
    from ...entities import Entities

    row, created, _aggregate = database.create_ordinary_notification_record(
        user,
        identifier=identifier,
        body=body,
        target=target,
    )
    notification = Entities.fetch_one(row, request=Fetch.direct())
    if created:
        try:
            from ..email.notifications import capture as email_capture

            email_capture.record_notification_event(
                user,
                row.key,
                body=row.get("body") or body,
                target=target,
                now=row.get("created"),
            )
        except Exception as error:
            from ...exceptions import capture

            capture(error, context={"operation": "notification-email-capture"})
    return notification, created


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-count ordinary-delete
def delete_ordinary_notification(user, notification_key):
    deleted, _aggregate = database.delete_ordinary_notification_record(
        user, notification_key
    )
    return deleted


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @matrix notifications : aggregate-count ordinary-clear
def clear_ordinary_notifications(user, keys):
    cleared, _aggregate = database.clear_ordinary_notification_records(user, keys)
    return cleared


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_process_notification_requires_a_valid_user
# @matrix notifications : body create task-queue
def create_process_notification(payload, body):
    """Create a notification for the valid user named by a process payload."""
    from ...definitions import Fetch
    from ...entities import Entities

    user_key = payload.get("user_key")
    if not user_key:
        return None
    user = Entities.fetch_one(user_key, request=Fetch.direct())
    if not user or user.kind != "user":
        return None
    notification = Entities.NOTIFICATION.create({"parent": user, "body": body})
    Entities.save(notification)
    return notification
