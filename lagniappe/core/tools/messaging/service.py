"""Authorization and post-commit orchestration for direct messages."""

from ...definitions import MessageRevisionConflict
from ...properties import message as message_values
from ...properties import message_conversation as conversation_values
from .. import collaboration, database
from ..email.notifications import capture as email_capture
from ..notifications import service as notification_service
from . import views


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pairs messaging:idempotency messaging:compose-eligibility messaging:reply-permission
# @pair messaging:new-after-clear
def send_message(
    actor,
    recipient_identifier,
    body,
    operation_id,
    conversation_identifier=None,
):
    recipient = collaboration.resolve_user(recipient_identifier)
    if not recipient:
        raise PermissionError("Recipient is not eligible for messages.")
    can_initiate = collaboration.recipient_allowed(actor, recipient, channel="message")
    reply_key = (
        database.get.datastore_key(conversation_identifier)
        if conversation_identifier
        else None
    )
    reply_matches = bool(
        reply_key and reply_key == database.conversation_key(actor, recipient)
    )
    if conversation_identifier and not reply_matches:
        raise PermissionError("Conversation is unavailable.")
    if not can_initiate and not reply_matches:
        raise PermissionError("Recipient is not eligible for messages.")
    body = message_values.normalize_body(body)
    operation_id = message_values.normalize_operation_id(operation_id)
    database.ensure_notification_aggregate(recipient)
    message, conversation, aggregate, created = database.send_message_record(
        actor,
        recipient,
        body,
        operation_id,
        require_existing=not can_initiate,
    )
    if aggregate is not None:
        notification_service.publish_notification_aggregate(recipient, aggregate)
    if created:
        try:
            email_capture.record_message(message, conversation, recipient)
        except Exception as error:
            from ...exceptions import capture

            capture(error, context={"operation": "message-email-capture"})
    return {
        "message": views.serialize_message(message, actor),
        "conversation": views.serialize_conversation(conversation, actor),
        "created": created,
    }


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pair messaging:read-race
def mark_read(user, conversation_identifier, expected_revision=None):
    key = database.get.datastore_key(conversation_identifier)
    if not key:
        raise ValueError("Conversation key is invalid.")
    database.ensure_notification_aggregate(user)
    try:
        conversation, aggregate = database.mark_conversation_read(
            user, key, expected_revision
        )
    except MessageRevisionConflict as error:
        error.conversation = views.serialize_conversation(error.conversation, user)
        raise
    if aggregate is not None:
        notification_service.publish_notification_aggregate(user, aggregate)
    peer_key = conversation_values.peer_key(conversation, user)
    peer_status = views._peer_status([conversation], user).get(
        peer_key,
        {
            "peer_available": False,
            "peer_replyable": False,
            "peer_deleted": True,
        },
    )
    return views.serialize_conversation(conversation, user, **peer_status)


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pair messaging:per-copy-delete
def hide_message(user, message_identifier):
    key = database.get.datastore_key(message_identifier)
    if not key:
        raise ValueError("Message key is invalid.")
    database.ensure_notification_aggregate(user)
    conversation, aggregate = database.hide_message_for_user(user, key)
    if aggregate is not None:
        notification_service.publish_notification_aggregate(user, aggregate)
    return bool(conversation)


# @testable true
# @tests tests_unit/test_027b_messaging_service.py::test_message_transactions_are_idempotent_and_keep_exact_unread_counts
# @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
# @pair messaging:clear-horizon
def clear_conversation(user, conversation_identifier):
    key = database.get.datastore_key(conversation_identifier)
    if not key:
        raise ValueError("Conversation key is invalid.")
    database.ensure_notification_aggregate(user)
    conversation, aggregate = database.clear_message_conversation(user, key)
    if aggregate is not None:
        notification_service.publish_notification_aggregate(user, aggregate)
    return views.serialize_conversation(conversation, user)
