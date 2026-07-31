"""Standalone Google Identity Platform provisioning."""

import time
from urllib.parse import quote, urlsplit

from installer import FORMATTER, wrap_text
from .errors import (
    ProviderConflict,
    ProviderError,
    ProviderInvalidInput,
    ProviderTimeout,
)
from .google_provider import (
    PROVIDER_OPERATION_POLL_DELAYS,
    PROVIDER_OPERATION_TIMEOUT_SECONDS,
    _api_request,
    _google_request_headers,
    _get_access_token,
)
from .package_install import install_if_missing
from .state import record_mutation

IDENTITY_PLATFORM_SUBTYPE = "IDENTITY_PLATFORM"
IDENTITY_PLATFORM_CORE_UPDATE_MASK = (
    "authorizedDomains",
    "signIn.email.enabled",
    "signIn.email.passwordRequired",
)
GOOGLE_PROVIDER_ID = "google.com"
IDENTITY_INITIALIZATION_ATTEMPTS = 8
IDENTITY_INITIALIZATION_DELAYS = (2, 4, 8, 15, 20, 30, 30)


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_config_contract
# @features setup
# @dimensions identity-platform provider-discovery permissions
def get_identity_platform_config(session, project_id, headers):
    """Read the live project-level Identity Platform configuration."""
    url = (
        f"https://identitytoolkit.googleapis.com/admin/v2/projects/{project_id}/config"
    )
    response, data = _api_request(
        session,
        "GET",
        url,
        headers,
        allow_codes=[404],
    )
    return data if response.status_code == 200 else None


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_config_contract
# @features setup
# @dimensions identity-platform authorized-domain
def identity_platform_target(app_url):
    """Return the application domain and local email action-handler URL."""
    app_url = str(app_url or "").strip().rstrip("/")
    parsed = urlsplit(app_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProviderInvalidInput(
            "Identity Platform requires an HTTPS application URL."
        )
    return parsed.hostname, f"{app_url}/users/login"


# @testable false
# @covered-by installer/identity.py::identity_platform_config_matches
# @covered-by installer/recovery.py::_probe_identity_platform
# @reason nested provider-state adapter is exercised through matching and recovery
def _email_password_enabled(config):
    email = ((config or {}).get("signIn") or {}).get("email") or {}
    return email.get("enabled") is True and email.get("passwordRequired") is True


# @testable false
# @covered-by installer/identity.py::identity_platform_config_matches
# @covered-by installer/identity.py::reconcile_identity_platform
# @reason core provider-state predicate is exercised through public reconciliation
def _core_matches(config, app_url):
    domain, _ = identity_platform_target(app_url)
    domains = {
        str(value).casefold() for value in (config or {}).get("authorizedDomains") or ()
    }
    return (
        (config or {}).get("subtype") == IDENTITY_PLATFORM_SUBTYPE
        and _email_password_enabled(config)
        and domain.casefold() in domains
    )


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_config_contract
# @features setup
# @dimensions identity-platform provider-state authorized-domain
def identity_platform_config_matches(config, app_url):
    """Return whether the live standalone provider matches Lagniappe's contract."""
    return _core_matches(config, app_url)


# @testable false
# @covered-by installer/identity.py::reconcile_identity_platform
# @reason bounded convergence polling is owned by provider reconciliation
def _wait_for_config(session, project_id, headers, predicate):
    deadline = time.monotonic() + PROVIDER_OPERATION_TIMEOUT_SECONDS
    attempt = 0
    while time.monotonic() < deadline:
        config = get_identity_platform_config(session, project_id, headers)
        if config is not None and predicate(config):
            return config
        delay = PROVIDER_OPERATION_POLL_DELAYS[
            min(attempt, len(PROVIDER_OPERATION_POLL_DELAYS) - 1)
        ]
        time.sleep(delay)
        attempt += 1
    raise ProviderTimeout(
        f"Timed out verifying Identity Platform for project '{project_id}'."
    )


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_verification_preserves_standalone_subtype
# @features setup
# @dimensions identity-platform provider-state auth-separation
def _ensure_standalone_subtype(config, project_id):
    subtype = str((config or {}).get("subtype") or "").strip()
    if subtype != IDENTITY_PLATFORM_SUBTYPE:
        raise ProviderConflict(
            f"Project '{project_id}' has authentication subtype "
            f"'{subtype or 'unavailable'}'. Lagniappe requires standalone "
            f"Identity Platform subtype '{IDENTITY_PLATFORM_SUBTYPE}'."
        )


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_setup_is_idempotent_for_matching_provider_state
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_initialization_retries_api_activation
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_initialization_accepts_existing_provider
# @features setup
# @dimensions identity-platform provider-state authorized-domain provider-convergence retry diagnostics idempotency
def reconcile_identity_platform(session, project_id, headers, app_url):
    """Initialize standalone Identity Platform and reconcile email authentication."""
    config = get_identity_platform_config(session, project_id, headers)
    initialize = config is None
    if initialize:
        initialize_url = (
            "https://identitytoolkit.googleapis.com/v2/"
            f"projects/{project_id}/identityPlatform:initializeAuth"
        )
        response, _ = _api_request(
            session,
            "POST",
            initialize_url,
            headers,
            {},
            allow_codes=[409],
            attempts=IDENTITY_INITIALIZATION_ATTEMPTS,
            delays=IDENTITY_INITIALIZATION_DELAYS,
        )
        record_mutation(
            "initialize Identity Platform",
            action="created" if response.status_code == 200 else "existing",
            resource="identity-platform-config",
            identifier=project_id,
        )
        config = _wait_for_config(
            session,
            project_id,
            headers,
            lambda value: bool(value),
        )

    _ensure_standalone_subtype(config, project_id)

    if not _core_matches(config, app_url):
        domain, _ = identity_platform_target(app_url)
        authorized_domains = []
        seen_domains = set()
        for value in [*(config.get("authorizedDomains") or ()), domain]:
            value = str(value).strip()
            normalized = value.casefold()
            if value and normalized not in seen_domains:
                authorized_domains.append(value)
                seen_domains.add(normalized)

        update_mask = quote(
            ",".join(IDENTITY_PLATFORM_CORE_UPDATE_MASK),
            safe=",.",
        )
        config_url = (
            "https://identitytoolkit.googleapis.com/admin/v2/"
            f"projects/{project_id}/config?updateMask={update_mask}"
        )
        _api_request(
            session,
            "PATCH",
            config_url,
            headers,
            {
                "authorizedDomains": authorized_domains,
                "signIn": {
                    "email": {
                        "enabled": True,
                        "passwordRequired": True,
                    }
                },
            },
        )
        record_mutation(
            "reconcile Identity Platform email authentication",
            action="updated",
            resource="identity-platform-config",
            identifier=project_id,
        )
        config = _wait_for_config(
            session,
            project_id,
            headers,
            lambda value: _core_matches(value, app_url),
        )
    else:
        record_mutation(
            "reconcile Identity Platform email authentication",
            action="existing",
            resource="identity-platform-config",
            identifier=project_id,
        )

    return config


# @testable false
# @covered-by installer/identity.py::setup_identity_platform
# @reason public config projection is exercised through persisted setup output
def _public_client_config(config, project_id):
    api_key = str((((config or {}).get("client") or {}).get("apiKey")) or "").strip()
    if not api_key:
        raise ProviderError("Identity Platform did not return its public Web API key.")
    return {
        "apiKey": api_key,
        "projectId": project_id,
    }


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_setup_is_idempotent_for_matching_provider_state
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_setup_finishes_spinner_before_reporting_error
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @features setup
# @dimensions identity-platform settings-save provider-state authorized-domain diagnostics spinner error-reporting
def setup_identity_platform(app_url=None):
    """Set up standalone Identity Platform email/password authentication."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    install_if_missing("requests", "HTTP library for Python")
    import requests

    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    app_url = app_url or (
        f"https://{SETTINGS.APP['CUSTOM_DOMAIN']}"
        if SETTINGS.APP.get("CUSTOM_DOMAIN")
        else SETTINGS.APP["APP_URL"]
    )
    with f.yaspin(text=f.success("Configure Identity Platform")) as sp:
        try:
            access_token = _get_access_token()
            headers = _google_request_headers(access_token, project_id)
            config = reconcile_identity_platform(
                requests.Session(),
                project_id,
                headers,
                app_url,
            )
        except Exception as error:
            sp.fail(f.fail_glyph)
            print(
                f.error(
                    wrap_text(f"Could not configure Identity Platform: {error}")
                )
            )
            raise ProviderError("Could not configure Identity Platform.") from error

        if not _core_matches(config, app_url):
            sp.fail(f.fail_glyph)
            raise ProviderError("Identity Platform configuration did not verify.")
        sp.ok(f.ok_glyph)

    client_config = _public_client_config(config, project_id)
    if SETTINGS.APP.get("IDENTITY_PLATFORM_CONFIG") != client_config:
        SETTINGS.APP["IDENTITY_PLATFORM_CONFIG"] = client_config
        SETTINGS.save()
    return True


# @testable false
# @covered-by installer/identity.py::setup_google_provider
# @reason provider lookup is exercised through Google-provider reconciliation
def get_google_provider_config(session, project_id, headers):
    """Return the live Google provider config, or None when it is absent."""
    url = (
        "https://identitytoolkit.googleapis.com/admin/v2/"
        f"projects/{project_id}/defaultSupportedIdpConfigs/{GOOGLE_PROVIDER_ID}"
    )
    response, data = _api_request(
        session,
        "GET",
        url,
        headers,
        allow_codes=[404],
    )
    return data if response.status_code == 200 else None


# @testable false
# @covered-by installer/identity.py::setup_google_provider
# @reason provider-state predicate is exercised through reconciliation
def google_provider_matches(config, client_id):
    return bool(
        config
        and config.get("enabled") is True
        and str(config.get("clientId") or "").strip() == str(client_id or "").strip()
    )


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_google_provider_reconciliation
# @features setup
# @dimensions identity-platform google-oauth provider-state secrets
def setup_google_provider(client_id, client_secret=None):
    """Configure the Google provider without persisting its OAuth secret."""
    from config import SETTINGS

    install_if_missing("requests", "HTTP library for Python")
    import requests

    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    access_token = _get_access_token()
    headers = _google_request_headers(
        access_token,
        project_id,
        json_content=True,
    )
    session = requests.Session()
    existing = get_google_provider_config(session, project_id, headers)
    if google_provider_matches(existing, client_id):
        record_mutation(
            "reconcile Identity Platform Google provider",
            action="existing",
            resource="identity-provider",
            identifier=GOOGLE_PROVIDER_ID,
        )
        return True

    client_secret = str(client_secret or "").strip()
    if not client_secret:
        raise ProviderInvalidInput(
            "The Google OAuth client secret is required to configure the "
            "Identity Platform Google provider."
        )

    payload = {
        "enabled": True,
        "clientId": str(client_id).strip(),
        "clientSecret": client_secret,
    }
    if existing is None:
        url = (
            "https://identitytoolkit.googleapis.com/admin/v2/"
            f"projects/{project_id}/defaultSupportedIdpConfigs"
            f"?idpId={GOOGLE_PROVIDER_ID}"
        )
        _api_request(session, "POST", url, headers, payload)
        action = "created"
    else:
        update_mask = quote("enabled,clientId,clientSecret", safe=",.")
        url = (
            "https://identitytoolkit.googleapis.com/admin/v2/"
            f"projects/{project_id}/defaultSupportedIdpConfigs/"
            f"{GOOGLE_PROVIDER_ID}?updateMask={update_mask}"
        )
        _api_request(session, "PATCH", url, headers, payload)
        action = "updated"

    record_mutation(
        "reconcile Identity Platform Google provider",
        action=action,
        resource="identity-provider",
        identifier=GOOGLE_PROVIDER_ID,
    )
    verified = get_google_provider_config(session, project_id, headers)
    if not google_provider_matches(verified, client_id):
        raise ProviderError(
            "Identity Platform's Google provider did not verify after update."
        )
    return True
