"""Unit coverage for hosted-E2E credential primitives."""

import pytest

from lagniappe.core.tools.hosted_e2e.auth import (
    HostedE2EAuthenticationError,
    load_hosted_e2e_cookie,
    sign_hosted_e2e_cookie,
    validate_google_claims,
)


pytestmark = pytest.mark.unit


# @features hosted-e2e
# @dimensions authentication audience issuer identity
def test_validate_google_claims_requires_exact_verified_identity():
    expected = {
        "iss": "https://accounts.google.com",
        "aud": "https://version.example.test",
        "email": "runner@project-1.iam.gserviceaccount.com",
        "email_verified": True,
    }

    assert (
        validate_google_claims(
            expected,
            audience=expected["aud"],
            caller_email=expected["email"],
        )
        is expected
    )

    for field, value in (
        ("iss", "accounts.google.com"),
        ("aud", "https://other.example.test"),
        ("email", "other@project-1.iam.gserviceaccount.com"),
        ("email_verified", False),
    ):
        claims = {**expected, field: value}
        with pytest.raises(HostedE2EAuthenticationError):
            validate_google_claims(
                claims,
                audience=expected["aud"],
                caller_email=expected["email"],
            )


# @features hosted-e2e
# @dimensions authentication cookie expiry deployment-binding
def test_hosted_e2e_cookie_is_signed_scoped_and_expiring():
    secret = "s" * 48
    value = sign_hosted_e2e_cookie(
        secret,
        run_id="run_abcdefghijklmnopqrstuvwxyz",
        version="e2e-version",
        source="a" * 40,
    )

    assert load_hosted_e2e_cookie(
        secret,
        value,
        version="e2e-version",
        source="a" * 40,
    ) == {
        "run_id": "run_abcdefghijklmnopqrstuvwxyz",
        "version": "e2e-version",
        "source": "a" * 40,
    }

    with pytest.raises(HostedE2EAuthenticationError, match="another deployment"):
        load_hosted_e2e_cookie(
            secret,
            value,
            version="another-version",
            source="a" * 40,
        )
    with pytest.raises(HostedE2EAuthenticationError, match="invalid or expired"):
        load_hosted_e2e_cookie(
            secret,
            value + "tampered",
            version="e2e-version",
            source="a" * 40,
        )
