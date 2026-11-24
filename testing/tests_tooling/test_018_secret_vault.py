"""Security and lifecycle tests for installer.secret_vault."""

from __future__ import annotations

import re
import threading
from urllib.parse import urlencode

import pytest
import requests

from installer.secret_vault import (
    OneShotSecretVault,
    VaultField,
    VaultLink,
    VaultSection,
    VaultSubmitResult,
    build_install_vault_sections,
    parse_oauth_vault_inputs,
)

pytestmark = pytest.mark.tooling


def _extract_csrf(html_body: str) -> str:
    match = re.search(r'name="_csrf"\s+value="([^"]+)"', html_body)
    assert match, "CSRF token missing from rendered vault HTML"
    return match.group(1)


def _sample_sections() -> tuple[VaultSection, ...]:
    return (
        VaultSection(
            section_id="redis",
            title="Redis",
            description="Test Redis credentials.",
            links=(VaultLink("Redis Cloud", "https://cloud.redis.io/"),),
            fields=(
                VaultField(name="redis_host", label="Host", secret=False, required=True),
                VaultField(name="redis_password", label="Password", secret=True, required=True),
            ),
        ),
    )


def test_vault_enforces_token_host_origin_csrf_retry_and_one_shot_shutdown(capsys):
    attempts: list[dict[str, str]] = []

    def on_submit(values: dict[str, str]) -> VaultSubmitResult:
        attempts.append(dict(values))
        if values["redis_password"] != "correct-horse-battery":
            return VaultSubmitResult(
                ok=False,
                error="Redis authentication failed.",
                field_errors={"redis_password": "Password was rejected."},
            )
        return VaultSubmitResult(ok=True, summary=("Redis connection verified and saved.",))

    vault = OneShotSecretVault(_sample_sections(), on_submit)
    url = vault.start()
    base = f"http://127.0.0.1:{vault.port}"
    try:
        # Wrong path token is rejected with 404 + no-store headers.
        bad_path = requests.get(f"{base}/vault/wrong-token", timeout=5)
        assert bad_path.status_code == 404
        assert bad_path.headers["Cache-Control"] == "no-store, max-age=0"
        assert bad_path.headers["X-Frame-Options"] == "DENY"

        # DNS rebinding / spoofed Host header is rejected with 403.
        bad_host = requests.get(url, headers={"Host": "evil.example.test"}, timeout=5)
        assert bad_host.status_code == 403

        # Valid GET renders form, links, and CSRF token.
        page = requests.get(url, timeout=5)
        assert page.status_code == 200
        assert "https://cloud.redis.io/" in page.text
        assert "no-store" in page.headers["Cache-Control"]
        # Same-origin Referrer-Policy is required so browsers send Origin on POST
        # (no-referrer causes Chromium to send Origin: null and fail CSRF checks).
        assert page.headers["Referrer-Policy"] == "same-origin"
        assert "default-src 'none'" in page.headers["Content-Security-Policy"]
        csrf = _extract_csrf(page.text)

        # Missing or foreign Origin on POST is rejected with 403.
        bad_origin = requests.post(
            url,
            headers={
                "Origin": "https://attacker.example.test",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode(
                {"_csrf": csrf, "redis_host": "redis.test", "redis_password": "wrong"}
            ),
            timeout=5,
        )
        assert bad_origin.status_code == 403

        # Wrong CSRF token is rejected with 403.
        bad_csrf = requests.post(
            url,
            headers={
                "Origin": base,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode(
                {"_csrf": "bad", "redis_host": "redis.test", "redis_password": "wrong"}
            ),
            timeout=5,
        )
        assert bad_csrf.status_code == 403

        # Bad credential returns HTTP 400 with inline error and NEVER echoes the secret back.
        retry = requests.post(
            url,
            headers={
                "Origin": base,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode(
                {
                    "_csrf": csrf,
                    "redis_host": "redis.test",
                    "redis_password": "wrong-secret-value-123",
                }
            ),
            timeout=5,
        )
        assert retry.status_code == 400
        assert "Redis authentication failed." in retry.text
        assert "Password was rejected." in retry.text
        assert "redis.test" in retry.text
        assert "wrong-secret-value-123" not in retry.text

        # Valid credential succeeds, renders confirmation, and shuts down immediately.
        wait_result: list[VaultSubmitResult] = []
        waiter = threading.Thread(
            target=lambda: wait_result.append(vault.wait(timeout=5)),
            daemon=True,
        )
        waiter.start()

        ok = requests.post(
            url,
            headers={
                "Origin": base,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode(
                {
                    "_csrf": csrf,
                    "redis_host": "redis.test",
                    "redis_password": "correct-horse-battery",
                }
            ),
            timeout=5,
        )
        assert ok.status_code == 200
        assert "Credentials verified and saved" in ok.text
        assert "correct-horse-battery" not in ok.text
        waiter.join(timeout=5)
        assert not waiter.is_alive()
        assert len(wait_result) == 1 and wait_result[0].ok is True

        # Replaying the one-time token URL after completion fails (port closed or 410).
        try:
            replay = requests.get(url, timeout=2)
        except requests.RequestException:
            replay = None
        if replay is not None:
            assert replay.status_code == 410
    finally:
        vault.stop()

    captured = capsys.readouterr()
    assert "correct-horse-battery" not in captured.out
    assert "correct-horse-battery" not in captured.err
    assert "wrong-secret-value-123" not in captured.out
    assert "wrong-secret-value-123" not in captured.err
    assert vault.token not in captured.out
    assert vault.token not in captured.err


def test_build_install_vault_sections_and_oauth_json_parser():
    sections = build_install_vault_sections(
        {
            "GOOGLE_CLOUD_PROJECT": "pilot-project-1",
            "APP_URL": "https://pilot-project-1.uc.r.appspot.com",
            "GOOGLE_LOGIN_URI": "https://pilot-project-1.uc.r.appspot.com/users/google_login",
        },
        include_oauth=True,
        include_auth_email=True,
        include_redis=True,
        include_sentry=True,
        auth_email_provider="gmail",
    )
    assert [section.section_id for section in sections] == [
        "google_oauth",
        "auth_email",
        "redis",
        "sentry",
    ]
    assert "project=pilot-project-1" in sections[0].links[0].url
    assert [f.name for f in sections[0].fields] == ["oauth_credentials_json"]
    assert sections[0].fields[0].required is True
    assert [f.name for f in sections[2].fields] == ["redis_cli_command"]
    assert sections[2].fields[0].required is True

    client_id, client_secret = parse_oauth_vault_inputs(
        {
            "oauth_credentials_json": '{"web":{"client_id":"123.apps.googleusercontent.com","client_secret":"sec-1"}}'
        }
    )
    assert (client_id, client_secret) == ("123.apps.googleusercontent.com", "sec-1")

    with pytest.raises(ValueError, match="Web application"):
        parse_oauth_vault_inputs({"oauth_credentials_json": '{"installed":{}}'})
