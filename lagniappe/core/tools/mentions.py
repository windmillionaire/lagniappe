"""Checkpoint-time mention validation, delivery, and public sanitization."""

from datetime import datetime, timezone
import hashlib
import re

from bs4 import BeautifulSoup, NavigableString
from google.cloud.datastore import Entity as DatastoreEntity

from ..definitions import Fetch
from ..entities import Entities
from . import collaboration, database, notification_service
from .database.core import DATA


MAX_MENTIONS_PER_CHECKPOINT = 64
OCCURRENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


# @testable true
# @tests tests_unit/test_027_messaging.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:payload-validation
def validate_mentions_payload(value):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_MENTIONS_PER_CHECKPOINT:
        return "Document mentions must be a bounded list."
    for occurrence in value:
        if not isinstance(occurrence, dict):
            return "Document mention must be an object."
        occurrence_id = occurrence.get("occurrence_id")
        recipient = occurrence.get("recipient")
        display_name = occurrence.get("display_name")
        if not isinstance(occurrence_id, str) or not OCCURRENCE_ID_PATTERN.fullmatch(
            occurrence_id
        ):
            return "Document mention occurrence is invalid."
        if (
            not isinstance(recipient, str)
            or not recipient
            or len(recipient) > 512
            or not isinstance(display_name, str)
            or not display_name.strip()
            or len(display_name) > 200
        ):
            return "Document mention recipient is invalid."
    return None


# @testable false
# @covered-by lagniappe/core/tools/mentions.py::deliver_mentions
# @reason saved-node extraction is exercised through checkpoint delivery filtering
def _saved_mentions(html):
    soup = BeautifulSoup(html or "", "html.parser")
    saved = {}
    for node in soup.select('[data-type="lagniappe-mention"][data-mention-id]'):
        occurrence_id = node.get("data-mention-id")
        recipient = node.get("data-recipient")
        display_name = node.get("data-display-name")
        if occurrence_id and recipient and display_name:
            saved[occurrence_id] = {
                "recipient": recipient,
                "display_name": display_name,
            }
    return saved


# @testable true
# @tests tests_unit/test_027_messaging.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:public-sanitization
def sanitize_mentions(html):
    """Render mention nodes as inert plain @Name text for public/export HTML."""
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select('[data-type="lagniappe-mention"]'):
        name = str(node.get("data-display-name") or node.get_text() or "").strip()
        name = name.removeprefix("@").strip()
        node.replace_with(NavigableString(f"@{name}" if name else "@"))
    return str(soup)


# @testable false
# @covered-by lagniappe/core/tools/mentions.py::_deliver_occurrence
# @reason deterministic hashing is asserted through delivery-ledger idempotency
def _marker_identity(document, occurrence_id):
    return hashlib.sha256(
        f"{document.urlsafe_key}\0{occurrence_id}".encode()
    ).hexdigest()


# @testable true
# @tests tests_unit/test_027_messaging.py::test_mention_delivery_ledger_survives_notification_replay
# @pairs mentions:delivery-ledger mentions:idempotency notifications:aggregate-count
@notification_service.retry_transaction
def _deliver_occurrence(actor, recipient, document, occurrence_id, display_name):
    identity = _marker_identity(document, occurrence_id)
    marker_key = database.create_named_key(
        "mention_marker", identity, parent=document
    )
    notification_key = notification_service.ordinary_notification_key(
        recipient, f"document-mention-{identity}"
    )
    now = datetime.now(timezone.utc)
    with DATA.datastore.transaction() as transaction:
        marker = DATA.datastore.get(marker_key, transaction=transaction)
        if marker is not None:
            return False, None
        marker = DatastoreEntity(
            key=marker_key,
            exclude_from_indexes=("occurrence_id", "display_name"),
        )
        marker.update(
            {
                "type": "mention_marker",
                "kind": "mention_marker",
                "document": document.key,
                "actor": actor.key,
                "recipient": recipient.key,
                "occurrence_id": occurrence_id,
                "display_name": display_name,
                "created": now,
                "modified": now,
            }
        )
        notification = notification_service.prepare_ordinary_notification(
            notification_key,
            recipient,
            body=f"{actor.name} mentioned you in {document.name}.",
            target=document,
        )
        aggregate = notification_service.mutate_aggregate_in_transaction(
            transaction, recipient, ordinary_delta=1
        )
        transaction.put(marker)
        transaction.put(notification)
    return True, aggregate


# @testable true
# @tests tests_unit/test_027_messaging.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pairs mentions:saved-occurrence mentions:permission mentions:idempotency
# @pair mentions:document-view
def deliver_mentions(actor, document, html, occurrences):
    """Deliver still-present eligible occurrences after a saved checkpoint."""
    if (
        not occurrences
        or document.entity_kind not in {"page", "project"}
        or not collaboration.managed_user(actor)
    ):
        return 0
    saved = _saved_mentions(html)
    candidates = []
    seen = set()
    for occurrence in occurrences:
        occurrence_id = occurrence["occurrence_id"]
        persisted = saved.get(occurrence_id)
        if occurrence_id in seen or not persisted:
            continue
        if persisted["recipient"] != occurrence["recipient"]:
            continue
        seen.add(occurrence_id)
        candidates.append(
            {
                "occurrence_id": occurrence_id,
                "recipient": occurrence["recipient"],
                "display_name": persisted["display_name"],
            }
        )
    loaded = {
        entity.urlsafe_key: entity
        for entity in Entities.fetch(
            *[candidate["recipient"] for candidate in candidates],
            request=Fetch.direct(),
        )
        if isinstance(entity, Entities.USER)
    }
    delivered = 0
    for candidate in candidates:
        recipient = loaded.get(candidate["recipient"])
        if not recipient or not collaboration.mention_recipient_allowed(
            actor, recipient, document
        ):
            continue
        notification_service.ensure_notification_aggregate(recipient)
        created, aggregate = _deliver_occurrence(
            actor,
            recipient,
            document,
            candidate["occurrence_id"],
            candidate["display_name"],
        )
        if aggregate is not None:
            notification_service.publish_notification_aggregate(
                recipient, aggregate
            )
        delivered += int(created)
    return delivered
