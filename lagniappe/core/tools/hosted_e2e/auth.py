"""Authentication primitives for the private hosted-E2E app version."""

from __future__ import annotations

import hashlib

from itsdangerous import BadData, URLSafeTimedSerializer


HOSTED_E2E_COOKIE = "__Host-lagniappe-e2e"
HOSTED_E2E_COOKIE_SALT = "lagniappe-hosted-e2e-session-v1"
HOSTED_E2E_COOKIE_MAX_AGE = 2 * 60 * 60


# @testable infrastructure
class HostedE2EAuthenticationError(ValueError):
    """Raised when a hosted-E2E credential does not match the deployment."""


# @testable true
# @tests tests_unit/test_030_hosted_e2e.py::test_validate_google_claims_requires_exact_verified_identity
# @matrix hosted-e2e : audience authentication identity issuer
def validate_google_claims(claims, *, audience: str, caller_email: str) -> dict:
    """Validate the identity-bound claims returned by Google's token verifier."""
    if not isinstance(claims, dict):
        raise HostedE2EAuthenticationError("Google ID-token claims are invalid.")
    if claims.get("iss") != "https://accounts.google.com":
        raise HostedE2EAuthenticationError("Google ID-token issuer is invalid.")
    if claims.get("aud") != audience:
        raise HostedE2EAuthenticationError("Google ID-token audience is invalid.")
    if claims.get("email_verified") is not True:
        raise HostedE2EAuthenticationError("Google caller email is not verified.")
    email = str(claims.get("email") or "").strip().casefold()
    if not email or email != str(caller_email or "").strip().casefold():
        raise HostedE2EAuthenticationError("Google caller identity is invalid.")
    return claims


# @testable false
# @covered-by lagniappe/core/tools/hosted_e2e/auth.py::sign_hosted_e2e_cookie
# @covered-by lagniappe/core/tools/hosted_e2e/auth.py::load_hosted_e2e_cookie
# @reason serializer construction is owned by the public signed-cookie contracts
def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    if len(str(secret_key or "")) < 32:
        raise HostedE2EAuthenticationError("Hosted E2E session key is invalid.")
    return URLSafeTimedSerializer(
        secret_key,
        salt=HOSTED_E2E_COOKIE_SALT,
        signer_kwargs={"digest_method": hashlib.sha256},
    )


# @testable true
# @tests tests_unit/test_030_hosted_e2e.py::test_hosted_e2e_cookie_is_signed_scoped_and_expiring
# @matrix hosted-e2e : authentication cookie deployment-binding expiry
def sign_hosted_e2e_cookie(
    secret_key: str,
    *,
    run_id: str,
    version: str,
    source: str,
) -> str:
    """Sign a browser credential bound to one run and one deployed version."""
    return _serializer(secret_key).dumps(
        {
            "run_id": str(run_id),
            "version": str(version),
            "source": str(source),
        }
    )


# @testable true
# @tests tests_unit/test_030_hosted_e2e.py::test_hosted_e2e_cookie_is_signed_scoped_and_expiring
# @matrix hosted-e2e : authentication cookie deployment-binding expiry
def load_hosted_e2e_cookie(
    secret_key: str,
    value: str,
    *,
    version: str,
    source: str,
    max_age: int = HOSTED_E2E_COOKIE_MAX_AGE,
) -> dict:
    """Verify and decode a browser credential for the active deployment."""
    try:
        payload = _serializer(secret_key).loads(value, max_age=int(max_age))
    except BadData as error:
        raise HostedE2EAuthenticationError(
            "Hosted E2E browser credential is invalid or expired."
        ) from error
    if not isinstance(payload, dict) or set(payload) != {
        "run_id",
        "version",
        "source",
    }:
        raise HostedE2EAuthenticationError(
            "Hosted E2E browser credential has an invalid payload."
        )
    if payload.get("version") != version or payload.get("source") != source:
        raise HostedE2EAuthenticationError(
            "Hosted E2E browser credential belongs to another deployment."
        )
    return payload


__all__ = [
    "HOSTED_E2E_COOKIE",
    "HOSTED_E2E_COOKIE_MAX_AGE",
    "HostedE2EAuthenticationError",
    "load_hosted_e2e_cookie",
    "sign_hosted_e2e_cookie",
    "validate_google_claims",
]
