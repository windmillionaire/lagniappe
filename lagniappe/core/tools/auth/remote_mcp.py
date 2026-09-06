"""ChatGPT and Codex OAuth service, using opaque secrets and current User permissions."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from types import SimpleNamespace

from google.oauth2 import id_token

from config.remote_mcp import (
    ACCESS_SECONDS,
    CODE_SECONDS,
    CODEX_CLIENT_ID,
    client_allowed,
    redirect_allowed,
    PENDING_SECONDS,
    REFRESH_SECONDS,
    SCOPE,
)
from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.auth.agent_api import credential_id
from lagniappe.core.tools.database import remote_mcp as store
from lagniappe.core.tools.http.client import fetch_user_content
from lagniappe.core.tools.http.models import UserFetchPolicy


_TOKEN = re.compile(r"lgmo_([pcar])_[A-Za-z0-9_-]{43}")
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")
_CLIENT_POLICY = UserFetchPolicy(
    name="chatgpt_cimd",
    schemes=frozenset({"https"}),
    accepted_media_types=frozenset({"application/json"}),
    max_bytes=32 * 1024,
    max_redirects=0,
    connect_timeout=3,
    read_timeout=5,
    deadline=10,
)
_client_cache = None
_client_lock = threading.Lock()
_CERTIFICATE_URL = "https://www.googleapis.com/oauth2/v1/certs"
_CERTIFICATE_POLICY = UserFetchPolicy(
    name="google_oidc_certificates",
    schemes=frozenset({"https"}),
    accepted_media_types=frozenset({"application/json"}),
    max_bytes=64 * 1024,
    max_redirects=0,
    connect_timeout=2,
    read_timeout=3,
    deadline=5,
)
_certificate_cache = None
_certificate_lock = threading.Lock()
_LOG_OUTCOMES = frozenset({
    "workload_verified", "consent_allowed", "consent_denied", "token_issued",
    "invalid_grant", "temporarily_unavailable", "invalid_client", "invalid_request",
    "unsupported_response_type", "invalid_target", "invalid_scope", "access_denied",
    "unsupported_grant_type",
})
LOGGER = logging.getLogger("lagniappe.remote_mcp")
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False
if not LOGGER.handlers:
    _outcome_handler = logging.StreamHandler()
    _outcome_handler.setFormatter(logging.Formatter(
        '{"severity":"INFO","event":"remote_mcp_auth","outcome":"%(message)s"}'
    ))
    LOGGER.addHandler(_outcome_handler)


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_oauth_outcomes_log_only_closed_categories_after_workload_verification
# @matrix mcp-oauth : observability privacy
def log_outcome(outcome):
    """Emit only a fixed outcome category through this subsystem's own handler."""
    if isinstance(outcome, str) and outcome in _LOG_OUTCOMES:
        LOGGER.info(outcome)


# @testable infrastructure
class OAuthError(ValueError):
    def __init__(self, code="invalid_grant", status=400):
        super().__init__(code)
        self.code = code
        self.status = status


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
def settings():
    value = CONFIG.REMOTE_MCP
    if not CONFIG.AI_ENABLED or not CONFIG.EXTERNAL_AI_ENABLED or not value.get("enabled"):
        raise OAuthError("temporarily_unavailable", 503)
    return value


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
def _now(now=None):
    return now or datetime.now(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
def _secret(kind):
    return f"lgmo_{kind}_{secrets.token_urlsafe(32)}"


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
def _name(token, kind):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token) or token[5] != kind:
        raise OAuthError()
    return f"{kind}-{hashlib.sha256(token.encode('ascii')).hexdigest()}"


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
def _live(row, now):
    return bool(
        row
        and not row.get("revoked")
        and isinstance(row.get("expires_at"), datetime)
        and row["expires_at"] > now
    )


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
def _bound(row, config):
    return (
        all(row.get(key) == config[key] for key in ("issuer", "resource"))
        and client_allowed(config, row.get("client_id"))
        and row.get("scope") == SCOPE
    )


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_oauth_user_and_workload_identity_are_both_required
# @matrix mcp-oauth : allowlist user-binding site-policy optional-actors
def eligible_user(user):
    config = settings()
    return bool(
        isinstance(user, Entities.USER)
        and user.is_authenticated
        and user.is_active
        and not user.is_public
        and (config.get("actors") is None
             or (user.email or "").casefold() in config["actors"])
    )


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::authenticate_access
def _user(row):
    user = Entities.fetch_one(row.get("user"), request=Fetch.direct())
    if not eligible_user(user) or user.key != row.get("user"):
        raise OAuthError()
    return user


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::client_metadata
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::_certificate_request
# @reason duplicate JSON keys are rejected through both bounded metadata readers
def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate metadata field")
        value[key] = item
    return value


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_workload_certificates_are_bounded_cached_and_fail_closed
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_cached_certificates_still_verify_each_signature_and_user_grant
# @matrix mcp-oauth : oidc certificate-cache
def _certificate_request(url, method="GET"):
    """Adapt one bounded public certificate response to Google's verifier."""
    global _certificate_cache
    if url != _CERTIFICATE_URL or method != "GET":
        raise OAuthError()
    with _certificate_lock:
        if _certificate_cache and _certificate_cache[0] > time.monotonic():
            body = _certificate_cache[1]
        else:
            # A failed fetch also has a short cooldown; unauthenticated traffic
            # cannot turn an unavailable certificate endpoint into a fetch loop.
            try:
                result = fetch_user_content(_CERTIFICATE_URL, _CERTIFICATE_POLICY)
                if not result.ok or result.http_status != 200 or result.redirect_count:
                    raise ValueError()
                certificates = json.loads(result.body, object_pairs_hook=_unique_object)
                if (
                    not isinstance(certificates, dict)
                    or not 1 <= len(certificates) <= 16
                    or not all(
                        isinstance(value, str) for value in certificates.values()
                    )
                ):
                    raise ValueError()
            except Exception:
                _certificate_cache = (time.monotonic() + 5, None)
                raise OAuthError() from None
            body = result.body
            _certificate_cache = (time.monotonic() + 300, body)
        if body is None:
            raise OAuthError()
        return SimpleNamespace(status=200, data=body)


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_cimd_is_exact_bounded_cached_and_accepts_public_method_intersection
# @matrix mcp-oauth : cimd validation
def client_metadata(client_id):
    """Fetch only the configured ChatGPT document, with no DCR or client secret."""
    global _client_cache
    config = settings()
    if client_id != config["client_id"]:
        raise OAuthError("invalid_client")
    cache_key = (client_id, config["redirect_uri"])
    with _client_lock:
        if (
            _client_cache
            and _client_cache[0] == cache_key
            and _client_cache[1] > time.monotonic()
        ):
            return _client_cache[2]
        result = fetch_user_content(client_id, _CLIENT_POLICY)
        if not result.ok or result.http_status != 200 or result.redirect_count:
            raise OAuthError("temporarily_unavailable", 503)
        try:
            document = json.loads(result.body, object_pairs_hook=_unique_object)
            if not isinstance(document, dict):
                raise ValueError()
            methods = document.get("token_endpoint_auth_methods_supported")
            if methods is None:
                methods = [document.get("token_endpoint_auth_method", "none")]
            redirects = document.get("redirect_uris")
            grants = document.get("grant_types", ["authorization_code"])
            responses = document.get("response_types", ["code"])
            if (
                document.get("client_id") != client_id
                or not isinstance(methods, list)
                or "none" not in methods
                or not all(isinstance(item, str) for item in methods)
                or not isinstance(redirects, list)
                or config["redirect_uri"] not in redirects
                or not all(isinstance(item, str) for item in redirects)
                or not isinstance(grants, list)
                or "authorization_code" not in grants
                or not isinstance(responses, list)
                or "code" not in responses
            ):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise OAuthError("invalid_client") from None
        # Cache only the already validated, minimal public projection.
        metadata = {"client_id": client_id, "redirect_uri": config["redirect_uri"]}
        _client_cache = (cache_key, time.monotonic() + 300, metadata)
        return metadata


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_codex_loopback_grants_coexist_and_cannot_cross_clients
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_authorization_requires_exact_bindings_state_and_s256
# @matrix mcp-oauth : authorization validation loopback client-isolation
def begin_authorization(parameters, *, now=None):
    config = settings()
    if (
        not redirect_allowed(
            config, parameters.get("client_id"), parameters.get("redirect_uri")
        )
    ):
        raise OAuthError("invalid_client")
    required = {
        "response_type",
        "client_id",
        "redirect_uri",
        "resource",
        "scope",
        "state",
        "code_challenge",
        "code_challenge_method",
    }
    if not required <= parameters.keys():
        raise OAuthError("invalid_request")
    if parameters["response_type"] != "code":
        raise OAuthError("unsupported_response_type")
    if parameters["resource"] != config["resource"]:
        raise OAuthError("invalid_target")
    if parameters["scope"] != SCOPE:
        raise OAuthError("invalid_scope")
    if parameters["code_challenge_method"] != "S256" or not _CHALLENGE.fullmatch(
        parameters["code_challenge"]
    ):
        raise OAuthError("invalid_request")
    state = parameters["state"]
    if (
        not isinstance(state, str)
        or not 1 <= len(state) <= 1024
        or any(ord(char) < 32 or ord(char) == 127 for char in state)
    ):
        raise OAuthError("invalid_request")
    if parameters["client_id"] == config["client_id"]:
        client_metadata(parameters["client_id"])
    now = _now(now)
    pending = _secret("p")
    row = {key: parameters[key] for key in required}
    row.update(
        issuer=config["issuer"], expires_at=now + timedelta(seconds=PENDING_SECONDS)
    )
    store.atomic(lambda records: records.put(_name(pending, "p"), row))
    return pending


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::consent
def pending_authorization(pending, *, now=None):
    row = store.read(_name(pending, "p"))
    if not _live(row, _now(now)) or row.get("consumed") or not _bound(row, settings()):
        raise OAuthError("invalid_request")
    return row


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_codex_loopback_grants_coexist_and_cannot_cross_clients
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_code_is_single_use_and_refresh_replay_revokes_the_family
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_consent_deny_and_pending_replay_do_not_issue_tokens
# @matrix mcp-oauth : consent transaction client-isolation
def consent(pending, user, *, allow, now=None):
    if not eligible_user(user):
        raise OAuthError("access_denied", 403)
    now = _now(now)
    config = settings()
    code = _secret("c")

    # @testable false
    # @covered-by lagniappe/core/tools/auth/remote_mcp.py::consent
    # @reason atomic pending consumption and code creation are one consent transition
    def transition(records):
        name = _name(pending, "p")
        row = records.get(name)
        if not _live(row, now) or row.get("consumed") or not _bound(row, config):
            raise OAuthError("invalid_request")
        row = dict(row)
        row["consumed"] = True
        records.put(name, row)
        if allow:
            code_row = {
                key: row[key]
                for key in (
                    "client_id",
                    "redirect_uri",
                    "resource",
                    "scope",
                    "code_challenge",
                    "issuer",
                )
            }
            code_row.update(
                user=user.key, expires_at=now + timedelta(seconds=CODE_SECONDS)
            )
            records.put(_name(code, "c"), code_row)
        result = {"state": row["state"], "iss": config["issuer"]}
        result.update({"code": code} if allow else {"error": "access_denied"})
        return row["redirect_uri"], result

    return store.atomic(transition)


# @testable false
# @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
def _grant_name(user, client_id=None):
    # Preserve existing ChatGPT grants when adding independent Codex grants.
    suffix = "-codex" if client_id == CODEX_CLIENT_ID else ""
    return "grant-" + credential_id(user) + suffix


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_codex_loopback_grants_coexist_and_cannot_cross_clients
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_code_is_single_use_and_refresh_replay_revokes_the_family
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_token_exchange_rejects_wrong_binding_expiry_and_scope_expansion
# @matrix mcp-oauth : token pkce refresh replay transaction
def exchange_token(parameters, *, now=None):
    config = settings()
    now = _now(now)
    if not client_allowed(config, parameters.get("client_id")):
        raise OAuthError("invalid_client")
    if parameters.get("resource") != config["resource"]:
        raise OAuthError("invalid_target")
    if parameters.get("scope", SCOPE) != SCOPE:
        raise OAuthError("invalid_scope")
    grant_type = parameters.get("grant_type")
    if grant_type not in {"authorization_code", "refresh_token"}:
        raise OAuthError("unsupported_grant_type")
    is_code = grant_type == "authorization_code"
    incoming = parameters.get("code" if is_code else "refresh_token")
    name = _name(incoming, "c" if is_code else "r")
    candidate = store.read(name)
    if (
        not _live(candidate, now)
        or not _bound(candidate, config)
        or candidate.get("client_id") != parameters["client_id"]
    ):
        raise OAuthError()
    user = _user(candidate)
    grant_name = _grant_name(user, candidate["client_id"])
    if is_code:
        verifier = parameters.get("code_verifier", "")
        if (
            not _VERIFIER.fullmatch(verifier)
            or parameters.get("redirect_uri") != candidate["redirect_uri"]
        ):
            raise OAuthError()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )
        if not hmac.compare_digest(challenge, candidate["code_challenge"]):
            raise OAuthError()
    access, refresh = _secret("a"), _secret("r")
    family = secrets.token_hex(16)

    # @testable false
    # @covered-by lagniappe/core/tools/auth/remote_mcp.py::exchange_token
    # @reason token consumption and family rotation must share the transaction
    def transition(records):
        row = records.get(name)
        grant = records.get(grant_name)
        if not _live(row, now) or dict(row) != dict(candidate):
            # A racing refresh must take the replay path, not merely fail CAS.
            if (
                not is_code
                and row
                and row.get("used")
                and grant
                and grant.get("family") == row.get("family")
            ):
                records.put(grant_name, {**grant, "revoked": True})
                return None
            raise OAuthError()
        if is_code:
            if row.get("used"):
                raise OAuthError()
            grant = {
                "user": user.key,
                "family": family,
                "issued_at": now,
                "generation": 1,
                "expires_at": now + timedelta(seconds=REFRESH_SECONDS),
                "issuer": config["issuer"],
                "client_id": candidate["client_id"],
                "resource": config["resource"],
                "scope": SCOPE,
            }
        elif (
            not _live(grant, now)
            or grant.get("family") != row.get("family")
            or not _bound(grant, config)
        ):
            raise OAuthError()
        elif row.get("used"):
            records.put(grant_name, {**grant, "revoked": True})
            return None
        else:
            grant = {**grant, "generation": grant["generation"] + 1}
        records.put(name, {**row, "used": True})
        records.put(grant_name, grant)
        common = {
            key: grant[key]
            for key in ("user", "family", "issuer", "client_id", "resource", "scope")
        }
        common["grant"] = grant_name
        common.update(issued_at=now, generation=grant["generation"])
        expires_at = min(now + timedelta(seconds=ACCESS_SECONDS), grant["expires_at"])
        records.put(_name(access, "a"), {**common, "expires_at": expires_at})
        records.put(_name(refresh, "r"), {**common, "expires_at": grant["expires_at"]})
        return {
            "access_token": access,
            "token_type": "Bearer",
            "scope": SCOPE,
            "expires_in": int((expires_at - now).total_seconds()),
            "refresh_token": refresh,
        }

    result = store.atomic(transition)
    if result is None:
        raise OAuthError()
    return result


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_codex_loopback_grants_coexist_and_cannot_cross_clients
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_token_exchange_rejects_wrong_binding_expiry_and_scope_expansion
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_oauth_user_and_workload_identity_are_both_required
# @matrix mcp-oauth : authentication expiry revocation user-binding site-policy existing-grants
def authenticate_access(token, *, now=None):
    config, now = settings(), _now(now)
    row = store.read(_name(token, "a"))
    if not _live(row, now) or not _bound(row, config):
        raise OAuthError()
    grant = store.read(row.get("grant"))
    if (
        not _live(grant, now)
        or not _bound(grant, config)
        or grant.get("family") != row.get("family")
        or grant.get("user") != row.get("user")
        or grant.get("client_id") != row.get("client_id")
    ):
        raise OAuthError()
    user = _user(row)
    if _grant_name(user, row["client_id"]) != row["grant"]:
        raise OAuthError()
    return user, {
        "active": True,
        "display_prefix": None,
        "issued_at": row["issued_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "generation": row["generation"],
    }


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_oauth_user_and_workload_identity_are_both_required
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_cached_certificates_still_verify_each_signature_and_user_grant
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_oauth_outcomes_log_only_closed_categories_after_workload_verification
# @matrix mcp-oauth : oidc audience service-identity token-separation authentication revocation
def authenticate_envelope(workload_token, user_token):
    config = settings()
    if not isinstance(workload_token, str) or not 1 <= len(workload_token) <= 8192:
        raise OAuthError()
    _name(user_token, "a")
    try:
        claims = id_token.verify_oauth2_token(
            workload_token, _certificate_request, audience=config["issuer"] + "/api/v1"
        )
    except Exception:
        raise OAuthError() from None
    if (
        claims.get("iss") != "https://accounts.google.com"
        or claims.get("aud") != config["issuer"] + "/api/v1"
        or claims.get("email") != config["service_account"]
        or claims.get("email_verified") is not True
        or not isinstance(claims.get("sub"), str)
        or not claims["sub"].isdigit()
    ):
        raise OAuthError()
    log_outcome("workload_verified")
    return authenticate_access(user_token)


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_codex_loopback_grants_coexist_and_cannot_cross_clients
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_revocation_is_private_and_reconnect_replaces_only_the_old_family
# @matrix mcp-oauth : revocation reconnect privacy
def revoke_token(token, client_id):
    config = settings()
    if not client_allowed(config, client_id):
        raise OAuthError("invalid_client")
    try:
        match = _TOKEN.fullmatch(token) if isinstance(token, str) else None
        if not match or match[1] not in {"a", "r"}:
            return
        name = _name(token, match[1])
    except OAuthError:
        return

    # @testable false
    # @covered-by lagniappe/core/tools/auth/remote_mcp.py::revoke_token
    # @reason private family revocation is exercised through token possession
    def transition(records):
        row = records.get(name)
        if not row or not _bound(row, config) or row.get("client_id") != client_id:
            return
        grant = records.get(row["grant"])
        if grant and grant.get("family") == row["family"]:
            records.put(row["grant"], {**grant, "revoked": True})

    store.atomic(transition)


# @testable true
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_codex_loopback_grants_coexist_and_cannot_cross_clients
# @tests tests_unit/test_034_remote_mcp_oauth.py::test_revocation_is_private_and_reconnect_replaces_only_the_old_family
# @matrix mcp-oauth : revocation user-binding
def connection_status(user, *, client_id=None, revoke=False, now=None):
    config = settings()
    client_id = client_id or config["client_id"]
    if not client_allowed(config, client_id):
        raise OAuthError("invalid_client")
    name, now = _grant_name(user, client_id), _now(now)

    # @testable false
    # @covered-by lagniappe/core/tools/auth/remote_mcp.py::connection_status
    # @reason connection status and optional revocation operate on one user grant
    def transition(records):
        grant = records.get(name)
        if not grant or grant.get("user") != user.key:
            return {"active": False}
        if revoke:
            grant = {**grant, "revoked": True}
            records.put(name, grant)
        return {
            "active": _live(grant, now) and _bound(grant, config),
            "issued_at": grant["issued_at"],
            "expires_at": grant["expires_at"],
        }

    return store.atomic(transition)
