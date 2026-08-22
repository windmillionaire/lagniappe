"""Document-mention content and atomic-delivery contracts."""

from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import mentions as mention_database
from lagniappe.core.tools.database import notifications as notification_database
from lagniappe.core.tools.mentions import content as mention_content
from lagniappe.core.tools.mentions import service as mention_service
from testing.utility.messaging_fakes import MemoryDatastore, managed_user


pytestmark = pytest.mark.unit


# @pairs mentions:payload-validation mentions:saved-occurrence mentions:idempotency mentions:permission
# @pair mentions:document-view
# @pair mentions:public-sanitization
# @source lagniappe/core/tools/mentions/content.py::validate_mentions_payload
# @source lagniappe/core/tools/mentions/content.py::sanitize_mentions
# @source lagniappe/core/tools/mentions/service.py::deliver_mentions
def test_mentions_validate_saved_occurrences_dedupe_and_sanitize(monkeypatch):
    occurrence = {
        "occurrence_id": "mention_1234",
        "recipient": "recipient-key",
        "display_name": "Bob Example",
    }
    assert mention_content.validate_mentions_payload([occurrence]) is None
    assert mention_content.validate_mentions_payload([{}]) is not None
    assert mention_content.validate_mentions_payload([occurrence] * 65) is not None

    html = (
        '<p>Hello <span data-type="lagniappe-mention" '
        'data-mention-id="mention_1234" data-recipient="recipient-key" '
        'data-display-name="Bob Example">@Bob Example</span>.</p>'
    )
    sanitized = mention_content.sanitize_mentions(html)
    assert "@Bob Example" in sanitized
    assert "recipient-key" not in sanitized
    assert "data-mention" not in sanitized

    actor = managed_user("actor", "Alice")
    actor.properties = SimpleNamespace(
        restrictions=SimpleNamespace(user_message_restrictions=["shared"])
    )
    recipient = managed_user("recipient", "Bob")
    recipient.urlsafe_key = "recipient-key"
    recipient.requires = ["users", "shared"]
    document = SimpleNamespace(
        entity_kind="page",
        urlsafe_key="document-key",
        key=Key("pages", "document", project="messaging-test"),
        name="Roadmap",
        can_view=True,
    )
    document.allowed = lambda _action, user: document.can_view and user is recipient
    monkeypatch.setattr(mention_service.Entities, "USER", SimpleNamespace)
    monkeypatch.setattr(
        mention_service.Entities, "fetch", lambda *_args, **_kwargs: [recipient]
    )
    monkeypatch.setattr(
        mention_service.database,
        "ensure_notification_aggregate",
        lambda _user: {},
    )
    deliveries = []
    monkeypatch.setattr(
        mention_service.database,
        "create_mention_delivery",
        lambda *args: deliveries.append(args)
        or (True, None, "document-mention-notification-key"),
    )
    email_deliveries = []
    monkeypatch.setattr(
        mention_service.email_capture,
        "record_document_mention",
        lambda *args, **kwargs: email_deliveries.append((args, kwargs)),
    )

    delivered = mention_service.deliver_mentions(
        actor,
        document,
        html,
        [occurrence, occurrence, {**occurrence, "recipient": "changed"}],
    )
    assert delivered == 1
    assert len(deliveries) == 1
    assert email_deliveries[0][0][0] is recipient
    assert email_deliveries[0][0][1] == "document-mention-notification-key"
    assert email_deliveries[0][1] == {"document": document}

    document.can_view = False
    deliveries.clear()
    email_deliveries.clear()
    assert mention_service.deliver_mentions(actor, document, html, [occurrence]) == 0
    assert deliveries == []
    assert email_deliveries == []


# @pairs mentions:delivery-ledger mentions:idempotency notifications:aggregate-count
# @source lagniappe/core/tools/database/mentions.py::create_mention_delivery
def test_mention_delivery_ledger_survives_notification_replay(monkeypatch):
    store = MemoryDatastore()
    monkeypatch.setattr(mention_database.DATA, "_datastore_client", store)
    actor = managed_user("mention-actor", "Alice")
    recipient = managed_user("mention-recipient", "Bob")
    document_key = Key("pages", "mentioned-page", project="messaging-test")
    document = SimpleNamespace(
        key=document_key,
        urlsafe_key=document_key.to_legacy_urlsafe().decode(),
        name="Roadmap",
    )
    aggregate = notification_database.new_aggregate(
        notification_database.aggregate_key(recipient)
    )
    store.put(aggregate)

    created, first_aggregate, _notification_key = mention_database.create_mention_delivery(
        actor,
        recipient,
        document,
        "mention_ledger_1",
        "Bob",
    )
    replayed, replay_aggregate, _notification_key = mention_database.create_mention_delivery(
        actor,
        recipient,
        document,
        "mention_ledger_1",
        "Bob",
    )

    assert created is True
    assert replayed is False
    assert replay_aggregate is None
    assert first_aggregate["ordinary_count"] == 1
    notification_rows = [
        row
        for row in store.rows.values()
        if row.get("type") == "notification"
        and row.get("notification_type") == "ordinary"
    ]
    assert len(notification_rows) == 1

