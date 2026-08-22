"""Managed-user messaging page and JSON endpoints."""

from flask import g, request
from flask_login import current_user

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.definitions import MessageConflict, MessageRevisionConflict
from lagniappe.core.tools import collaboration
from lagniappe.core.tools.messaging import service as message_service
from lagniappe.core.tools.messaging import views as message_views
from lagniappe.web import responses
from lagniappe.web.auth import abort_public_user_action, logged_in

from . import message_internal, messages


# @testable infrastructure
def _managed_only():
    abort_public_user_action()


# @testable infrastructure
@messages.route("")
@messages.route("/")
@logged_in
def index():
    _managed_only()
    g.NO_CACHE = True
    return responses.message_page(
        initial_conversation=request.args.get("with"),
        can_message=collaboration.can_initiate_messages(current_user),
    )


# @testable infrastructure
@message_internal.route("/conversations")
@logged_in
def conversations():
    _managed_only()
    g.NO_CACHE = True
    return responses.json_response(
        message_views.conversations(current_user, request.args.get("cursor"))
    )


# @testable infrastructure
@message_internal.route("/conversations/<key>")
@logged_in
def history(key):
    _managed_only()
    g.NO_CACHE = True
    try:
        payload = message_views.conversation_history(
            current_user,
            key,
            request.args.get("cursor"),
        )
    except PermissionError:
        return responses.json_response({"error": "Conversation not found."}, 404)
    return responses.json_response(payload)


# @testable infrastructure
@message_internal.route("/conversations/<key>/delete")
@logged_in
def clear_modal(key):
    _managed_only()
    g.NO_CACHE = True
    try:
        conversation = message_views.get_conversation(current_user, key)
    except PermissionError:
        return responses.json_response({"error": "Conversation not found."}, 404)
    peer_name = message_views.serialize_conversation(
        conversation, current_user
    )["peer"]["name"]
    return responses.message_clear_modal(key, peer_name=peer_name)


# @testable infrastructure
@message_internal.route("", methods=["POST"])
@logged_in
def send():
    _managed_only()
    try:
        payload = message_service.send_message(
            current_user,
            request.form.get("recipient"),
            request.form.get("body"),
            request.form.get("operation_id"),
            request.form.get("conversation"),
        )
    except PermissionError as error:
        return responses.json_response({"error": str(error)}, 403)
    except ValidationError as error:
        return responses.json_response({"error": str(error)}, 422)
    except MessageConflict as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.json_response(payload, status=201 if payload["created"] else 200)


# @testable infrastructure
@message_internal.route("/conversations/<key>/read", methods=["POST"])
@logged_in
def read(key):
    _managed_only()
    revision = request.form.get("revision")
    try:
        conversation = message_service.mark_read(
            current_user,
            key,
            expected_revision=int(revision) if revision not in {None, ""} else None,
        )
    except (PermissionError, ValueError):
        return responses.json_response({"error": "Conversation not found."}, 404)
    except MessageRevisionConflict as error:
        return responses.json_response(
            {"error": str(error), "conversation": error.conversation}, 409
        )
    return responses.json_response({"conversation": conversation})


# @testable infrastructure
@message_internal.route("/<key>", methods=["DELETE"])
@logged_in
def hide_message(key):
    _managed_only()
    try:
        found = message_service.hide_message(current_user, key)
    except PermissionError:
        return responses.json_response({"error": "Message not found."}, 404)
    if not found:
        return responses.json_response({"error": "Message not found."}, 404)
    return responses.json_response({"deleted": True})


# @testable infrastructure
@message_internal.route("/conversations/<key>", methods=["DELETE"])
@logged_in
def clear(key):
    _managed_only()
    try:
        conversation = message_service.clear_conversation(current_user, key)
    except (PermissionError, ValueError):
        return responses.json_response({"error": "Conversation not found."}, 404)
    return responses.json_response({"conversation": conversation})
