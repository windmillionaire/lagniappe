"""Schema values for queued notification-email delivery rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from lagniappe.core.definitions.notification_email import NotificationEmailMode
    from lagniappe.core.entities import types as models


DELIVERY_SCHEMA_VERSION = 1


def initial_values(user: models.User, *, record_type: str, mode: NotificationEmailMode, due_at: datetime, preference_epoch: int, now: datetime) -> dict[str, object]:
    return {
        "type": "notification_email_delivery",
        "schema_version": DELIVERY_SCHEMA_VERSION,
        "record_type": record_type,
        "recipient": user.key,
        "mode": mode.name,
        "preference_epoch": int(preference_epoch),
        "due_at": due_at,
        "state": "pending",
        "created": now,
        "modified": now,
    }


def terminal_values(row: Mapping[str, object], state: str, now: datetime) -> dict[str, object]:
    values = {
        "type": "notification_email_delivery",
        "schema_version": DELIVERY_SCHEMA_VERSION,
        "record_type": row.get("record_type"),
        "recipient": row.get("recipient"),
        "mode": row.get("mode"),
        "state": state,
        "created": row.get("created") or now,
        "modified": now,
        "completed": now,
    }
    if row.get("bucket"):
        values["bucket"] = row["bucket"]
    return values
