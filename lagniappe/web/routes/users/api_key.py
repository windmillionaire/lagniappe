"""Browser-session controls for the user's external-agent API credential."""

from flask import abort, g, request
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import AI
from lagniappe.core.tools.auth import agent_api
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip
from lagniappe.web import responses
from lagniappe.web.auth import ai_access

from . import users


# @testable false
# @covered-by lagniappe/web/routes/users/api_key.py::api_key
# @reason fail-closed feature normalization is exercised at the route boundary
def _feature_enabled():
    value = getattr(CONFIG, "EXTERNAL_AGENT_API_ENABLED", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


# @testable false
# @covered-by lagniappe/web/routes/users/api_key.py::api_key
# @reason user eligibility is owned by the public key-management route
def _enabled_actor():
    if not _feature_enabled():
        abort(404)
    if getattr(current_user, "is_public", False):
        abort(403)
    g.NO_CACHE = True
    return current_user._get_current_object()


# @testable false
# @covered-by lagniappe/web/routes/users/api_key.py::api_key
# @reason shared rate-limiter plumbing is owned by the key-management route
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


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_user_can_rotate_and_revoke_external_agent_api_key
# @matrix agent-api user-settings : expiry revoke rotate shown-once
@users.route("/me/api-key", methods=["GET", "POST", "DELETE"])
@ai_access(AI.CREATE)
def api_key():
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
