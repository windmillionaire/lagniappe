"""Atomic mention-marker, notification, and aggregate persistence."""

from datetime import datetime, timezone

from ...properties import mention
from . import notifications
from .core import DATA
from .transactions import retry_aborted
from .utility import create_named_key


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mention_delivery_ledger_survives_notification_replay
# @pairs mentions:delivery-ledger mentions:idempotency notifications:aggregate-count
@retry_aborted
def create_mention_delivery(
    actor,
    recipient,
    document,
    occurrence_id,
    display_name,
):
    from ...entities.mention import MentionMarker

    identity = mention.occurrence_identity(document, occurrence_id)
    marker_key = create_named_key("mention_marker", identity, parent=document)
    notification_key = notifications.ordinary_notification_key(
        recipient, f"document-mention-{identity}"
    )
    now = datetime.now(timezone.utc)
    with DATA.datastore.transaction() as transaction:
        marker = DATA.datastore.get(marker_key, transaction=transaction)
        if marker is not None:
            return False, None, notification_key
        marker = MentionMarker.create(
            actor,
            recipient,
            document,
            occurrence_id,
            display_name,
            key=marker_key,
            now=now,
        ).db
        notification = notifications.prepare_ordinary_notification(
            notification_key,
            recipient,
            body=f"{actor.name} mentioned you in {document.name}.",
            target=document,
        )
        aggregate = notifications.mutate_notification_aggregate(
            transaction, recipient, ordinary_delta=1
        )
        transaction.put(marker)
        transaction.put(notification)
    return True, aggregate, notification_key
