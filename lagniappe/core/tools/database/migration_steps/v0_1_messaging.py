"""Canonical notification discriminator transform for messaging aggregates."""

from .base import MigrationChange


# @testable true
# @tests tests_unit/test_027_messaging.py::test_notification_discriminator_migration_is_idempotent
# @pairs migrations:notification-discriminator migrations:idempotency
def canonicalize_notification_record(row):
    if row.get("type") != "notification":
        return MigrationChange(False)
    value = row.get("notification_type")
    if value in {"ordinary", "aggregate"}:
        return MigrationChange(False)
    row["notification_type"] = "ordinary"
    return MigrationChange(
        True,
        ("Set the missing notification discriminator to ordinary.",),
    )
