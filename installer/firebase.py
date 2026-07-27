import time
from urllib.parse import quote
import webbrowser

from installer import FORMATTER
from .package_install import install_if_missing
from .utils import validate_input
from .errors import (
    ProviderError,
    ProviderPermissionDenied,
    ProviderTimeout,
    classify_provider_error,
    retry_provider_call,
)
from .state import record_mutation

FIREBASE_API_TIMEOUT = 10
FIREBASE_OPERATION_TIMEOUT_SECONDS = 120
FIREBASE_OPERATION_POLL_DELAYS = (1, 2, 4, 5)
FIREBASE_REQUEST_ATTEMPTS = 4
FIREBASE_MESSAGING_CONFIG_FIELDS = (
    "apiKey",
    "appId",
    "messagingSenderId",
    "projectId",
)
FIREBASE_CLOUD_MESSAGING_URL = (
    "https://console.firebase.google.com/project/"
    "{project_id}/settings/cloudmessaging"
)


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_access_token_refresh_retries_connection_resets
# @features setup
# @dimensions firebase-api authentication retry
def _get_access_token():
    """Get an OAuth2 access token for Google provider management APIs."""
    from installer import FORMATTER

    f = FORMATTER.initialize()

    install_if_missing(
        "google.auth", "Google authentication library", package_name="google-auth"
    )
    import google.auth
    import google.auth.transport.requests

    credentials, project = google.auth.default(
        scopes=[
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/firebase",
        ]
    )
    if not credentials:
        print(
            f.error(
                "Failed to get Application Default Credentials for Google "
                "provider installer."
            )
        )
        return None

    request = google.auth.transport.requests.Request()
    retry_provider_call(
        lambda: credentials.refresh(request),
        description="Google provider access-token refresh",
        attempts=FIREBASE_REQUEST_ATTEMPTS,
        delays=FIREBASE_OPERATION_POLL_DELAYS,
        sleep=time.sleep,
    )
    return credentials.token


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_helpers_use_timeouts_and_report_errors
# @pair firebase-api:quota-project
def _firebase_request_headers(access_token, project_id, *, json_content=False):
    """Build Firebase REST headers without dropping the ADC quota project."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-goog-user-project": project_id,
    }
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_helpers_use_timeouts_and_report_errors
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_api_request_reports_google_reason_and_retries_service_activation
# @features setup
# @dimensions firebase-api diagnostics retry
def _api_request(
    session,
    method,
    url,
    headers,
    json_data=None,
    allow_codes=None,
    *,
    attempts=None,
    delays=None,
    retry_label=None,
):
    """Make a bounded retrying API request and raise a typed failure."""
    allow_codes = allow_codes or []
    attempts = attempts or FIREBASE_REQUEST_ATTEMPTS
    delays = delays or FIREBASE_OPERATION_POLL_DELAYS

    # @testable false
    # @covered-by installer/firebase.py::_api_request
    # @reason closure only formats and applies the parent request's retry delay
    def wait_for_retry(attempt):
        delay = delays[min(attempt, len(delays) - 1)]
        if retry_label:
            f = FORMATTER.initialize()
            print(
                f.info(
                    f"{retry_label} is still becoming available; "
                    f"retrying in {delay} seconds..."
                )
            )
        time.sleep(delay)

    for attempt in range(attempts):
        try:
            if method == "GET":
                resp = session.get(
                    url,
                    headers=headers,
                    timeout=FIREBASE_API_TIMEOUT,
                )
            elif method == "POST":
                resp = session.post(
                    url,
                    headers=headers,
                    json=json_data or {},
                    timeout=FIREBASE_API_TIMEOUT,
                )
            elif method == "PATCH":
                resp = session.patch(
                    url,
                    headers=headers,
                    json=json_data or {},
                    timeout=FIREBASE_API_TIMEOUT,
                )
            else:
                raise ValueError(f"Unsupported provider request method: {method}")
        except Exception as error:
            classified = classify_provider_error(
                error,
                message=f"Google provider {method} request failed: {error}",
            )
            if classified.category != "transient" or attempt == (attempts - 1):
                raise classified from error
            wait_for_retry(attempt)
            continue

        if resp.status_code == 200 or resp.status_code in allow_codes:
            return resp, resp.json() if resp.text else {}
        try:
            response_data = resp.json()
        except (AttributeError, ValueError):
            response_data = {}
        error_data = {}
        if isinstance(response_data, dict):
            error_data = response_data.get("error") or {}
        if not isinstance(error_data, dict):
            error_data = {}
        provider_status = str(error_data.get("status") or "").strip()
        provider_message = " ".join(
            str(error_data.get("message") or resp.text or "").split()
        )[:1000]
        provider_reasons = []
        for detail in error_data.get("details") or ():
            if not isinstance(detail, dict):
                continue
            reason = str(detail.get("reason") or "").strip()
            if reason and reason not in provider_reasons:
                provider_reasons.append(reason)
        status_detail = f"HTTP {resp.status_code}"
        if provider_status:
            status_detail += f" {provider_status}"
        if provider_reasons:
            status_detail += f" ({', '.join(provider_reasons)})"
        if provider_message:
            status_detail += f": {provider_message}"
        classified = classify_provider_error(
            RuntimeError(status_detail),
            message=f"Google provider {method} request failed: {status_detail}",
            status_code=resp.status_code,
        )
        if classified.category != "transient" or attempt == (attempts - 1):
            raise classified
        wait_for_retry(attempt)
    raise ProviderTimeout(f"Google provider request timed out: {method} {url}")


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_operation_polling_uses_operation_endpoint
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_operation_polling_exits_on_error_and_timeout
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_web_app_pagination_and_operation_response
# @features setup
# @dimensions firebase-api operation-response
def _poll_operation(session, operation_name, headers, sp):
    """Poll a Firebase long-running operation until it completes."""
    from installer import FORMATTER

    f = FORMATTER.initialize()

    if not operation_name:
        return {}

    operation_url = f"https://firebase.googleapis.com/v1beta1/{operation_name}"
    deadline = time.monotonic() + FIREBASE_OPERATION_TIMEOUT_SECONDS
    attempt = 0
    while time.monotonic() < deadline:
        _, data = _api_request(session, "GET", operation_url, headers)
        if data.get("done"):
            if data.get("error"):
                print(f.error(f"Firebase operation failed: {data['error']}"))
                sp.fail(f.fail_glyph)
                raise ProviderError(
                    f"Firebase operation failed: {data['error']}"
                )
            return data.get("response") or {}
        delay = FIREBASE_OPERATION_POLL_DELAYS[
            min(attempt, len(FIREBASE_OPERATION_POLL_DELAYS) - 1)
        ]
        time.sleep(delay)
        attempt += 1

    print(f.error(f"Timed out waiting for Firebase operation {operation_name}."))
    sp.fail(f.fail_glyph)
    raise ProviderTimeout(
        f"Timed out waiting for Firebase operation {operation_name}."
    )


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_helpers_use_timeouts_and_report_errors
# @features setup
# @dimensions firebase-api
def _find_web_app(apps, app_id=None, display_name=None):
    """Find a web app by ID or display name."""
    if app_id:
        found = next((a for a in apps if a.get("appId") == app_id), None)
        if found:
            return found
    if display_name:
        return next((a for a in apps if a.get("displayName") == display_name), None)
    return None


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_web_app_pagination_and_operation_response
# @features setup
# @dimensions firebase-api pagination
def _list_web_apps(session, webapps_url, headers):
    """Return every active Firebase WebApp across provider list pages."""
    apps = []
    page_token = None
    seen_tokens = set()
    while True:
        url = webapps_url
        if page_token:
            url = f"{webapps_url}?pageToken={quote(page_token, safe='')}"
        _, data = _api_request(session, "GET", url, headers)
        apps.extend(data.get("apps") or ())
        page_token = data.get("nextPageToken")
        if not page_token:
            return apps
        if page_token in seen_tokens:
            raise RuntimeError("Firebase WebApp pagination repeated a page token.")
        seen_tokens.add(page_token)


# @testable false
# @covered-by installer/firebase.py::_configure_firebase
# @reason provider convergence polling is exercised through Firebase setup tests
def _wait_for_firebase_project(session, project_url, headers, sp):
    """Wait for an already-running addFirebase operation to become visible."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    deadline = time.monotonic() + FIREBASE_OPERATION_TIMEOUT_SECONDS
    attempt = 0
    while time.monotonic() < deadline:
        response, response_data = _api_request(
            session,
            "GET",
            project_url,
            headers,
            allow_codes=[404],
        )
        if response.status_code == 200:
            return response_data
        delay = FIREBASE_OPERATION_POLL_DELAYS[
            min(attempt, len(FIREBASE_OPERATION_POLL_DELAYS) - 1)
        ]
        time.sleep(delay)
        attempt += 1
    print(f.error("Timed out waiting for the Firebase project to become available."))
    sp.fail(f.fail_glyph)
    raise ProviderTimeout(
        "Timed out waiting for the Firebase project to become available."
    )


# @testable false
# @covered-by installer/firebase.py::_configure_firebase
# @reason provider convergence polling is exercised through Firebase setup tests
def _wait_for_web_app(session, webapps_url, headers, display_name, sp):
    """Wait for an already-running WebApp creation to become visible."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    deadline = time.monotonic() + FIREBASE_OPERATION_TIMEOUT_SECONDS
    attempt = 0
    while time.monotonic() < deadline:
        app = _find_web_app(
            _list_web_apps(session, webapps_url, headers),
            display_name=display_name,
        )
        if app:
            return app
        delay = FIREBASE_OPERATION_POLL_DELAYS[
            min(attempt, len(FIREBASE_OPERATION_POLL_DELAYS) - 1)
        ]
        time.sleep(delay)
        attempt += 1
    print(f.error(f"Timed out waiting for Firebase WebApp '{display_name}'."))
    sp.fail(f.fail_glyph)
    raise ProviderTimeout(
        f"Timed out waiting for Firebase WebApp '{display_name}'."
    )


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_recovery_discovers_saved_app_without_overwriting_snapshot
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_web_app_pagination_and_operation_response
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_already_running_web_app_create_is_discovered
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_project_permission_failure_is_not_treated_as_absent
# @tests tests_tooling/test_001d_setup_drift.py::test_firebase_management_discovery_has_used_endpoints
# @features setup
# @dimensions firebase-api recovery provider-discovery settings-preservation conflict provider-convergence permissions not-found api-drift
def _configure_firebase():
    """Set up the Firebase Cloud Messaging project and web app."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    feedback_text = f.success("Configure Firebase Messaging")
    with f.yaspin(text=feedback_text) as sp:
        install_if_missing("requests", "HTTP library for Python")
        import requests

        project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
        base_url = "https://firebase.googleapis.com/v1beta1"

        try:
            access_token = _get_access_token()
        except Exception as e:
            print(f.error(f"Failed to obtain access token:\n{str(e)}"))
            sp.fail(f.fail_glyph)
            raise ProviderError("Failed to obtain a Firebase access token.") from e

        headers = _firebase_request_headers(
            access_token,
            project_id,
            json_content=True,
        )
        session = requests.Session()

        project_url = f"{base_url}/projects/{project_id}"
        resp, _project_data = _api_request(
            session,
            "GET",
            project_url,
            headers,
            allow_codes=[403, 404],
        )

        if resp.status_code == 200:
            sp.write(f.success(f"Firebase linked to {project_id}."))
            record_mutation(
                "reconcile Firebase project",
                action="existing",
                resource="firebase-project",
                identifier=project_id,
            )
        elif resp.status_code == 403:
            print(
                f.error(
                    "Firebase project lookup was forbidden (403). Setup will "
                    "not treat a permission failure as a missing project."
                )
            )
            sp.fail(f.fail_glyph)
            raise ProviderPermissionDenied(
                "Firebase project lookup was forbidden (403)."
            )
        elif resp.status_code == 404:
            sp.write(f.warning(f"Adding Firebase to {project_id}..."))
            add_url = f"{base_url}/projects/{project_id}:addFirebase"
            add_resp, add_data = _api_request(
                session, "POST", add_url, headers, {}, allow_codes=[409]
            )

            if add_resp.status_code == 409:
                sp.write(f.warning("Firebase already being provisioned (409)."))
            else:
                sp.write(f.info("Waiting for Firebase provisioning..."))
                _poll_operation(session, add_data.get("name"), headers, sp)

            _wait_for_firebase_project(session, project_url, headers, sp)
            record_mutation(
                "reconcile Firebase project",
                action="created",
                resource="firebase-project",
                identifier=project_id,
            )
            sp.write(f.success(f"Firebase provisioned for {project_id}."))
        else:
            print(f.error("Failed to check Firebase status."))
            print(f"Status {resp.status_code}: {resp.text}")
            sp.fail(f.fail_glyph)
            raise classify_provider_error(
                RuntimeError(resp.text[:1000]),
                message="Failed to check Firebase project status.",
                status_code=resp.status_code,
            )

        app_display_name = SETTINGS.APP["APP_NAME"]
        webapps_url = f"{base_url}/projects/{project_id}/webApps"

        existing_apps = _list_web_apps(session, webapps_url, headers)

        saved_app_id = (SETTINGS.APP.get("FIREBASE_CONFIG") or {}).get("appId")
        found_app = _find_web_app(
            existing_apps,
            app_id=saved_app_id,
            display_name=None if saved_app_id else app_display_name,
        )

        if found_app:
            app_id = found_app.get("appId")
            record_mutation(
                "reconcile Firebase web app",
                action="existing",
                resource="firebase-web-app",
                identifier=app_id,
            )
        else:
            create_response, create_data = _api_request(
                session,
                "POST",
                webapps_url,
                headers,
                {"displayName": app_display_name},
                allow_codes=[409],
            )
            if create_response.status_code == 409:
                sp.write(
                    f.warning(
                        "Firebase WebApp creation is already running; waiting "
                        "for the saved display name."
                    )
                )
                found_app = _wait_for_web_app(
                    session,
                    webapps_url,
                    headers,
                    app_display_name,
                    sp,
                )
            else:
                found_app = _poll_operation(
                    session,
                    create_data.get("name"),
                    headers,
                    sp,
                )
                if not found_app.get("appId"):
                    found_app = _wait_for_web_app(
                        session,
                        webapps_url,
                        headers,
                        app_display_name,
                        sp,
                    )
            app_id = found_app.get("appId")
            if app_id:
                record_mutation(
                    "reconcile Firebase web app",
                    action="created",
                    resource="firebase-web-app",
                    identifier=app_id,
                )
        if not app_id:
            print(f.error("Firebase WebApp discovery returned no appId."))
            sp.fail(f.fail_glyph)
            raise ProviderError("Firebase WebApp discovery returned no appId.")

        config_url = f"{base_url}/projects/{project_id}/webApps/{app_id}/config"
        _, firebase_config = _api_request(session, "GET", config_url, headers)

        sp.ok(f.ok_glyph)
        return firebase_config


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_vapid_instructions_open_current_project_cloud_messaging_page
# @features setup
# @dimensions firebase-web-push browser operator-guidance
def print_vapid_instructions():
    """Open Firebase Cloud Messaging settings and guide VAPID key creation."""
    from config import SETTINGS
    from installer import FORMATTER

    f = FORMATTER.initialize()
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    cloud_messaging_url = FIREBASE_CLOUD_MESSAGING_URL.format(
        project_id=project_id
    )
    print(
        f"\n{f.warning('To set up web push notifications, you will need a VAPID key:')}"
    )
    print(f"\nOpening Firebase Cloud Messaging for project '{project_id}':")
    print(f"  {cloud_messaging_url}")
    try:
        webbrowser.open_new_tab(cloud_messaging_url)
    except webbrowser.Error:
        pass

    print("1. Look for the 'Web Push certificates' section.")
    print("2. Generate a new key pair if none exists.")
    print("3. Copy the 'Key pair' value and paste it below.")


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_validators_cover_expected_inputs
# @features setup
# @dimensions validation
def _validate_vapid_key(key):
    """Validate VAPID public key format (P-256 uncompressed point, base64url encoded)."""
    import base64

    key = key.strip()
    padding = 4 - (len(key) % 4)
    if padding != 4:
        key += "=" * padding

    try:
        decoded = base64.urlsafe_b64decode(key)
    except Exception:
        return False

    if len(decoded) != 65:
        return False

    if decoded[0] != 0x04:
        return False

    return True


# @testable false
# @covered-by installer/firebase.py::setup_firebase
# @reason interactive input wrapper owned by the Firebase setup flow
@validate_input(
    "Enter VAPID Key",
    validation_fn=_validate_vapid_key,
    error_msg="Invalid VAPID key format. Please check the key and try again.",
)
def _get_vapid_key(value):
    return value.strip()


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_firebase_messaging_client_config_excludes_auth_fields
# @features setup
# @dimensions firebase-messaging public-config auth-separation
def _messaging_client_config(config):
    """Keep only Firebase WebApp fields used by Cloud Messaging."""
    return {
        key: value
        for key in FIREBASE_MESSAGING_CONFIG_FIELDS
        if (value := (config or {}).get(key))
    }


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @features setup
# @dimensions settings-save
def setup_firebase():
    """Set up the Firebase Cloud Messaging WebApp and VAPID key."""
    from config import SETTINGS
    from installer import FORMATTER

    f = FORMATTER.initialize()
    firebase_config = _configure_firebase()

    if not firebase_config:
        print(f.error("Firebase Messaging setup failed."))
        raise ProviderError("Firebase Messaging setup returned no configuration.")

    existing_config = SETTINGS.APP.get("FIREBASE_CONFIG") or {}
    messaging_config = _messaging_client_config(firebase_config)
    if existing_config.get("vapidKey"):
        messaging_config["vapidKey"] = existing_config["vapidKey"]
    if existing_config != messaging_config:
        SETTINGS.APP["FIREBASE_CONFIG"] = messaging_config
        SETTINGS.save()

    if "vapidKey" not in SETTINGS.APP["FIREBASE_CONFIG"]:
        print_vapid_instructions()

        SETTINGS.APP["FIREBASE_CONFIG"]["vapidKey"] = _get_vapid_key()
        SETTINGS.save()

    return True
