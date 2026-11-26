"""Remote MCP OAuth service, using opaque secrets and current User permissions."""

from collections.abc import Mapping
import base64
from datetime import datetime, timedelta, UTC
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypeGuard

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User

from google.oauth2 import id_token

from config.remote_mcp import (
    ACCESS_SECONDS,
    ANTIGRAVITY_CLIENT_ID,
    CIMD_CLIENTS,
    CIMD_LOOPBACK_CLIENTS,
    CLAUDE_CLIENT_ID,
    CLAUDE_CODE_CLIENT_ID,
    CODE_SECONDS,
    CODEX_CLIENT_ID,
    CLIENT_ID,
    PI_CLIENT_ID,
    loopback_redirect_base,
    mcp_issuer,
    client_allowed,
    redirect_allowed,
    PENDING_SECONDS,
    REFRESH_RACE_GRACE_SECONDS,
    REFRESH_RACE_MAX_MINTS,
    REFRESH_SECONDS,
    LEGACY_SCOPE,
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
_client_cache: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, object]]] | None = {}
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


def log_outcome(outcome: str) -> None:
    """Emit only a fixed outcome category through this subsystem's own handler."""
    if isinstance(outcome, str) and outcome in _LOG_OUTCOMES:
        LOGGER.info(outcome)


class OAuthError(ValueError):
    def __init__(self, code: str = "invalid_grant", status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def settings() -> dict[str, str]:
    if (
        not CONFIG.AI_ENABLED or not CONFIG.EXTERNAL_AI_ENABLED
        or not CONFIG.MCP_RESOURCE or not CONFIG.MCP_SERVICE_ACCOUNT
    ):
        raise OAuthError("temporarily_unavailable", 503)
    return {
        "issuer": mcp_issuer(vars(CONFIG)),
        "resource": CONFIG.MCP_RESOURCE,
        "service_account": CONFIG.MCP_SERVICE_ACCOUNT,
    }


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _secret(kind: str) -> str:
    return f"lgmo_{kind}_{secrets.token_urlsafe(32)}"


def _name(token, kind):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token) or token[5] != kind:
        raise OAuthError()
    return f"{kind}-{hashlib.sha256(token.encode('ascii')).hexdigest()}"


def _live[T: dict](row: T | None, now: datetime) -> TypeGuard[T]:
    return bool(
        row
        and not row.get("revoked")
        and isinstance(row.get("expires_at"), datetime)
        and row["expires_at"] > now
    )


def _bound(row, config):
    return (
        all(row.get(key) == config[key] for key in ("issuer", "resource"))
        and client_allowed(row.get("client_id"))
        and row.get("scope") in (None, LEGACY_SCOPE)
    )


def eligible_user(user: object) -> TypeGuard[User]:
    settings()
    return bool(
        isinstance(user, Entities.USER)
        and user.is_authenticated
        and user.is_active
        and not user.is_public
    )


def _user(row, *, prefetched=None):
    user_key = row.get("user")
    user = Entities.fetch_one(prefetched if prefetched is not None else user_key, request=Fetch.direct())
    if not eligible_user(user) or user.key != user_key:
        raise OAuthError()
    return user


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate metadata field")
        value[key] = item
    return value


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


def client_metadata(client_id: str) -> dict[str, object]:
    """Fetch only supported CIMD documents, with no DCR or client secret."""
    global _client_cache
    settings()
    if client_id in CIMD_CLIENTS:
        expected_redirects: tuple[str, ...] = (CIMD_CLIENTS[client_id],)
    elif client_id in CIMD_LOOPBACK_CLIENTS:
        expected_redirects = CIMD_LOOPBACK_CLIENTS[client_id]
    else:
        raise OAuthError("invalid_client")
    cache_key = (client_id, expected_redirects)
    with _client_lock:
        if not isinstance(_client_cache, dict):
            _client_cache = {}
        cached = _client_cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
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
            matched_redirects = (
                tuple(uri for uri in expected_redirects if uri in redirects)
                if isinstance(redirects, list)
                else ()
            )
            if (
                document.get("client_id") != client_id
                or not isinstance(methods, list)
                or "none" not in methods
                or not all(isinstance(item, str) for item in methods)
                or not isinstance(redirects, list)
                or not matched_redirects
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
        metadata: dict[str, object] = {
            "client_id": client_id,
            "redirect_uri": matched_redirects[0],
            "redirect_uris": matched_redirects,
        }
        _client_cache[cache_key] = (time.monotonic() + 300, metadata)
        return metadata


def begin_authorization(parameters: Mapping[str, str], *, now: datetime | None = None) -> str:
    config = settings()
    if (
        not redirect_allowed(
            parameters.get("client_id"), parameters.get("redirect_uri")
        )
    ):
        raise OAuthError("invalid_client")
    required = {
        "response_type",
        "client_id",
        "redirect_uri",
        "resource",
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
    # Access follows the user's current permissions, with no scope negotiation.
    # Older clients may still send the previously advertised scope.
    if parameters.get("scope") not in (None, "", LEGACY_SCOPE):
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
    if parameters["client_id"] in CIMD_CLIENTS or parameters["client_id"] in CIMD_LOOPBACK_CLIENTS:
        metadata = client_metadata(parameters["client_id"])
        published_redirects = metadata.get("redirect_uris")
        if isinstance(published_redirects, (list, tuple)):
            expected_base = (
                loopback_redirect_base(parameters["redirect_uri"], allow_localhost=True)
                if parameters["client_id"] in CIMD_LOOPBACK_CLIENTS
                else parameters["redirect_uri"]
            )
            if expected_base not in published_redirects:
                raise OAuthError("invalid_client")
    now = _now(now)
    pending = _secret("p")
    row: dict[str, object] = {key: parameters[key] for key in required}
    row.update(
        issuer=config["issuer"], expires_at=now + timedelta(seconds=PENDING_SECONDS)
    )
    store.atomic(lambda records: records.put(_name(pending, "p"), row))
    return pending


def pending_authorization(pending: str, *, now: datetime | None = None) -> dict[str, object]:
    row = store.read(_name(pending, "p"))
    if not _live(row, _now(now)) or row.get("consumed") or not _bound(row, settings()):
        raise OAuthError("invalid_request")
    return row


def consent(pending: str, user: User, *, allow: bool, now: datetime | None = None) -> tuple[str, dict[str, str]]:
    if not eligible_user(user):
        raise OAuthError("access_denied", 403)
    now = _now(now)
    config = settings()
    code = _secret("c")

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


def _grant_name(user, client_id: str | None = None) -> str:
    # Preserve existing ChatGPT and Codex grants when adding independent client grants.
    suffix = {
        CODEX_CLIENT_ID: "-codex",
        ANTIGRAVITY_CLIENT_ID: "-antigravity",
        CLAUDE_CLIENT_ID: "-claude",
        CLAUDE_CODE_CLIENT_ID: "-claude-code",
        PI_CLIENT_ID: "-pi",
    }.get(client_id or "", "")
    return "grant-" + credential_id(user) + suffix


def _within_refresh_race_grace(
    grant: Mapping[str, object],
    row: Mapping[str, object],
    now: datetime,
) -> bool:
    """Allow immediate concurrent refreshes of the just-rotated generation without revoking."""
    rotated_at = grant.get("rotated_at")
    if not isinstance(rotated_at, datetime):
        return False
    if rotated_at.tzinfo is None:
        rotated_at = rotated_at.replace(tzinfo=UTC)
    elapsed = now - rotated_at
    generation = grant.get("generation")
    row_generation = row.get("generation")
    race_mints = grant.get("race_mints", 0)
    return (
        isinstance(generation, int)
        and isinstance(row_generation, int)
        and isinstance(race_mints, int)
        and generation == row_generation + 1
        and timedelta(0) <= elapsed < timedelta(seconds=REFRESH_RACE_GRACE_SECONDS)
        and race_mints < REFRESH_RACE_MAX_MINTS
    )


def exchange_token(parameters: Mapping[str, str], *, now: datetime | None = None) -> dict[str, str | int]:
    config = settings()
    now = _now(now)
    if not client_allowed(parameters.get("client_id")):
        raise OAuthError("invalid_client")
    if parameters.get("scope") not in (None, "", LEGACY_SCOPE):
        raise OAuthError("invalid_scope")
    grant_type = parameters.get("grant_type")
    if grant_type not in {"authorization_code", "refresh_token"}:
        raise OAuthError("unsupported_grant_type")
    is_code = grant_type == "authorization_code"
    resource = parameters.get("resource")
    if is_code:
        if resource != config["resource"]:
            raise OAuthError("invalid_target")
    elif resource not in (None, "", config["resource"]):
        raise OAuthError("invalid_target")
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

    def transition(records):
        row = records.get(name)
        grant = records.get(grant_name)
        if is_code:
            if not _live(row, now) or dict(row) != dict(candidate) or row.get("used"):
                raise OAuthError()
            grant = {
                "user": user.key,
                "family": family,
                "issued_at": now,
                "generation": 1,
                "rotated_at": now,
                "race_mints": 0,
                "expires_at": now + timedelta(seconds=REFRESH_SECONDS),
                "issuer": config["issuer"],
                "client_id": candidate["client_id"],
                "resource": config["resource"],
            }
            records.put(name, {**row, "used": True})
        else:
            if (
                not _live(row, now)
                or not _bound(row, config)
                or row.get("client_id") != candidate["client_id"]
                or row.get("family") != candidate.get("family")
                or not _live(grant, now)
                or grant.get("family") != row.get("family")
                or not _bound(grant, config)
            ):
                raise OAuthError()
            if not row.get("used") and row.get("generation") == grant.get("generation"):
                grant = {
                    **grant,
                    "generation": grant["generation"] + 1,
                    "rotated_at": now,
                    "race_mints": 0,
                }
                records.put(name, {**row, "used": True, "used_at": now})
            elif _within_refresh_race_grace(grant, row, now):
                grant = {
                    **grant,
                    "race_mints": int(grant.get("race_mints") or 0) + 1,
                }
                if not row.get("used"):
                    records.put(name, {**row, "used": True, "used_at": now})
            else:
                records.put(grant_name, {**grant, "revoked": True})
                return None
        records.put(grant_name, grant)
        common = {
            key: grant[key]
            for key in ("user", "family", "issuer", "client_id", "resource")
        }
        common["grant"] = grant_name
        common.update(issued_at=now, generation=grant["generation"])
        expires_at = min(now + timedelta(seconds=ACCESS_SECONDS), grant["expires_at"])
        records.put(_name(access, "a"), {**common, "expires_at": expires_at})
        records.put(_name(refresh, "r"), {**common, "expires_at": grant["expires_at"]})
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": int((expires_at - now).total_seconds()),
            "refresh_token": refresh,
        }

    result = store.atomic(transition)
    if result is None:
        raise OAuthError()
    return result


def authenticate_access(token: str, *, now: datetime | None = None) -> tuple[User, dict[str, object]]:
    config, now = settings(), _now(now)
    row = store.read(_name(token, "a"))
    if not _live(row, now) or not _bound(row, config):
        raise OAuthError()
    grant_name = row.get("grant")
    if not isinstance(grant_name, str):
        raise OAuthError()
    grant, user_row = store.read_grant_and_user(grant_name, row.get("user"))
    if (
        not _live(grant, now)
        or not _bound(grant, config)
        or grant.get("family") != row.get("family")
        or grant.get("user") != row.get("user")
        or grant.get("client_id") != row.get("client_id")
        or user_row is None
    ):
        raise OAuthError()
    user = _user(row, prefetched=user_row)
    if _grant_name(user, row["client_id"]) != row["grant"]:
        raise OAuthError()
    return user, {
        "active": True,
        "display_prefix": None,
        "issued_at": row["issued_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "generation": row["generation"],
    }


def authenticate_envelope(workload_token: str, user_token: str) -> tuple[User, dict[str, object]]:
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


def revoke_token(token: str, client_id: str) -> None:
    config = settings()
    if not client_allowed(client_id):
        raise OAuthError("invalid_client")
    try:
        match = _TOKEN.fullmatch(token) if isinstance(token, str) else None
        if not match or match[1] not in {"a", "r"}:
            return
        name = _name(token, match[1])
    except OAuthError:
        return

    def transition(records):
        row = records.get(name)
        if not row or not _bound(row, config) or row.get("client_id") != client_id:
            return
        grant = records.get(row["grant"])
        if grant and grant.get("family") == row["family"]:
            records.put(row["grant"], {**grant, "revoked": True})

    store.atomic(transition)


def connection_status(user: User, *, client_id: str | None = None, revoke: bool = False, now: datetime | None = None) -> Mapping[str, object]:
    config = settings()
    client_id = client_id or CLIENT_ID
    if not client_allowed(client_id):
        raise OAuthError("invalid_client")
    name, now = _grant_name(user, client_id), _now(now)

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
