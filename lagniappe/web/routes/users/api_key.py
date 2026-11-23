"""Browser-session controls for the user's external-agent API credential."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

from flask import abort, g, request
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.tools.auth import agent_api
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip
from lagniappe.web import responses
from lagniappe.web.auth import authenticated_user, logged_in

from . import users


def _enabled_actor():
    if (
        not CONFIG.AI_ENABLED
        or not CONFIG.EXTERNAL_AI_ENABLED
        or getattr(current_user, "is_public", False)
    ):
        abort(403)
    g.NO_CACHE = True
    return authenticated_user()


def _rotation_limit(actor):
    try:
        state = check_limit(
            "agent-api-key-rotation",
            f"{actor.urlsafe_key}:{client_ip(request)}",
            5,
            60 * 60,
        )
    except Exception as error:
        exceptions.capture(
            error,
            context={"agent_api": {"phase": "browser_key_rotation_limit"}},
        )
        return responses.json_response(
            {"error": "API key management is temporarily unavailable."},
            503,
        )
    if not state["allowed"]:
        response, status = responses.json_response(
            {"error": "Too many API key changes. Try again later."},
            429,
        )
        response.headers["Retry-After"] = str(max(state["retry_after"], 1))
        return response, status
    return None


@users.route("/me/api-key", methods=["GET", "POST", "DELETE"])
@logged_in
def api_key() -> ResponseReturnValue:
    """Inspect, rotate, or revoke the current user's single API credential."""
    actor = _enabled_actor()
    if request.method == "GET":
        return responses.json_response(
            {"credential": agent_api.credential_status(actor)}
        )

    limited = _rotation_limit(actor)
    if limited:
        return limited
    if request.method == "DELETE":
        return responses.json_response(
            {"credential": agent_api.revoke_credential(actor)}
        )

    token, metadata = agent_api.issue_credential(actor)
    return responses.json_response(
        {
            "credential": metadata,
            "token": token,
            "shown_once": True,
        },
        201,
    )
