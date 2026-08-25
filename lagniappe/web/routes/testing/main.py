"""Private bootstrap and request gate for the hosted E2E version."""

from __future__ import annotations

import hashlib

from flask import abort, jsonify, make_response, request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from config.hosted_e2e import is_reserved_hosted_e2e_hostname
from lagniappe import CONFIG
from lagniappe.core.tools.hosted_e2e.lease import (
    bind_e2e_deployment,
    consume_e2e_bootstrap_token,
    e2e_deployment_lease_active,
)
from lagniappe.core.tools.hosted_e2e.auth import (
    HOSTED_E2E_COOKIE,
    HOSTED_E2E_COOKIE_MAX_AGE,
    HostedE2EAuthenticationError,
    load_hosted_e2e_cookie,
    sign_hosted_e2e_cookie,
    validate_google_claims,
)

from . import testing


PUBLIC_ENDPOINTS = frozenset({"testing.health", "testing.create_session"})


# @testable false
# @covered-by lagniappe/web/routes/testing/main.py::require_hosted_e2e_session
# @reason concealment response helper owned by the hosted request gate
def _hidden():
    return abort(404)


# @testable false
# @covered-by config/hosted_e2e.py::is_reserved_hosted_e2e_hostname
# @reason response marker is verified by the hosted lifecycle preflight
def _soft_route_hidden():
    response = make_response("", 404)
    response.headers["X-Lagniappe-Hosted-E2E-Guard"] = "active"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return response


# @testable false
# @covered-by lagniappe/web/routes/testing/main.py::create_session
# @reason header parsing is exercised through the deployed Google OIDC exchange
def _bearer_token() -> str | None:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


# @testable infrastructure
# @matrix hosted-e2e : authentication internal-callback
def _valid_internal_process_request() -> bool:
    """Allow the app's own OIDC-authenticated task callbacks through the gate."""
    if request.method != "POST" or not request.path.startswith("/process/"):
        return False
    token = _bearer_token()
    if token is None:
        return False
    try:
        claims = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=request.url,
        )
        validate_google_claims(
            claims,
            audience=request.url,
            caller_email=CONFIG.INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL,
        )
        if not e2e_deployment_lease_active(
            CONFIG.HOSTED_E2E_VERSION,
            CONFIG.HOSTED_E2E_SOURCE,
        ):
            return False
    except Exception:
        return False
    return True


# @testable infrastructure
# @matrix hosted-e2e : authentication deployment-binding lease request-gate
@testing.before_app_request
def require_hosted_e2e_session():
    """Hide every dynamic/static Flask request without an active run cookie."""
    if not CONFIG.hosted_e2e_server:
        hostname = request.host.partition(":")[0]
        if is_reserved_hosted_e2e_hostname(hostname):
            return _soft_route_hidden()
        return None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if _valid_internal_process_request():
        return None
    try:
        payload = load_hosted_e2e_cookie(
            CONFIG.HOSTED_E2E_SESSION_KEY,
            request.cookies.get(HOSTED_E2E_COOKIE, ""),
            version=CONFIG.HOSTED_E2E_VERSION,
            source=CONFIG.HOSTED_E2E_SOURCE,
        )
        if not e2e_deployment_lease_active(
            CONFIG.HOSTED_E2E_VERSION,
            CONFIG.HOSTED_E2E_SOURCE,
            run_id=payload["run_id"],
        ):
            raise HostedE2EAuthenticationError(
                "Hosted E2E run no longer owns the shared lease."
            )
    except Exception:
        return _hidden()
    return None


# @testable infrastructure
# @matrix hosted-e2e : deployment-binding readiness
@testing.route("/health", methods=["GET"])
def health():
    """Expose only non-secret identity needed to validate a fresh version."""
    if not CONFIG.hosted_e2e_server:
        return _hidden()
    response = jsonify(
        {
            "ready": True,
            "service": CONFIG.HOSTED_E2E_SERVICE,
            "version": CONFIG.HOSTED_E2E_VERSION,
            "source": CONFIG.HOSTED_E2E_SOURCE,
            "source_snapshot": CONFIG.HOSTED_E2E_SOURCE_SNAPSHOT,
            "build_id": CONFIG.HOSTED_E2E_BUILD_ID,
        }
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


# @testable infrastructure
# @matrix hosted-e2e : authentication bootstrap cookie replay
@testing.route("/session", methods=["POST"])
def create_session():
    """Exchange one Google ID token for a run- and version-bound cookie."""
    if not CONFIG.hosted_e2e_server:
        return _hidden()
    token = _bearer_token()
    payload = request.get_json(silent=True)
    if token is None or not isinstance(payload, dict):
        return _hidden()
    if set(payload) != {"run_id", "version", "source"}:
        return _hidden()
    if (
        payload.get("version") != CONFIG.HOSTED_E2E_VERSION
        or payload.get("source") != CONFIG.HOSTED_E2E_SOURCE
    ):
        return _hidden()
    try:
        claims = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=CONFIG.BASE_URL,
        )
        validate_google_claims(
            claims,
            audience=CONFIG.BASE_URL,
            caller_email=CONFIG.HOSTED_E2E_CALLER_EMAIL,
        )
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not consume_e2e_bootstrap_token(token_digest, payload["run_id"]):
            return _hidden()
        if not bind_e2e_deployment(
            payload["run_id"],
            payload["version"],
            payload["source"],
        ):
            return _hidden()
        cookie = sign_hosted_e2e_cookie(
            CONFIG.HOSTED_E2E_SESSION_KEY,
            run_id=payload["run_id"],
            version=payload["version"],
            source=payload["source"],
        )
    except Exception:
        return _hidden()

    response = make_response("", 204)
    response.set_cookie(
        HOSTED_E2E_COOKIE,
        cookie,
        max_age=HOSTED_E2E_COOKIE_MAX_AGE,
        secure=True,
        httponly=True,
        samesite="Strict",
        path="/",
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
