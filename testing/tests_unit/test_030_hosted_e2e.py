"""Unit coverage for hosted-E2E credential primitives."""

import pytest

from lagniappe.core.tools.hosted_e2e.auth import (
    HostedE2EAuthenticationError,
    load_hosted_e2e_cookie,
    sign_hosted_e2e_cookie,
    validate_google_claims,
)


pytestmark = pytest.mark.unit


# @matrix hosted-e2e : authentication cookie
@pytest.mark.parametrize("inherited", [True, False])
def test_worker_inherits_run_cookie_without_replaying_bootstrap(monkeypatch, inherited):
    from types import SimpleNamespace
    import lagniappe
    from lagniappe.core.entities import Entities
    from testing.utility import e2e_runtime, e2e_worker

    base_url = "https://candidate.example.test"
    cookie = {"name": "__Host-lagniappe-e2e", "value": "test-run-cookie", "url": base_url}
    record = {"base_url": base_url, "run_id": "test-run",
              "browser_cookies": [cookie] if inherited else []}
    monkeypatch.setattr(lagniappe, "CONFIG", SimpleNamespace(
        testing=True, PREFIX="test-", BASE_URL=base_url, hosted_e2e_runner=True))
    monkeypatch.setattr(e2e_worker, "context", lambda: record)
    monkeypatch.setattr(e2e_worker, "assert_owner", lambda record: None)
    monkeypatch.setattr(Entities, "initialize", lambda: None)
    monkeypatch.setattr(e2e_runtime, "validate_hosted_e2e_health", lambda: None)

    def forbidden_exchange(_run_id):
        raise AssertionError("A worker must not exchange another single-use bootstrap token")

    monkeypatch.setattr(e2e_runtime, "hosted_e2e_browser_cookie", forbidden_exchange)
    if not inherited:
        with pytest.raises(RuntimeError, match="coordinator's run cookie"):
            with e2e_worker.worker_runtime():
                pytest.fail("A hosted worker started without its inherited cookie")
    else:
        with e2e_worker.worker_runtime() as runtime:
            assert runtime.run_id == "test-run"
            assert runtime.browser_cookies == (cookie,)


# @matrix hosted-e2e : audience authentication identity issuer
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


# @matrix hosted-e2e : authentication cookie deployment-binding expiry
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
    with pytest.raises(HostedE2EAuthenticationError, match="another deployment"):
        load_hosted_e2e_cookie(
            secret,
            value,
            version="e2e-version",
            source="b" * 40,
        )
    with pytest.raises(HostedE2EAuthenticationError, match="invalid or expired"):
        load_hosted_e2e_cookie(
            secret,
            value,
            version="e2e-version",
            source="a" * 40,
            max_age=-1,
        )
    with pytest.raises(HostedE2EAuthenticationError, match="invalid or expired"):
        load_hosted_e2e_cookie(
            secret,
            value + "tampered",
            version="e2e-version",
            source="a" * 40,
        )
