"""Browser-consent and public-client OAuth boundary for remote MCP."""

from urllib.parse import urlencode

from flask import (
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from config.remote_mcp import CLIENT_ID, CODEX_CLIENT_ID, PENDING_SECONDS, mcp_issuer
from lagniappe import CONFIG
from lagniappe.core.tools.auth import remote_mcp as auth
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip

from . import oauth, oauth_metadata


_PENDING_COOKIE = "__Secure-lagniappe-mcp-pending"


# @testable false
# @covered-by lagniappe/web/routes/oauth/main.py::authorize
@oauth.before_request
def guard():
    g.NO_CACHE = True
    request.max_content_length = 16 * 1024
    if (
        not CONFIG.AI_ENABLED or not CONFIG.EXTERNAL_AI_ENABLED
        or not CONFIG.MCP_RESOURCE or not CONFIG.MCP_SERVICE_ACCOUNT
        or request.host_url.rstrip("/") != mcp_issuer(vars(CONFIG))
    ):
        abort(404)
    if request.content_length and request.content_length > 16 * 1024:
        abort(413)
    try:
        result = check_limit("remote-mcp-oauth", client_ip(request), 60, 60)
    except Exception:
        raise auth.OAuthError("temporarily_unavailable", 503) from None
    if not result["allowed"]:
        response = jsonify(error="temporarily_unavailable")
        response.status_code = 429
        response.headers["Retry-After"] = str(max(result["retry_after"], 1))
        return response


# @testable false
# @covered-by lagniappe/web/routes/oauth/main.py::authorize
@oauth.errorhandler(auth.OAuthError)
def oauth_error(error):
    # Codes come from our closed vocabulary; no provider exception or form value.
    auth.log_outcome(error.code)
    if request.endpoint in {"oauth.token", "oauth.revoke"}:
        return jsonify(error=error.code), error.status
    return render_template("oauth/connection.html", error=True), error.status


# @testable false
# @covered-by lagniappe/web/routes/oauth/main.py::token
def _parameters(values):
    if len(values) > 16 or any(len(values.getlist(key)) != 1 for key in values):
        raise auth.OAuthError("invalid_request")
    return values.to_dict()


# @testable true
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_metadata_login_consent_and_csrf
# @matrix mcp-oauth : discovery site-policy
@oauth_metadata.route("/oauth-authorization-server")
def metadata():
    g.NO_CACHE = True
    if (
        not CONFIG.AI_ENABLED or not CONFIG.EXTERNAL_AI_ENABLED
        or not CONFIG.MCP_RESOURCE or not CONFIG.MCP_SERVICE_ACCOUNT
    ):
        abort(404)
    issuer = mcp_issuer(vars(CONFIG))
    return jsonify(
        issuer=issuer,
        authorization_endpoint=issuer + "/oauth/authorize",
        token_endpoint=issuer + "/oauth/token",
        revocation_endpoint=issuer + "/oauth/revoke",
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=["none"],
        client_id_metadata_document_supported=True,
        authorization_response_iss_parameter_supported=True,
    )


# @testable true
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_codex_browser_consent_names_client_and_revokes_only_its_connection
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_metadata_login_consent_and_csrf
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_consent_rejects_replaced_request_and_changed_account
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_pending_survives_google_callback_session_replacement
# @matrix mcp-oauth : consent csrf login redirect loopback client-isolation
# @pair mcp-oauth:consent-binding
# @pair mcp-oauth:login-continuation
@oauth.route("/authorize", methods=["GET", "POST"])
def authorize():
    if request.method == "GET" and request.args:
        pending = auth.begin_authorization(_parameters(request.args))
        # Remove OAuth parameters from the address bar before login or consent.
        # Google redirect login posts across sites and replaces the Lax Flask
        # session. This separate cookie survives, then returns on the consent GET.
        response = redirect(url_for("oauth.authorize"), code=303)
        response.set_cookie(
            _PENDING_COOKIE,
            pending,
            max_age=PENDING_SECONDS,
            path="/oauth",
            secure=True,
            httponly=True,
            samesite="Lax",
        )
        return response
    pending = request.cookies.get(_PENDING_COOKIE)
    pending_request = auth.pending_authorization(pending)
    if not current_user.is_authenticated:
        return redirect(url_for("users.login", next=url_for("oauth.authorize")))
    user = current_user._get_current_object()
    if not auth.eligible_user(user):
        raise auth.OAuthError("access_denied", 403)
    if request.method == "POST":
        form = _parameters(request.form)
        decision = form.get("decision")
        if (
            decision not in {"allow", "deny"}
            or form.get("pending") != pending
            or form.get("user_id") != user.get_id()
        ):
            raise auth.OAuthError("invalid_request")
        target, parameters = auth.consent(pending, user, allow=decision == "allow")
        auth.log_outcome("consent_allowed" if decision == "allow" else "consent_denied")
        response = redirect(target + "?" + urlencode(parameters), code=303)
        response.delete_cookie(
            _PENDING_COOKIE,
            path="/oauth",
            secure=True,
            httponly=True,
            samesite="Lax",
        )
        return response
    return render_template(
        "oauth/connection.html",
        consent=True,
        pending=pending,
        resource=CONFIG.MCP_RESOURCE,
        client_name="Codex" if pending_request["client_id"] == CODEX_CLIENT_ID else "ChatGPT",
    )


# @testable false
# @covered-by lagniappe/web/routes/oauth/main.py::token
def _public_client_form():
    if request.mimetype != "application/x-www-form-urlencoded" or request.query_string:
        raise auth.OAuthError("invalid_request")
    parameters = _parameters(request.form)
    if request.headers.get("Authorization") or any(
        key in parameters
        for key in ("client_secret", "client_assertion", "client_assertion_type")
    ):
        raise auth.OAuthError("invalid_client")
    return parameters


# @testable true
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_token_api_envelope_and_browser_revocation
# @matrix mcp-oauth : token csrf-exemption
@oauth.route("/token", methods=["POST"])
def token():
    result = auth.exchange_token(_public_client_form())
    auth.log_outcome("token_issued")
    response = jsonify(result)
    response.headers["Pragma"] = "no-cache"
    return response


# @testable true
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_token_api_envelope_and_browser_revocation
# @matrix mcp-oauth : revocation csrf-exemption
@oauth.route("/revoke", methods=["POST"])
def revoke():
    parameters = _public_client_form()
    auth.revoke_token(parameters.get("token"), parameters.get("client_id"))
    return "", 200


# @testable true
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_codex_browser_consent_names_client_and_revokes_only_its_connection
# @tests tests_e2e/013_agent_api/test_013d_remote_mcp_oauth.py::test_oauth_token_api_envelope_and_browser_revocation
# @matrix mcp-oauth : revocation csrf browser-settings client-isolation
@oauth.route("/connection", methods=["GET", "POST"])
def connection():
    if not current_user.is_authenticated:
        return redirect(url_for("users.login", next=url_for("oauth.connection")))
    user = current_user._get_current_object()
    if request.method == "POST":
        parameters = _parameters(request.form)
        auth.connection_status(
            user, client_id=parameters.get("client_id", CLIENT_ID), revoke=True
        )
    clients = [(CLIENT_ID, "ChatGPT"), (CODEX_CLIENT_ID, "Codex")]
    connections = [
        {"client_id": client_id, "name": name, **auth.connection_status(user, client_id=client_id)}
        for client_id, name in clients
    ]
    return render_template("oauth/connection.html", connections=connections)
