"""Direct-message transactions, projections, and deletion contracts."""

from types import SimpleNamespace

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key
import pytest

from lagniappe.core.definitions import MessageConflict, MessageRevisionConflict
from lagniappe.core.entities.message import Message, MessageConversation
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.mutations.delete import DeleteCollector
from lagniappe.core.properties import message as message_values
from lagniappe.core.properties import message_conversation as conversation_values
from lagniappe.core.tools.database import messaging as messaging_database
from lagniappe.core.tools.database import notifications as notification_database
from lagniappe.core.tools.messaging import service as message_service
from lagniappe.core.tools.messaging import views as message_views
from lagniappe.core.tools.notifications import service as notification_service
from testing.utility.messaging_fakes import MemoryDatastore, managed_user


pytestmark = pytest.mark.unit


# @pairs messaging:deterministic-key messaging:idempotency messaging:unread-count
# @pairs messaging:read-race messaging:per-copy-delete messaging:clear-horizon
# @pairs messaging:conversation-page messaging:compose-eligibility messaging:history-page
# @pairs messaging:chronological-display messaging:new-after-clear
# @pairs messaging:body-validation messaging:reply-permission
# @pairs notifications:aggregate-count notifications:revision
# @source lagniappe/core/tools/messaging/service.py::send_message
# @source lagniappe/core/tools/messaging/service.py::mark_read
# @source lagniappe/core/tools/messaging/service.py::hide_message
# @source lagniappe/core/tools/messaging/service.py::clear_conversation
# @source lagniappe/core/properties/notification_aggregate.py::counts
# @source lagniappe/core/tools/database/notifications.py::mutate_notification_aggregate
def test_message_transactions_are_idempotent_and_keep_exact_unread_counts(monkeypatch):
    store = MemoryDatastore()
    monkeypatch.setattr(messaging_database.DATA, "_datastore_client", store)
    actor = managed_user("actor", "Alice")
    recipient = managed_user("recipient", "Bob")
    recipient_aggregate = notification_database.new_aggregate(
        notification_database.aggregate_key(recipient)
    )
    actor_aggregate = notification_database.new_aggregate(
        notification_database.aggregate_key(actor)
    )
    store.put(recipient_aggregate)
    store.put(actor_aggregate)

    monkeypatch.setattr(
        message_service.collaboration,
        "resolve_user",
        lambda key: actor if key == actor.urlsafe_key else recipient,
    )
    monkeypatch.setattr(
        message_service.collaboration,
        "recipient_allowed",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        message_service.database,
        "ensure_notification_aggregate",
        lambda _user: recipient_aggregate,
    )
    published = []
    monkeypatch.setattr(
        message_service.notification_service,
        "publish_notification_aggregate",
        lambda user, aggregate: published.append((user, dict(aggregate))),
    )
    monkeypatch.setattr(
        message_views,
        "_peer_status",
        lambda rows, user: {
            conversation_values.peer_key(rows[0], user): {
                "peer_available": True,
                "peer_replyable": True,
                "peer_deleted": False,
            }
        },
    )

    first = message_service.send_message(
        actor, recipient.urlsafe_key, "  hello  ", "op-1"
    )
    replay = message_service.send_message(
        actor, recipient.urlsafe_key, "hello", "op-1"
    )

    assert first["created"] is True
    assert first["message"]["body"] == "hello"
    assert replay["created"] is False
    assert replay["message"]["id"] == first["message"]["id"]
    conversation_key = messaging_database.conversation_key(actor, recipient)
    assert conversation_key == messaging_database.conversation_key(recipient, actor)
    conversation = store.get(conversation_key)
    recipient_id = conversation_values.participant_id(recipient)
    assert conversation["unread_counts"][recipient_id] == 1
    assert notification_service.aggregate_counts(recipient_aggregate)["count"] == 1
    assert recipient_aggregate["message_revision"] == 1

    monkeypatch.setattr(
        message_service.collaboration,
        "recipient_allowed",
        lambda candidate, *_args, **_kwargs: candidate is actor,
    )
    with pytest.raises(PermissionError):
        message_service.send_message(
            recipient,
            actor.urlsafe_key,
            "reply without conversation",
            "reply-denied",
        )
    reply = message_service.send_message(
        recipient,
        actor.urlsafe_key,
        "reply in conversation",
        "reply-1",
        conversation_key,
    )
    assert reply["created"] is True
    assert reply["message"]["body"] == "reply in conversation"

    with pytest.raises(MessageConflict):
        message_service.send_message(
            actor, recipient.urlsafe_key, "changed", "op-1"
        )

    with pytest.raises(MessageRevisionConflict):
        message_service.mark_read(recipient, conversation_key, 0)
    message_service.mark_read(
        recipient, conversation_key, conversation["revision"]
    )
    read = store.get(conversation_key)
    aggregate = store.get(notification_database.aggregate_key(recipient))
    assert read["unread_counts"][recipient_id] == 0
    assert aggregate["unread_message_count"] == 0
    assert aggregate["message_revision"] == 1

    second, conversation, _aggregate, created = messaging_database.send_message_record(
        actor, recipient, "second", "op-2"
    )
    assert created is True
    assert message_service.hide_message(recipient, second.key)
    aggregate = store.get(notification_database.aggregate_key(recipient))
    assert recipient.key in store.get(second.key)["hidden_for"]
    assert aggregate["unread_message_count"] == 0
    assert aggregate["message_revision"] == 2

    messaging_database.send_message_record(actor, recipient, "third", "op-3")
    message_service.clear_conversation(recipient, conversation_key)
    cleared = store.get(conversation_key)
    aggregate = store.get(notification_database.aggregate_key(recipient))
    assert recipient.key not in cleared["visible_to"]
    assert cleared["cleared_through"][recipient_id] == cleared["sequence"]
    assert aggregate["unread_message_count"] == 0

    message_service.send_message(actor, recipient.urlsafe_key, "fourth", "op-4")
    restored = store.get(conversation_key)
    assert set(restored["visible_to"]) == {actor.key, recipient.key}
    assert restored["unread_counts"][recipient_id] == 1
    assert published[-1][1]["unread_message_count"] == 1

    class PageResult(list):
        next_cursor = "next-page"

    class MessageQuery:
        def __init__(self, kind, ancestor=None):
            self.kind = kind
            self.ancestor = ancestor
            self.page_limit = None

        def filter(self, _filter):
            return self

        def order(self, _field):
            return self

        def limit(self, value):
            self.page_limit = value
            return self

        def cursor(self, _value):
            return self

        def fetch(self):
            if self.kind == messaging_database.KINDS.message_conversations:
                return PageResult([restored])
            rows = sorted(
                (
                    row
                    for row in store.rows.values()
                    if row.key.parent == conversation_key
                    and row.get("type") == "message"
                ),
                key=lambda row: row["sequence"],
                reverse=True,
            )
            page = PageResult(rows[: self.page_limit])
            page.next_cursor = None
            return page

    monkeypatch.setattr(messaging_database, "Query", MessageQuery)
    listed = message_views.conversations(recipient)
    history = message_views.conversation_history(recipient, restored.key)
    assert listed["conversations"][0]["peer"]["available"] is True
    assert listed["conversations"][0]["peer"]["replyable"] is True
    assert listed["cursor"] == "next-page"
    assert [item["body"] for item in history["messages"]] == ["fourth"]

    with pytest.raises(ValidationError):
        message_values.normalize_body("   ")
    with pytest.raises(ValidationError):
        message_values.normalize_body("x" * 1001)


# @pairs messaging:deleted-peer messaging:history-retention messaging:orphan-purge
# @source lagniappe/core/mutations/delete.py::DeleteCollector.user_messages
# @source lagniappe/core/mutations/delete.py::DeleteCollector.finalize_message_conversations
def test_user_delete_preserves_or_purges_message_history_by_survivor(monkeypatch):
    deleted_user = managed_user("deleted", "Deleted User")
    survivor = managed_user("survivor", "Surviving User")
    conversation_key = Key(
        messaging_database.KINDS.message_conversations.value,
        "conversation",
        project="messaging-test",
    )
    conversation_row = DatastoreEntity(key=conversation_key)
    conversation_row.update(
        {
            "type": "message_conversation",
            "participants": [deleted_user.key, survivor.key],
            "visible_to": [deleted_user.key, survivor.key],
            "participant_names": {
                conversation_values.participant_id(deleted_user): deleted_user.name,
                conversation_values.participant_id(survivor): survivor.name,
            },
        }
    )
    conversation = MessageConversation(conversation_row)
    message_key = Key(
        messaging_database.KINDS.messages.value,
        "message",
        parent=conversation_key,
        project="messaging-test",
    )

    class MessagingRegistry:
        USER = SimpleNamespace
        MESSAGE_CONVERSATION = MessageConversation
        MESSAGE = Message

        def __init__(self, *rows):
            self.rows = {row.key: row for row in rows}

        def fetch(self, *keys, request):
            return [self.rows[key] for key in keys if key in self.rows]

    monkeypatch.setattr(
        "lagniappe.core.mutations.delete.database.message_conversation_keys",
        lambda _user: [conversation_key],
    )
    monkeypatch.setattr(
        "lagniappe.core.mutations.delete.database.message_keys",
        lambda _conversation: [message_key],
    )

    preserving = DeleteCollector(
        MessagingRegistry(deleted_user, survivor, conversation)
    )
    preserving.user_messages(deleted_user)
    preserving.delete(deleted_user)
    preserving.finalize_message_conversations()

    assert conversation.db["visible_to"] == [survivor.key]
    assert conversation.db["participant_names"][
        conversation_values.participant_id(deleted_user)
    ] == "Deleted User"
    assert [item.entity for item in preserving.survivors] == [conversation]
    assert conversation not in preserving.to_delete

    purging = DeleteCollector(MessagingRegistry(survivor, conversation))
    purging.user_messages(survivor)
    purging.delete(survivor)
    purging.finalize_message_conversations()

    deleted_keys = {entity.key for entity in purging.to_delete}
    assert conversation_key in deleted_keys
    assert message_key in deleted_keys
