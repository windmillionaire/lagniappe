"""AI configuration for Lagniappe.

This module provides the entry point for configuring AI settings,
including zero data retention mode.
"""

from runner.context import setup_command
from installer import FORMATTER, wrap_text
from .package_install import install_if_missing
from .verify import prepare_existing_installation

AI_API_TIMEOUT = 10
VERTEX_AI_REGION = "us-central1"


# @testable false
# @covered-by installer/ai.py::_configure_ai_cache
# @reason provider auth handshake is exercised through the live setup flow
def _get_access_token():
    """Get OAuth2 access token for Vertex AI Management API."""
    from installer import FORMATTER

    f = FORMATTER.initialize()

    install_if_missing(
        "google.auth", "Google authentication library", package_name="google-auth"
    )
    import google.auth
    import google.auth.transport.requests

    credentials, project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if not credentials:
        print(
            f.error("Failed to get Application Default Credentials for Vertex AI.")
        )
        return None

    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    return credentials.token


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_gcp_domain_mapping_and_ai_cache_commands
# @pair setup:ai-cache
def _api_request(session, method, url, headers, json_data=None, allow_codes=None):
    """Make an API request, returning (response, json) or None on error."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    allow_codes = allow_codes or []

    if method == "GET":
        resp = session.get(url, headers=headers, timeout=AI_API_TIMEOUT)
    elif method == "PATCH":
        resp = session.patch(
            url, headers=headers, json=json_data or {}, timeout=AI_API_TIMEOUT
        )
    else:
        resp = session.post(
            url, headers=headers, json=json_data or {}, timeout=AI_API_TIMEOUT
        )

    if resp.status_code == 200 or resp.status_code in allow_codes:
        return resp, resp.json() if resp.text else {}

    print(f.error(f"API request failed: {method} {url}"))
    print(f.error(f"Status {resp.status_code}: {resp.text[:1000]}"))
    return None


# @testable false
# @covered-by installer/ai.py::_configure_ai_cache
# @reason manual fallback instructions for the AI cache setup flow
def print_ai_cache_instructions(project_id):
    """Print a portable Python retry command for AI caching."""
    f = FORMATTER.initialize()
    print(
        f"\n{f.warning('Fix Application Default Credentials for project ')}"
        f"{project_id}, then retry the Python setup mode:"
    )
    print(setup_command("ai"))


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_gcp_domain_mapping_and_ai_cache_commands
# @tests tests_tooling/test_001d_setup_drift.py::test_vertex_discovery_has_cache_config_disable_cache
# @matrix setup : ai-cache api-drift
def _configure_ai_cache(sp):
    """Disable AI data caching in Vertex AI."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    install_if_missing("requests", "HTTP library for Python")
    import requests

    project_id = SETTINGS.GCLOUD_CONFIG.get("PROJECT")
    if not project_id:
        sp.write(f.error("Google Cloud Project ID not found"))
        sp.fail(f.fail_glyph)
        return False

    try:
        access_token = _get_access_token()
    except Exception as e:
        print(f.error(f"Failed to obtain access token:\n{str(e)}"))
        print_ai_cache_instructions(project_id)
        sp.fail(f.fail_glyph)
        return False

    if not access_token:
        print_ai_cache_instructions(project_id)
        sp.fail(f.fail_glyph)
        return False

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    session = requests.Session()
    cache_url = (
        f"https://{VERTEX_AI_REGION}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/cacheConfig"
    )
    payload = {
        "name": f"projects/{project_id}/cacheConfig",
        "disableCache": True,
    }

    if _api_request(session, "PATCH", cache_url, headers, payload) is None:
        print_ai_cache_instructions(project_id)
        sp.fail(f.fail_glyph)
        return False

    print(f.success("AI data caching disabled successfully."))
    print(
        wrap_text(
            "Vertex AI prompt caching is now disabled for this project. Review "
            "Google Cloud's zero data retention guidance for the remaining "
            "provider settings."
        )
    )
    sp.ok(f.ok_glyph)
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_ai_setup_mode_configures_observability
# @matrix ai-observability setup : ai-cache privacy-consent settings-save
def configure_ai():
    """Entry point for AI configuration.

    Verify the installation, configure caching, and expose observability.
    """
    prepare_existing_installation()

    from config import SETTINGS
    from installer.optional import configure_ai_observability

    f = FORMATTER.initialize()

    print(f"\n{f.info('AI Configuration for Lagniappe')}")
    print("=" * 40)
    print("\nThis will configure Vertex AI data retention settings.")
    print(
        wrap_text(
            "Disabling data caching is one step toward zero data retention for "
            "Vertex AI prompts."
        )
    )

    print(
        f"\n{f.warning('Note: Disabling caching may result in slightly slower responses.')}"
    )

    consent = input(
        f"\n{f.info('Disable AI data caching as a zero-retention control? [y/N]: ')}"
    )
    if consent.lower() == "y":
        feedback_text = f.success("Disabling AI data caching")
        with f.yaspin(text=feedback_text) as sp:
            if not _configure_ai_cache(sp):
                return 1
    else:
        print(f.success("Vertex AI cache configuration unchanged."))

    configure_ai_observability()
    SETTINGS.save()
    return 0
