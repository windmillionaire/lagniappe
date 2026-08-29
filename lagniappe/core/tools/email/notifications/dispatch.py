"""Cloud Task dispatch for queued notification-email rows."""

from math import ceil

from ....exceptions import capture
from ...database import notification_email as email_database
from ...services import task_queue
from .links import identity, origin
from .policy import utc


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/capture.py::record_notification_event
# @reason one-off task dispatch is exercised through public capture APIs
def schedule(row, *, task_suffix=None, now=None):
    now = utc(now)
    encoded = email_database.encoded_key(row.key)
    suffix = task_suffix or row.get("bucket") or row.get("source_key") or encoded
    task_id = f"notification-email-{identity(encoded, suffix)[:32]}"
    delay = max(0, ceil((row["due_at"] - now).total_seconds()))
    try:
        return task_queue.create_task(
            f"{origin()}/process/notification-email",
            {"delivery_key": encoded},
            delay_seconds=delay,
            task_id=task_id,
        )
    except Exception as error:
        capture(
            error,
            context={"operation": "notification-email-enqueue", "delivery_key": encoded},
        )
        return None
