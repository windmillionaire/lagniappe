"""Participant-authorized direct-message reads and browser projections."""

from ...definitions import Fetch
from ...entities import Entities
from ...properties import message as message_values
from ...properties import message_conversation as conversation_values
from .. import collaboration, database
from ..database import messaging as message_database


CONVERSATION_PAGE_SIZE = 25
HISTORY_PAGE_SIZE = 50


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::conversations
# @reason peer availability batching is exercised through list and history projections
def _peer_status(rows, user):
    peers = {
        conversation_values.peer_key(row, user)
        for row in rows
        if conversation_values.peer_key(row, user) is not None
    }
    loaded = {
        entity.key: entity
        for entity in Entities.fetch(*peers, request=Fetch.direct())
        if isinstance(entity, Entities.USER)
    }
    return {
        key: {
            "peer_available": bool(
                loaded.get(key)
                and collaboration.recipient_allowed(
                    user, loaded[key], channel="message"
                )
            ),
            "peer_replyable": bool(
                loaded.get(key) and collaboration.managed_user(loaded[key])
            ),
            "peer_deleted": key not in loaded,
        }
        for key in peers
    }


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::conversations
# @reason browser projection is exercised through conversation listing
def serialize_conversation(
    conversation,
    user,
    *,
    peer_available=True,
    peer_replyable=True,
    peer_deleted=False,
):
    user_id = conversation_values.participant_id(user)
    peer_key = conversation_values.peer_key(conversation, user)
    peer_id = conversation_values.encoded_identifier(peer_key) if peer_key else None
    names = conversation.get("participant_names") or {}
    return {
        "id": conversation_values.encoded_identifier(conversation.key),
        "peer": {
            "id": peer_id,
            "name": names.get(peer_id) or "Deleted user",
            "available": bool(peer_available),
            "replyable": bool(peer_replyable),
            "deleted": bool(peer_deleted),
        },
        "last_activity": (
            conversation.get("last_activity").isoformat()
            if conversation.get("last_activity")
            else None
        ),
        "last_sender": conversation_values.encoded_identifier(
            conversation.get("last_sender")
        )
        if conversation.get("last_sender")
        else None,
        "unread": int((conversation.get("unread_counts") or {}).get(user_id) or 0),
        "revision": int(conversation.get("revision") or 0),
        "sequence": int(conversation.get("sequence") or 0),
    }


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::conversation_history
# @reason browser projection is exercised through chronological history
def serialize_message(message, viewer):
    return message_values.projection(message, viewer)


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @matrix messaging : compose-eligibility conversation-page
def conversations(user, cursor=None, limit=CONVERSATION_PAGE_SIZE):
    if not collaboration.managed_user(user):
        raise PermissionError("Messaging is available to managed users only.")
    page = database.conversations_page(user, cursor, limit)
    rows = list(page)
    peer_status = _peer_status(rows, user)
    unavailable = {
        "peer_available": False,
        "peer_replyable": False,
        "peer_deleted": True,
    }
    return {
        "conversations": [
            serialize_conversation(
                row,
                user,
                **peer_status.get(
                    conversation_values.peer_key(row, user), unavailable
                ),
            )
            for row in rows
        ],
        "cursor": page.next_cursor,
    }


# @testable false
# @covered-by lagniappe/core/tools/messaging/views.py::conversation_history
# @reason authorized lookup is exercised through history
def get_conversation(user, conversation_identifier):
    conversation = database.get_conversation(conversation_identifier)
    message_database.require_participant(conversation, user)
    return conversation


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @matrix messaging : chronological-display history-page
def conversation_history(
    user,
    conversation_identifier,
    cursor=None,
    limit=HISTORY_PAGE_SIZE,
):
    conversation = get_conversation(user, conversation_identifier)
    peer_key = conversation_values.peer_key(conversation, user)
    peer_status = _peer_status([conversation], user).get(
        peer_key,
        {
            "peer_available": False,
            "peer_replyable": False,
            "peer_deleted": True,
        },
    )
    user_id = conversation_values.participant_id(user)
    cleared = int((conversation.get("cleared_through") or {}).get(user_id) or 0)
    visible = []
    next_cursor = cursor
    exhausted = False
    while len(visible) < limit and not exhausted:
        requested = max(limit, limit - len(visible))
        page = database.messages_page(conversation, next_cursor, requested)
        next_cursor = page.next_cursor
        for row in page:
            if int(row.get("sequence") or 0) <= cleared:
                exhausted = True
                break
            if user.key not in set(row.get("hidden_for") or ()):
                visible.append(row)
                if len(visible) == limit:
                    break
        if not page.next_cursor:
            exhausted = True
    return {
        "conversation": serialize_conversation(conversation, user, **peer_status),
        "messages": [serialize_message(row, user) for row in reversed(visible)],
        "cursor": None if exhausted else next_cursor,
    }
