"""Schema values for queued notification-email delivery rows."""


DELIVERY_SCHEMA_VERSION = 1


# @testable false
# @covered-by lagniappe/core/tools/notification_email/capture.py::record_notification_event
# @reason exact delivery construction is exercised through capture and delivery
def initial_values(user, *, record_type, mode, due_at, preference_epoch, now):
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


# @testable false
# @covered-by lagniappe/core/tools/notification_email/delivery.py::deliver
# @reason compact terminal schema is exercised through delivery completion
def terminal_values(row, state, now):
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
