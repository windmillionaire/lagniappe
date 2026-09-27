"""Shared hosted health and browser access boundary for E2E coordinators/workers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class E2ERuntime:
    """Browser-facing state shared by every context in one pytest session."""

    run_id: str
    browser_cookies: tuple[dict, ...] = ()


def validate_hosted_e2e_health():
    """Validate the exact hosted deployment before touching shared test data."""
    import requests

    from lagniappe import CONFIG

    health_response = requests.get(
        f"{CONFIG.BASE_URL}/testing/health",
        timeout=30,
    )
    health_response.raise_for_status()
    expected_health = {
        "ready": True,
        "service": CONFIG.HOSTED_E2E_SERVICE,
        "version": CONFIG.HOSTED_E2E_VERSION,
        "source": CONFIG.HOSTED_E2E_SOURCE,
        "source_snapshot": CONFIG.HOSTED_E2E_SOURCE_SNAPSHOT,
        "build_id": CONFIG.HOSTED_E2E_BUILD_ID,
    }
    if health_response.json() != expected_health:
        raise RuntimeError(
            "Hosted E2E health metadata does not match this job execution."
        )


def hosted_e2e_browser_cookie(run_id):
    """Exchange one Google OIDC token for the deployment's browser cookie."""
    import requests
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    from lagniappe import CONFIG
    from lagniappe.core.tools.hosted_e2e.auth import HOSTED_E2E_COOKIE

    token = id_token.fetch_id_token(google_requests.Request(), CONFIG.BASE_URL)
    session_response = requests.post(
        f"{CONFIG.BASE_URL}/testing/session",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "run_id": run_id,
            "version": CONFIG.HOSTED_E2E_VERSION,
            "source": CONFIG.HOSTED_E2E_SOURCE,
        },
        timeout=30,
    )
    if session_response.status_code != 204:
        raise RuntimeError(
            "Hosted E2E browser bootstrap was rejected "
            f"(HTTP {session_response.status_code})."
        )
    value = session_response.cookies.get(HOSTED_E2E_COOKIE)
    if not value:
        raise RuntimeError("Hosted E2E bootstrap did not return its browser cookie.")
    return {
        "name": HOSTED_E2E_COOKIE,
        "value": value,
        "url": CONFIG.BASE_URL,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Strict",
    }


