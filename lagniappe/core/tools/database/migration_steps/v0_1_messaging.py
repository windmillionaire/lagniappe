"""Canonical notification discriminator transform for messaging aggregates."""

from collections.abc import MutableMapping

from .base import MigrationChange


def canonicalize_notification_record(
    row: MutableMapping[str, object],
) -> MigrationChange:
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
