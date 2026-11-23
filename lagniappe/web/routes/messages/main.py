"""Managed-user messaging page and JSON endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import g, request

from lagniappe.core.exceptions import ValidationError
from lagniappe.core.definitions import MessageConflict, MessageRevisionConflict
from lagniappe.core.tools import collaboration
from lagniappe.core.tools.messaging import service as message_service
from lagniappe.core.tools.messaging import views as message_views
from lagniappe.web import responses
from lagniappe.web.auth import authenticated_user, abort_public_user_action, logged_in

from . import message_internal, messages


def _managed_only():
    abort_public_user_action()


@messages.route("")
@messages.route("/")
@logged_in
def index() -> ResponseReturnValue:
    _managed_only()
    g.NO_CACHE = True
    return responses.message_page(
        initial_conversation=request.args.get("with"),
        can_message=collaboration.can_initiate_messages(authenticated_user()),
    )


@message_internal.route("/conversations")
@logged_in
def conversations() -> ResponseReturnValue:
    _managed_only()
    g.NO_CACHE = True
    return responses.json_response(
        message_views.conversations(authenticated_user(), request.args.get("cursor"))
    )


@message_internal.route("/conversations/<key>")
@logged_in
def history(key: str) -> ResponseReturnValue:
    _managed_only()
    g.NO_CACHE = True
    try:
        payload = message_views.conversation_history(
            authenticated_user(),
            key,
            request.args.get("cursor"),
        )
    except PermissionError:
        return responses.json_response({"error": "Conversation not found."}, 404)
    return responses.json_response(payload)


@message_internal.route("/conversations/<key>/delete")
@logged_in
def clear_modal(key: str) -> ResponseReturnValue:
    _managed_only()
    g.NO_CACHE = True
    try:
        conversation = message_views.get_conversation(authenticated_user(), key)
    except PermissionError:
        return responses.json_response({"error": "Conversation not found."}, 404)
    peer_name = message_views.serialize_conversation(
        conversation, authenticated_user()
    )["peer"]["name"]
    return responses.message_clear_modal(key, peer_name=peer_name)


@message_internal.route("", methods=["POST"])
@logged_in
def send() -> ResponseReturnValue:
    _managed_only()
    try:
        payload = message_service.send_message(
            authenticated_user(),
            request.form.get("recipient", ""),
            request.form.get("body", ""),
            request.form.get("operation_id", ""),
            request.form.get("conversation"),
        )
    except PermissionError as error:
        return responses.json_response({"error": str(error)}, 403)
    except ValidationError as error:
        return responses.json_response({"error": str(error)}, 422)
    except MessageConflict as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.json_response(payload, status=201 if payload["created"] else 200)


@message_internal.route("/conversations/<key>/read", methods=["POST"])
@logged_in
def read(key: str) -> ResponseReturnValue:
    _managed_only()
    revision = request.form.get("revision")
    try:
        conversation = message_service.mark_read(
            authenticated_user(),
            key,
            expected_revision=int(revision) if revision else None,
        )
    except (PermissionError, ValueError):
        return responses.json_response({"error": "Conversation not found."}, 404)
    except MessageRevisionConflict as error:
        return responses.json_response(
            {"error": str(error), "conversation": error.conversation}, 409
        )
    return responses.json_response({"conversation": conversation})


@message_internal.route("/<key>", methods=["DELETE"])
@logged_in
def hide_message(key: str) -> ResponseReturnValue:
    _managed_only()
    try:
        found = message_service.hide_message(authenticated_user(), key)
    except PermissionError:
        return responses.json_response({"error": "Message not found."}, 404)
    if not found:
        return responses.json_response({"error": "Message not found."}, 404)
    return responses.json_response({"deleted": True})


@message_internal.route("/conversations/<key>", methods=["DELETE"])
@logged_in
def clear(key: str) -> ResponseReturnValue:
    _managed_only()
    try:
        conversation = message_service.clear_conversation(authenticated_user(), key)
    except (PermissionError, ValueError):
        return responses.json_response({"error": "Conversation not found."}, 404)
    return responses.json_response({"conversation": conversation})
