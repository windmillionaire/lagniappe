"""Authorized, idempotent document-mention delivery orchestration."""

from ...definitions import Fetch
from ...entities import Entities
from .. import collaboration, database
from ..email.notifications import capture as email_capture
from ..notifications import service as notification_service
from .content import saved_mentions


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_document_mentions_use_anchored_menu_and_profile_links
# @matrix mentions : document-view idempotency permission saved-occurrence
def deliver_mentions(actor, document, html, occurrences):
    """Deliver still-present eligible occurrences after a saved checkpoint."""
    if (
        not occurrences
        or document.entity_kind not in {"page", "project"}
        or not collaboration.managed_user(actor)
    ):
        return 0
    saved = saved_mentions(html)
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
        database.ensure_notification_aggregate(recipient)
        created, aggregate, notification_key = database.create_mention_delivery(
            actor,
            recipient,
            document,
            candidate["occurrence_id"],
            candidate["display_name"],
        )
        if aggregate is not None:
            notification_service.publish_notification_aggregate(recipient, aggregate)
        if created:
            try:
                email_capture.record_document_mention(
                    recipient,
                    notification_key,
                    document=document,
                )
            except Exception as error:
                from ...exceptions import capture

                capture(error, context={"operation": "mention-email-capture"})
        delivered += int(created)
    return delivered
