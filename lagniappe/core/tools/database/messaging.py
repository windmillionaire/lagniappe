"""Direct-message Datastore transactions and indexed query recipes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from google.cloud.datastore import Entity as Row
from google.cloud.datastore import Key

from ...definitions import MessageConflict, MessageRevisionConflict
from ...properties import message as message_values
from ...properties import message_conversation as conversation_values
from . import notifications
from .core import DATA, KINDS
from .filter import Filter, Query, Results
from .get import datastore_key
from .transactions import retry_aborted
from .utility import create_named_key, stored_key, stored_row

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User

    from .get import Identifier


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:deterministic-key
def conversation_key(first: User, second: User) -> Key:
    return create_named_key(
        "message_conversation",
        conversation_values.conversation_identity(first, second),
    )


# @testable false
# @covered-by lagniappe/core/tools/database/messaging.py::send_message_record
# @reason deterministic message identity is asserted through idempotent send
def message_key(conversation: Key, sender: User, operation_id: str) -> Key:
    return create_named_key(
        "message",
        message_values.message_identity(sender, operation_id),
        parent=conversation,
    )


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::get_conversation
# @reason shared authorization guard is exercised by public read and write boundaries
def require_participant(conversation: Row | None, user: User) -> None:
    if not conversation or not conversation_values.participant(conversation, user):
        raise PermissionError("Conversation is unavailable.")


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @matrix messaging : idempotency unread-count
# @pair notifications:aggregate-count
@retry_aborted
def send_message_record(
    actor: User,
    recipient: User,
    body: str,
    operation_id: str,
    *,
    require_existing: bool = False,
) -> tuple[Row, Row | None, Row | None, bool]:
    from ...entities.message import Message, MessageConversation

    current_conversation_key = conversation_key(actor, recipient)
    current_message_key = message_key(current_conversation_key, actor, operation_id)
    now = datetime.now(UTC)
    with DATA.datastore.transaction() as transaction:
        existing_message = DATA.datastore.get(
            current_message_key, transaction=transaction
        )
        if existing_message is not None:
            if not message_values.payload_matches(
                existing_message, actor, recipient, body, operation_id
            ):
                raise MessageConflict("Operation ID was already used.")
            conversation = DATA.datastore.get(
                current_conversation_key, transaction=transaction
            )
            return existing_message, conversation, None, False

        conversation = DATA.datastore.get(
            current_conversation_key, transaction=transaction
        )
        if conversation is None and require_existing:
            raise PermissionError("Conversation is unavailable.")
        if conversation is None:
            conversation = stored_row(MessageConversation.create(
                actor,
                recipient,
                key=current_conversation_key,
                now=now,
            ))
        require_participant(conversation, actor)
        if recipient.key not in set(conversation.get("participants") or ()):
            raise PermissionError("Conversation is unavailable.")

        sequence = conversation_values.apply_send(
            conversation, actor, recipient, now
        )
        message = stored_row(Message.create(
            MessageConversation(conversation),
            actor,
            recipient,
            key=current_message_key,
            body=body,
            operation_id=operation_id,
            sequence=sequence,
            now=now,
        ))
        aggregate = notifications.mutate_notification_aggregate(
            transaction, recipient, message_delta=1
        )
        transaction.put(conversation)
        transaction.put(message)
    return message, conversation, aggregate, True


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:read-race
@retry_aborted
def mark_conversation_read(
    user: User, key: Key, expected_revision: int | None = None
) -> tuple[Row, Row | None]:
    with DATA.datastore.transaction() as transaction:
        conversation = DATA.datastore.get(key, transaction=transaction)
        if conversation is None:
            raise PermissionError("Conversation is unavailable.")
        require_participant(conversation, user)
        if expected_revision is not None and int(
            conversation.get("revision") or 0
        ) != int(expected_revision):
            raise MessageRevisionConflict(conversation)
        prior = conversation_values.apply_read(
            conversation, user, datetime.now(UTC)
        )
        if not prior:
            return conversation, None
        aggregate = notifications.mutate_notification_aggregate(
            transaction, user, message_delta=-prior
        )
        transaction.put(conversation)
    return conversation, aggregate


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:per-copy-delete
@retry_aborted
def hide_message_for_user(user: User, key: Key) -> tuple[Row | None, Row | None]:
    with DATA.datastore.transaction() as transaction:
        message = DATA.datastore.get(key, transaction=transaction)
        if message is None:
            return None, None
        conversation = DATA.datastore.get(stored_key(message).parent, transaction=transaction)
        if conversation is None:
            raise PermissionError("Conversation is unavailable.")
        require_participant(conversation, user)
        hidden: set[Key | None] = set(message.get("hidden_for") or ())
        if user.key in hidden:
            return conversation, None
        hidden.add(user.key)
        message["hidden_for"] = list(hidden)
        message["modified"] = datetime.now(UTC)
        aggregate = None
        if conversation_values.apply_hidden_message(conversation, message, user):
            aggregate = notifications.mutate_notification_aggregate(
                transaction, user, message_delta=-1
            )
            transaction.put(conversation)
        transaction.put(message)
    return conversation, aggregate


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @pair messaging:clear-horizon
@retry_aborted
def clear_message_conversation(user: User, key: Key) -> tuple[Row, Row | None]:
    with DATA.datastore.transaction() as transaction:
        conversation = DATA.datastore.get(key, transaction=transaction)
        if conversation is None:
            raise PermissionError("Conversation is unavailable.")
        require_participant(conversation, user)
        prior = conversation_values.apply_clear(
            conversation, user, datetime.now(UTC)
        )
        aggregate = None
        if prior:
            aggregate = notifications.mutate_notification_aggregate(
                transaction, user, message_delta=-prior
            )
        transaction.put(conversation)
    return conversation, aggregate


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::get_conversation
# @reason direct lookup is exercised by the authorized view boundary
def get_conversation(identifier: Identifier) -> Row | None:
    key = datastore_key(identifier)
    return DATA.datastore.get(key) if key else None


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::conversations
# @reason indexed query plumbing is exercised through conversation listing
def conversations_page(
    user: User, cursor: str | None = None, limit: int = 25
) -> Results[Row]:
    return (
        Query(KINDS.message_conversations)
        .filter(Filter().eq("visible_to", user.key))
        .order("-last_activity")
        .limit(limit)
        .cursor(cursor)
        .fetch()
    )


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::conversation_history
# @reason indexed query plumbing is exercised through bounded history
def messages_page(
    conversation: Row, cursor: str | None = None, limit: int = 50
) -> Results[Row]:
    return (
        Query(KINDS.messages, ancestor=conversation.key)
        .order("-sequence")
        .limit(limit)
        .cursor(cursor)
        .fetch()
    )


# @testable false
# @covered-by lagniappe/core/mutations/delete.py::DeleteCollector.user_messages
# @reason user-deletion lookup is exercised through the delete mutation plan
def message_conversation_keys(participant: Identifier) -> list[Key]:
    participant_key = datastore_key(participant)
    if not participant_key:
        return []
    records = (
        Query(KINDS.message_conversations)
        .filter(Filter().eq("participants", participant_key))
        .keys_only()
        .fetch_all()
    )
    return [stored_key(record) for record in records]


# @testable false
# @covered-by lagniappe/core/mutations/delete.py::DeleteCollector.finalize_message_conversations
# @reason orphan purging is exercised through the delete mutation plan
def message_keys(conversation: Identifier) -> list[Key]:
    current_key = datastore_key(conversation)
    if not current_key:
        return []
    records = (
        Query(KINDS.messages)
        .ancestor(current_key)
        .keys_only()
        .fetch_all()
    )
    return [stored_key(record) for record in records]
