"""Shown-once bearer credentials for the external agent API."""

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import re
import secrets

from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import agent_api as credential_store


TOKEN_PREFIX = "lgn_"
TOKEN_LIFETIME = timedelta(days=30)
TOKEN_PATTERN = re.compile(
    r"^lgn_([A-Za-z0-9_-]{24})\.([A-Za-z0-9_-]{40,50})$"
)


class AgentAPICredentialError(ValueError):
    """Raised when a bearer credential is absent, invalid, revoked, or expired."""


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_api.py::authenticate_credential
# @reason timestamp normalization is exercised through credential expiry checks
def _utc(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_api.py::credential_id
# @reason encoding helper is owned by opaque credential id construction
def _urlsafe(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_api.py::issue_credential
# @reason opaque id construction is exercised through issuance and authentication
def credential_id(user):
    """Return a stable opaque lookup id without exposing the user's entity key."""
    digest = hmac.new(
        str(CONFIG.SECRET_KEY).encode("utf-8"),
        str(user.urlsafe_key).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe(digest[:18])


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_api.py::authenticate_credential
# @reason digest comparison is exercised through tamper rejection
def _token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_api.py::issue_credential
# @reason safe projection is asserted through issuance and status responses
def _public_metadata(row, *, now=None):
    now = _utc(now)
    expires_at = row.get("expires_at") if row else None
    if isinstance(expires_at, datetime):
        expires_at = _utc(expires_at)
    active = bool(
        row
        and row.get("active") is True
        and isinstance(expires_at, datetime)
        and expires_at > now
        and row.get("token_digest")
    )
    return {
        "active": active,
        "display_prefix": row.get("display_prefix") if row else None,
        "issued_at": (
            _utc(row["issued_at"]).isoformat()
            if row and isinstance(row.get("issued_at"), datetime)
            else None
        ),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "generation": int((row or {}).get("generation") or 0),
    }


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_issue_authenticate_expire_and_revoke_credential
# @matrix agent-api : authentication expiry issue shown-once
def issue_credential(user, *, now=None):
    """Rotate the user's credential and return the secret exactly once."""
    now = _utc(now)
    identifier = credential_id(user)
    secret = secrets.token_urlsafe(32)
    token = f"{TOKEN_PREFIX}{identifier}.{secret}"
    row = credential_store.rotate_credential(
        identifier,
        user.key,
        token_digest=_token_digest(token),
        display_prefix=f"{TOKEN_PREFIX}{identifier[:8]}…",
        issued_at=now,
        expires_at=now + TOKEN_LIFETIME,
    )
    return token, _public_metadata(row, now=now)


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_issue_authenticate_expire_and_revoke_credential
# @matrix agent-api : authentication expiry revoke
def revoke_credential(user, *, now=None):
    row = credential_store.revoke_credential(
        credential_id(user),
        user.key,
        revoked_at=_utc(now),
    )
    return _public_metadata(row, now=now)


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_issue_authenticate_expire_and_revoke_credential
# @matrix agent-api : authentication expiry
def credential_status(user, *, now=None):
    row = credential_store.get_credential(credential_id(user))
    if row is not None and row.get("user") != user.key:
        row = None
    return _public_metadata(row, now=now)


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_issue_authenticate_expire_and_revoke_credential
# @tests tests_unit/test_032_agent_api.py::test_authenticate_rejects_tampered_and_mismatched_credentials
# @matrix agent-api : authentication expiry revoke tamper user-binding
def authenticate_credential(token, *, now=None):
    """Return the current User for a valid external-agent bearer token."""
    match = TOKEN_PATTERN.fullmatch(str(token or "").strip())
    if not match:
        raise AgentAPICredentialError("Invalid API credential.")

    identifier = match.group(1)
    row = credential_store.get_credential(identifier)
    if not row or row.get("active") is not True or not row.get("token_digest"):
        raise AgentAPICredentialError("Invalid API credential.")

    expires_at = row.get("expires_at")
    if not isinstance(expires_at, datetime) or _utc(expires_at) <= _utc(now):
        raise AgentAPICredentialError("API credential expired.")

    if not hmac.compare_digest(row["token_digest"], _token_digest(token)):
        raise AgentAPICredentialError("Invalid API credential.")

    user = Entities.fetch_one(row.get("user"), request=Fetch.direct())
    if not isinstance(user, Entities.USER) or user.key != row.get("user"):
        raise AgentAPICredentialError("Invalid API credential.")
    if credential_id(user) != identifier:
        raise AgentAPICredentialError("Invalid API credential.")
    return user, _public_metadata(row, now=now)


__all__ = [
    "AgentAPICredentialError",
    "TOKEN_LIFETIME",
    "authenticate_credential",
    "credential_status",
    "issue_credential",
    "revoke_credential",
]
