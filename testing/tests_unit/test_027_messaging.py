"""Focused unit contracts for managed-user messaging and mentions."""

from types import SimpleNamespace

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key
from google.api_core import exceptions as google_exceptions
import pytest

from lagniappe.core.definitions import Restriction
from lagniappe.core.entities import Entities
from lagniappe.core.entities.message import Message, MessageConversation
from lagniappe.core.entities.mention import MentionMarker
from lagniappe.core.entities.notification import Notification
from lagniappe.core.entities.page import Page
from lagniappe.core.entities.user import User
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.mutations.delete import DeleteCollector
from lagniappe.core.tools import collaboration, mentions, messages, notification_service
from lagniappe.core.tools.cache import owner
from lagniappe.core.tools.database.migration_steps.v0_1_messaging import (
    canonicalize_notification_record,
)
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


class MemoryDatastore:
    """Small transaction-compatible Datastore fake for one entity group flow."""

    def __init__(self):
        self.rows = {}

    def key(self, kind, identifier=None, parent=None):
        return Key(kind, identifier, parent=parent, project="messaging-test")

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, key, transaction=None):
        return self.rows.get(key)

    def get_multi(self, keys, transaction=None):
        return [self.rows.get(key) for key in keys]

    def put(self, row):
        self.rows[row.key] = row

    def delete(self, key):
        self.rows.pop(key, None)


class HashRedis:
    def __init__(self):
        self.values = {}

    def hgetall(self, key):
        return dict(self.values.get(key, {}))

    def hset(self, key, mapping):
        self.values.setdefault(key, {}).update(mapping)
        return len(mapping)


def managed_user(identifier, name, *, owner_user=False, public=False):
    key = Key("users", identifier, project="messaging-test")
    return SimpleNamespace(
        key=key,
        urlsafe_key=key.to_legacy_urlsafe().decode(),
        name=name,
        hash=f"hash-{identifier}",
        is_authenticated=True,
        is_public=public,
        is_owner=owner_user,
        allow_messages_and_mentions=False,
        allow_task_assignments=False,
        requires=["users", f"group-{identifier}"],
    )


# @pairs messaging:entity-contract messaging:owner-opt-in messaging:index-exclusion
# @pairs mentions:entity-contract mentions:idempotency mentions:index-exclusion
# @pairs notifications:discriminator notifications:aggregate-count
# @pairs notifications:revision notifications:generation
# @source lagniappe/core/entities/message.py::MessageConversation
# @source lagniappe/core/entities/message.py::Message
# @source lagniappe/core/entities/mention.py::MentionMarker
# @source lagniappe/core/properties/messaging.py::NotificationType.value
# @source lagniappe/core/properties/messaging.py::OrdinaryCount.value
# @source lagniappe/core/properties/messaging.py::UnreadMessageCount.value
# @source lagniappe/core/properties/messaging.py::AggregateRevision.value
# @source lagniappe/core/properties/messaging.py::AggregateGeneration.value
# @source lagniappe/core/properties/user_entity.py::OwnerInboundToggle.value
def test_messaging_entities_and_owner_toggles_are_fail_closed():
    user = User(testing=True)
    assert user.allow_messages_and_mentions is False
    assert user.allow_task_assignments is False

    user.allow_messages_and_mentions = "true"
    user.allow_task_assignments = True
    assert user.allow_messages_and_mentions is True
    assert user.allow_task_assignments is True

    user.allow_messages_and_mentions = "false"
    user.allow_task_assignments = None
    assert user.allow_messages_and_mentions is False
    assert user.allow_task_assignments is False
    assert "allow_messages_and_mentions" not in user.db
    assert "allow_task_assignments" not in user.db

    conversation = MessageConversation(testing=True)
    message = Message(testing=True)
    marker = MentionMarker(testing=True)
    assert "participant_names" in conversation.exclude_from_index
    assert "body" in message.exclude_from_index
    assert "hidden_for" in message.exclude_from_index
    assert marker.exclude_from_index == frozenset({"occurrence_id", "display_name"})

    notification = Notification(testing=True)
    assert notification.notification_type == "ordinary"
    notification.ordinary_count = 3
    notification.unread_message_count = 2
    notification.aggregate_revision = 7
    notification.aggregate_generation = "generation-a"
    assert notification.ordinary_count == 3
    assert notification.unread_message_count == 2
    assert notification.aggregate_revision == 7
    assert notification.aggregate_generation == "generation-a"


# @pairs messaging:permission messaging:self-exclusion messaging:public-exclusion
# @pairs messaging:owner-opt-in messaging:managed-user messaging:recipient-resolution
# @pairs mentions:document-view mentions:permission task-assignment:permission
# @source lagniappe/core/tools/collaboration.py::managed_user
# @source lagniappe/core/tools/collaboration.py::can_initiate_messages
# @source lagniappe/core/tools/collaboration.py::recipient_allowed
# @source lagniappe/core/tools/collaboration.py::mention_recipient_allowed
def test_collaboration_permissions_use_current_recipient_and_document_access(
    monkeypatch,
):
    actor = managed_user("actor", "Actor")
    actor.properties = SimpleNamespace(
        restrictions=SimpleNamespace(
            user_message_restrictions=["shared"],
            user_assign_restrictions=["assigned"],
            can_initiate_messages=True,
        )
    )
    assert collaboration.can_initiate_messages(actor)
    actor.properties.restrictions.can_initiate_messages = False
    assert not collaboration.can_initiate_messages(actor)
    actor.properties.restrictions.can_initiate_messages = True
    recipient = managed_user("recipient", "Recipient")
    recipient.requires = ["users", "shared"]

    assert collaboration.recipient_allowed(actor, recipient, channel="message")
    assert not collaboration.recipient_allowed(actor, actor, channel="message")
    public = managed_user("public", "Public", public=True)
    assert not collaboration.recipient_allowed(actor, public, channel="message")

    owner_recipient = managed_user("owner", "Owner", owner_user=True)
    assert not collaboration.recipient_allowed(
        actor, owner_recipient, channel="message"
    )
    owner_recipient.allow_messages_and_mentions = True
    assert collaboration.recipient_allowed(
        actor, owner_recipient, channel="message"
    )

    viewers = []
    document = SimpleNamespace(
        allowed=lambda _action, user: viewers.append(user) or user is recipient
    )
    assert collaboration.mention_recipient_allowed(actor, recipient, document)
    assert viewers == [recipient]

    actor.properties.restrictions.user_message_restrictions = Restriction.UNRESTRICTED
    stranger = managed_user("stranger", "Stranger")
    assert collaboration.recipient_allowed(actor, stranger, channel="message")

    stored_user = User(testing=True)
    stored_page = Page(testing=True)
    stored_page.properties.user._value = stored_user
    monkeypatch.setattr(
        collaboration.Entities,
        "fetch_one",
        lambda identifier, request: stored_user if identifier == "user" else stored_page,
    )
    assert collaboration.resolve_user("user") is stored_user
    assert collaboration.resolve_user("page") is stored_user


# @pairs messaging:deterministic-key messaging:idempotency messaging:unread-count
# @pairs messaging:read-race messaging:per-copy-delete messaging:clear-horizon
# @pairs messaging:conversation-page messaging:compose-eligibility messaging:history-page
# @pairs messaging:chronological-display messaging:new-after-clear
# @pairs notifications:aggregate-count notifications:revision
# @source lagniappe/core/tools/messages.py::send_message
# @source lagniappe/core/tools/messages.py::mark_read
# @source lagniappe/core/tools/messages.py::hide_message
# @source lagniappe/core/tools/messages.py::clear_conversation
# @source lagniappe/core/tools/notification_service.py::aggregate_counts
# @source lagniappe/core/tools/notification_service.py::mutate_aggregate_in_transaction
def test_message_transactions_are_idempotent_and_keep_exact_unread_counts(monkeypatch):
    store = MemoryDatastore()
    monkeypatch.setattr(messages.DATA, "_datastore_client", store)
    actor = managed_user("actor", "Alice")
    recipient = managed_user("recipient", "Bob")
    recipient_aggregate = notification_service._new_aggregate(
        notification_service.aggregate_key(recipient)
    )
    actor_aggregate = notification_service._new_aggregate(
        notification_service.aggregate_key(actor)
    )
    store.put(recipient_aggregate)
    store.put(actor_aggregate)

    monkeypatch.setattr(
        messages.collaboration,
        "resolve_user",
        lambda key: actor if key == actor.urlsafe_key else recipient,
    )
    monkeypatch.setattr(
        messages.collaboration, "recipient_allowed", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(
        messages.notification_service,
        "ensure_notification_aggregate",
        lambda _user: recipient_aggregate,
    )
    published = []
    monkeypatch.setattr(
        messages.notification_service,
        "publish_notification_aggregate",
        lambda user, aggregate: published.append((user, dict(aggregate))),
    )
    monkeypatch.setattr(
        messages,
        "_peer_status",
        lambda rows, user: {
            messages._conversation_peer(rows[0], user): {
                "peer_available": True,
                "peer_replyable": True,
                "peer_deleted": False,
            }
        },
    )

    first = messages.send_message(actor, recipient.urlsafe_key, "  hello  ", "op-1")
    replay = messages.send_message(actor, recipient.urlsafe_key, "hello", "op-1")

    assert first["created"] is True
    assert first["message"]["body"] == "hello"
    assert replay["created"] is False
    assert replay["message"]["id"] == first["message"]["id"]
    conversation_key = messages._conversation_key(actor, recipient)
    assert conversation_key == messages._conversation_key(recipient, actor)
    conversation = store.get(conversation_key)
    recipient_id = messages._participant_id(recipient)
    assert conversation["unread_counts"][recipient_id] == 1
    assert notification_service.aggregate_counts(recipient_aggregate)["count"] == 1

    monkeypatch.setattr(
        messages.collaboration,
        "recipient_allowed",
        lambda candidate, *_args, **_kwargs: candidate is actor,
    )
    with pytest.raises(PermissionError):
        messages.send_message(
            recipient,
            actor.urlsafe_key,
            "reply without conversation",
            "reply-denied",
        )
    reply = messages.send_message(
        recipient,
        actor.urlsafe_key,
        "reply in conversation",
        "reply-1",
        conversation_key,
    )
    assert reply["created"] is True
    assert reply["message"]["body"] == "reply in conversation"

    with pytest.raises(messages.MessageConflict):
        messages.send_message(actor, recipient.urlsafe_key, "changed", "op-1")

    with pytest.raises(messages.MessageRevisionConflict):
        messages.mark_read(recipient, conversation_key, 0)
    messages.mark_read(
        recipient, conversation_key, conversation["revision"]
    )
    read = store.get(conversation_key)
    aggregate = store.get(notification_service.aggregate_key(recipient))
    assert read["unread_counts"][recipient_id] == 0
    assert aggregate["unread_message_count"] == 0

    second, conversation, _aggregate, created = messages._send_transaction(
        actor, recipient, "second", "op-2"
    )
    assert created is True
    assert messages.hide_message(recipient, second.key)
    aggregate = store.get(notification_service.aggregate_key(recipient))
    assert recipient.key in store.get(second.key)["hidden_for"]
    assert aggregate["unread_message_count"] == 0

    messages._send_transaction(actor, recipient, "third", "op-3")
    messages.clear_conversation(recipient, conversation_key)
    cleared = store.get(conversation_key)
    aggregate = store.get(notification_service.aggregate_key(recipient))
    assert recipient.key not in cleared["visible_to"]
    assert cleared["cleared_through"][recipient_id] == cleared["sequence"]
    assert aggregate["unread_message_count"] == 0

    messages.send_message(actor, recipient.urlsafe_key, "fourth", "op-4")
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
            if self.kind == messages.KINDS.message_conversations:
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

    monkeypatch.setattr(messages, "Query", MessageQuery)
    listed = messages.conversations(recipient)
    history = messages.conversation_history(recipient, restored.key)
    assert listed["conversations"][0]["peer"]["available"] is True
    assert listed["conversations"][0]["peer"]["replyable"] is True
    assert listed["cursor"] == "next-page"
    assert [item["body"] for item in history["messages"]] == ["fourth"]

    with pytest.raises(ValidationError):
        messages._validated_body("   ")
    with pytest.raises(ValidationError):
        messages._validated_body("x" * 1001)


# @pairs messaging:deleted-peer messaging:history-retention messaging:orphan-purge
# @source lagniappe/core/mutations/delete.py::DeleteCollector.user_messages
# @source lagniappe/core/mutations/delete.py::DeleteCollector.finalize_message_conversations
def test_user_delete_preserves_or_purges_message_history_by_survivor(monkeypatch):
    deleted_user = managed_user("deleted", "Deleted User")
    survivor = managed_user("survivor", "Surviving User")
    conversation_key = Key(
        messages.KINDS.message_conversations.value,
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
                messages._participant_id(deleted_user): deleted_user.name,
                messages._participant_id(survivor): survivor.name,
            },
        }
    )
    conversation = MessageConversation(conversation_row)
    message_key = Key(
        messages.KINDS.messages.value,
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
        "lagniappe.core.mutations.delete.database.get.message_conversation_keys",
        lambda _user: [conversation_key],
    )
    monkeypatch.setattr(
        "lagniappe.core.mutations.delete.database.get.message_keys",
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
        messages._participant_id(deleted_user)
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


# @pairs mentions:payload-validation mentions:saved-occurrence mentions:idempotency mentions:permission
# @pair mentions:document-view
# @pair mentions:public-sanitization
# @source lagniappe/core/tools/mentions.py::validate_mentions_payload
# @source lagniappe/core/tools/mentions.py::sanitize_mentions
# @source lagniappe/core/tools/mentions.py::deliver_mentions
def test_mentions_validate_saved_occurrences_dedupe_and_sanitize(monkeypatch):
    occurrence = {
        "occurrence_id": "mention_1234",
        "recipient": "recipient-key",
        "display_name": "Bob Example",
    }
    assert mentions.validate_mentions_payload([occurrence]) is None
    assert mentions.validate_mentions_payload([{}]) is not None
    assert mentions.validate_mentions_payload([occurrence] * 65) is not None

    html = (
        '<p>Hello <span data-type="lagniappe-mention" '
        'data-mention-id="mention_1234" data-recipient="recipient-key" '
        'data-display-name="Bob Example">@Bob Example</span>.</p>'
    )
    sanitized = mentions.sanitize_mentions(html)
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
    monkeypatch.setattr(mentions.Entities, "USER", SimpleNamespace)
    monkeypatch.setattr(mentions.Entities, "fetch", lambda *_args, **_kwargs: [recipient])
    monkeypatch.setattr(
        mentions.notification_service,
        "ensure_notification_aggregate",
        lambda _user: {},
    )
    deliveries = []
    monkeypatch.setattr(
        mentions,
        "_deliver_occurrence",
        lambda *args: deliveries.append(args) or (True, None),
    )

    delivered = mentions.deliver_mentions(
        actor,
        document,
        html,
        [occurrence, occurrence, {**occurrence, "recipient": "changed"}],
    )
    assert delivered == 1
    assert len(deliveries) == 1

    document.can_view = False
    deliveries.clear()
    assert mentions.deliver_mentions(actor, document, html, [occurrence]) == 0
    assert deliveries == []


# @pairs mentions:delivery-ledger mentions:idempotency notifications:aggregate-count
# @source lagniappe/core/tools/mentions.py::_deliver_occurrence
def test_mention_delivery_ledger_survives_notification_replay(monkeypatch):
    store = MemoryDatastore()
    monkeypatch.setattr(mentions.DATA, "_datastore_client", store)
    actor = managed_user("mention-actor", "Alice")
    recipient = managed_user("mention-recipient", "Bob")
    document_key = Key("pages", "mentioned-page", project="messaging-test")
    document = SimpleNamespace(
        key=document_key,
        urlsafe_key=document_key.to_legacy_urlsafe().decode(),
        name="Roadmap",
    )
    aggregate = notification_service._new_aggregate(
        notification_service.aggregate_key(recipient)
    )
    store.put(aggregate)

    created, first_aggregate = mentions._deliver_occurrence(
        actor,
        recipient,
        document,
        "mention_ledger_1",
        "Bob",
    )
    replayed, replay_aggregate = mentions._deliver_occurrence(
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


# @pairs owner-projection:normalization owner-projection:repair owner-projection:request-memo
# @pairs owner-projection:fail-closed owner-projection:selector-shape owner-projection:revision
# @source lagniappe/core/tools/cache/owner.py::normalize_owner_name
# @source lagniappe/core/tools/cache/owner.py::update_owner_projection
# @source lagniappe/core/tools/cache/owner.py::get_owner_projection
# @source lagniappe/core/tools/cache/owner.py::owner_search_result
def test_owner_projection_normalizes_and_round_trips(monkeypatch):
    redis = HashRedis()
    monkeypatch.setattr(owner.cache, "_redis", redis)
    owner.clear_request_owner_projection()
    user = managed_user("owner", "  JOSÉ   Example  ", owner_user=True)
    page_key = Key("pages", "owner-page", project="messaging-test")
    user.properties = SimpleNamespace(page=SimpleNamespace(key=page_key))
    user.allow_messages_and_mentions = True

    projection = owner.update_owner_projection(user)
    owner.clear_request_owner_projection()
    loaded = owner.get_owner_projection(repair=False)

    assert owner.normalize_owner_name("  Jose\u0301  EXAMPLE ") == "josé example"
    assert projection == loaded
    assert loaded["allow_messages_and_mentions"] is True
    assert loaded["allow_task_assignments"] is False
    result = owner.owner_search_result(loaded)
    assert result["details"]["recipient_key"] == user.urlsafe_key
    assert result["id"] == page_key.to_legacy_urlsafe().decode()


# @pairs messaging:owner-search messaging:self-exclusion messaging:recipient-key
# @pairs mentions:document-view owner-projection:normalization owner-projection:deduplication
# @source lagniappe/core/tools/collaboration.py::collaboration_user_results
def test_collaboration_search_filters_self_owner_and_document_access(monkeypatch):
    class SearchPage:
        def __init__(self, identifier, user):
            self.urlsafe_key = identifier
            self.user = user

    actor = managed_user("search-actor", "Actor")
    actor.page = SimpleNamespace(urlsafe_key="self-page")
    allowed_user = managed_user("allowed", "Allowed")
    denied_user = managed_user("denied", "Denied")
    pages = {
        "allowed-page": SearchPage("allowed-page", allowed_user),
        "denied-page": SearchPage("denied-page", denied_user),
    }
    projection = {
        "key": "owner-user",
        "page_key": "owner-page",
        "hash": "owner-hash",
        "name": "José Example",
        "normalized_name": "josé example",
        "allow_messages_and_mentions": True,
        "allow_task_assignments": False,
        "revision": 1,
    }
    rows = [
        {"id": "self-page", "name": "Actor", "kind": "user", "details": {}},
        {"id": "owner-page", "name": "Owner", "kind": "user", "details": {}},
        {
            "id": "allowed-page",
            "name": "Allowed",
            "kind": "user",
            "details": {"hash": "allowed-hash"},
        },
        {
            "id": "denied-page",
            "name": "Denied",
            "kind": "user",
            "details": {"hash": "denied-hash"},
        },
        {
            "id": "deleted-page",
            "name": "Deleted",
            "kind": "user",
            "details": {"hash": "deleted-hash"},
        },
    ]
    document = SimpleNamespace(
        allowed=lambda _action, user: user is allowed_user
    )
    monkeypatch.setattr(collaboration.cache, "get_owner_projection", lambda: projection)
    monkeypatch.setattr(collaboration.Entities, "PAGE", SearchPage)
    monkeypatch.setattr(
        collaboration.Entities,
        "fetch",
        lambda *identifiers, **_kwargs: [
            pages[identifier] for identifier in identifiers if identifier in pages
        ],
    )
    monkeypatch.setattr(
        collaboration.Entities, "fetch_one", lambda *_args, **_kwargs: document
    )

    message_results = collaboration.collaboration_user_results(
        [dict(row) for row in rows], "SÉ ex", "message", actor
    )
    mention_results = collaboration.collaboration_user_results(
        [dict(row) for row in rows],
        "example",
        "mention",
        actor,
        document_identifier="document-key",
    )
    blank_results = collaboration.collaboration_user_results(
        [dict(row) for row in rows], "", "message", actor
    )

    assert [row["id"] for row in message_results] == [
        "allowed-page",
        "denied-page",
        "owner-page",
    ]
    assert message_results[0]["details"]["recipient_key"] == allowed_user.urlsafe_key
    assert [row["id"] for row in mention_results] == [
        "allowed-page",
        "owner-page",
    ]
    assert [row["id"] for row in blank_results] == [
        "allowed-page",
        "denied-page",
    ]


# @pairs migrations:notification-discriminator migrations:idempotency
# @source lagniappe/core/tools/database/migration_steps/v0_1_messaging.py::canonicalize_notification_record
def test_notification_discriminator_migration_is_idempotent():
    notification = {"type": "notification"}
    first = canonicalize_notification_record(notification)
    second = canonicalize_notification_record(notification)

    assert first.changed is True
    assert notification["notification_type"] == "ordinary"
    assert second.changed is False
    assert canonicalize_notification_record({"type": "note"}).changed is False


# @pairs notifications:ordinary-create notifications:ordinary-delete notifications:ordinary-count
# @pairs notifications:ordinary-clear notifications:idempotency notifications:aggregate-count
# @pairs notifications:transaction-retry notifications:aggregate-repair notifications:revision
# @pair notifications:cache-failure-isolation
# @source lagniappe/core/tools/notification_service.py::create_ordinary_notification
# @source lagniappe/core/tools/notification_service.py::delete_ordinary_notification
# @source lagniappe/core/tools/notification_service.py::clear_ordinary_notifications
def test_ordinary_notification_service_mutates_aggregate_once(monkeypatch):
    store = MemoryDatastore()
    monkeypatch.setattr(notification_service.DATA, "_datastore_client", store)
    user = managed_user("notice-user", "Notice User")
    aggregate = notification_service._new_aggregate(
        notification_service.aggregate_key(user)
    )
    store.put(aggregate)
    monkeypatch.setattr(Entities, "fetch_one", lambda row, request: row)

    first, created = notification_service.create_ordinary_notification(
        user,
        identifier="notice-one",
        body="First",
    )
    replay, replay_created = notification_service.create_ordinary_notification(
        user,
        identifier="notice-one",
        body="First",
    )
    assert created is True
    assert replay_created is False
    assert replay.key == first.key
    assert aggregate["ordinary_count"] == 1

    second, _created = notification_service.create_ordinary_notification(
        user,
        identifier="notice-two",
        body="Second",
    )
    assert aggregate["ordinary_count"] == 2
    assert notification_service.delete_ordinary_notification(user, first.key)
    assert aggregate["ordinary_count"] == 1
    assert notification_service.clear_ordinary_notifications(user, [second.key]) == 1
    assert aggregate["ordinary_count"] == 0

    mutation = SimpleNamespace(
        parent=user,
        notification_type="ordinary",
        _notification_count_delta=1,
    )
    projected = notification_service.apply_ordinary_mutations(upserts=[mutation])
    assert projected[user.urlsafe_key]["ordinary_count"] == 1
    revision = projected[user.urlsafe_key]["aggregate_revision"]
    mutation._notification_count_delta = 0
    projected = notification_service.apply_ordinary_mutations(upserts=[mutation])
    assert projected[user.urlsafe_key]["ordinary_count"] == 1
    assert projected[user.urlsafe_key]["aggregate_revision"] == revision + 1

    repair_user = managed_user("repair-user", "Repair User")
    repaired = notification_service.repair_notification_aggregate(
        repair_user, ordinary_count=2
    )
    assert repaired["ordinary_count"] == 2
    assert notification_service.ensure_notification_aggregate(repair_user) is repaired

    attempts = []
    monkeypatch.setattr(notification_service.time, "sleep", lambda delay: attempts.append(delay))

    @notification_service.retry_transaction
    def contended():
        if len(attempts) < 2:
            raise google_exceptions.Aborted("retry")
        return "done"

    assert contended() == "done"
    assert attempts == [0.05, 0.1]

    captured = []
    from lagniappe.core import exceptions as core_exceptions

    monkeypatch.setattr(
        core_exceptions,
        "capture",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    from lagniappe.core.tools import cache as notification_cache

    monkeypatch.setattr(
        notification_cache,
        "publish_notification_aggregate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
    )
    notification_service.publish_notification_aggregate(user, aggregate)
    assert captured and captured[0][1]["context"] == {
        "operation": "notification-aggregate-publish"
    }


# @pairs task-assignment:transition task-assignment:idempotency task-assignment:self-exclusion
# @source lagniappe/core/entities/task.py::Task._add_assignment_notice
def test_task_assignment_notice_uses_stable_transition_identity(monkeypatch):
    task = TestEntities.get("TASK", {"name": "Review", "hash": "task-notice"})
    actor = TestEntities.get(
        "USER",
        {
            "name": "Alice",
            "hash": "assignment-actor",
            "page": {"name": "Alice Page", "hash": "assignment-actor-page"},
        },
    )
    recipient = TestEntities.get(
        "USER",
        {
            "name": "Bob",
            "hash": "assignment-recipient",
            "page": {"name": "Bob Page", "hash": "assignment-recipient-page"},
        },
    )
    recipient.page.properties.user._value = recipient
    task.db["assignment_revision"] = 4
    captured = []
    notice = Notification(testing=True)
    notice._key = "assignment-notice"
    monkeypatch.setattr(
        Entities.NOTIFICATION,
        "create",
        lambda data: captured.append(data) or notice,
    )

    task._add_assignment_notice(actor, recipient.page)
    task._add_assignment_notice(actor, recipient.page)
    assert captured[0]["identifier"] == captured[1]["identifier"]
    assert captured[0]["parent"] is recipient
    assert captured[0]["target"] is task
    assert captured[0]["body"] == "Alice assigned you a task."

    captured.clear()
    actor.page.properties.user._value = actor
    task._add_assignment_notice(actor, actor.page)
    assert captured == []
