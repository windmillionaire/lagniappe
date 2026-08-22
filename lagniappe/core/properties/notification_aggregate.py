"""Durable notification aggregate values and pure state projection."""

from datetime import datetime, timezone
import uuid

from .base_db import DBProperty


AGGREGATE_ID = "message-aggregate"


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @pair notifications:aggregate-repair
def initial_values(parent, *, ordinary_count=0, unread_message_count=0, now=None):
    now = now or datetime.now(timezone.utc)
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


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair notifications:aggregate-count
def counts(row):
    row = row or {}
    ordinary = max(0, int(row.get("ordinary_count") or 0))
    messages = max(0, int(row.get("unread_message_count") or 0))
    return {
        "ordinary_count": ordinary,
        "unread_message_count": messages,
        "count": ordinary + messages,
        "revision": int(row.get("aggregate_revision") or 0),
        "message_revision": int(row.get("message_revision") or 0),
        "generation": row.get("aggregate_generation"),
    }


# @testable true
# @tests tests_unit/test_027e_notifications.py::test_ordinary_notification_service_mutates_aggregate_once
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pairs notifications:ordinary-count notifications:aggregate-count notifications:revision
def apply_deltas(row, *, ordinary_delta=0, message_delta=0, now=None):
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
    row["modified"] = now or datetime.now(timezone.utc)
    return row


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:aggregate-count
class OrdinaryCount(DBProperty):
    _id = "ordinary_count"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:aggregate-count
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:aggregate-count
class UnreadMessageCount(DBProperty):
    _id = "unread_message_count"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:aggregate-count
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:revision
class AggregateRevision(DBProperty):
    _id = "aggregate_revision"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:revision
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:revision
class MessageRevision(DBProperty):
    _id = "message_revision"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:revision
    @property
    def value(self):
        return int(super().value or 0)

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
# @pair notifications:generation
class AggregateGeneration(DBProperty):
    _id = "aggregate_generation"

    # @testable true
    # @tests tests_unit/test_027a_messaging_properties.py::test_messaging_entities_and_owner_toggles_are_fail_closed
    # @pair notifications:generation
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)
