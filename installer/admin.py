import json
import re
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from installer import wrap_text
from installer.errors import (
    ProviderInvalidInput,
    classify_provider_error,
)
from runner.context import REPOSITORY_ROOT, setup_command

from .utils import validate_input


GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_CLIENT_PROBE_TIMEOUT = 10
OAUTH_CLIENT_FILE_MAX_BYTES = 64 * 1024
OAUTH_CLIENT_FILE = (
    REPOSITORY_ROOT / "config" / "files" / "google_oauth_credentials.json"
)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_instructions_open_current_project_clients_page
# @features setup
# @dimensions oauth browser provider-apis
def print_oauth_instructions():
    """Print instructions for setting up OAuth credentials."""
    from config import SETTINGS

    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    account = str(SETTINGS.GCLOUD_CONFIG.get("ACCOUNT") or "").strip()
    clients_url = (
        "https://console.cloud.google.com/auth/clients"
        f"?project={project_id}"
    )
    app_name = SETTINGS.APP["APP_NAME"]
    app_origin = (
        f"https://{SETTINGS.APP['CUSTOM_DOMAIN']}"
        if SETTINGS.APP.get("CUSTOM_DOMAIN")
        else SETTINGS.APP["APP_URL"]
    )

    print("\nConfigure Google Sign-In:")
    print(
        wrap_text(
            "Identity Platform is ready. Google Auth Platform registration and "
            "OAuth client creation are the remaining one-time browser steps."
        )
    )
    print(f"\nOpening Google Auth Platform for project '{project_id}':")
    print(f"  {clients_url}")
    if account:
        print(f"  Required browser account: {account}")
    try:
        webbrowser.open_new_tab(clients_url)
    except webbrowser.Error:
        pass

    if account:
        print(
            wrap_text(
                "\nBefore continuing, confirm the Google Cloud Console "
                f"profile is '{account}'. If Google says you need additional "
                "access, switch the browser to this account and reload the "
                "page; setup already verified this account's project "
                "permissions."
            )
        )

    print(
        wrap_text(
            "\n1. If Google says the Auth Platform is not configured, "
            "click 'Get started':"
        )
    )
    print(
        wrap_text(
            f"   - App information: use '{app_name}' and select a support email"
        )
    )
    print(wrap_text("   - Audience: choose 'External'"))
    print(
        wrap_text(
            "   - Contact information: enter your email and finish registration"
        )
    )
    print(
        wrap_text(
            "2. For a new or replacement client, click 'Create client'. For "
            "secret rotation, open the existing Web application client and "
            "create a new Client secret instead."
        )
    )
    print(
        wrap_text(
            "3. For a new client, choose 'Web application' and enter the "
            "values below. The "
            "client type must say 'Web application'; a 'Desktop app' client "
            "will not work."
        )
    )
    print(f"   - Name: {app_name}")
    print(f"   - Authorized JavaScript origin: {app_origin}")
    print(f"   - Authorized redirect URI: {SETTINGS.APP['GOOGLE_LOGIN_URI']}")
    print(
        wrap_text(
            "4. Click 'Create'. Under Client secrets, click 'Download JSON'. "
            "Move the downloaded file to the exact path below, renaming it "
            "'google_oauth_credentials.json':"
        )
    )
    print(f"   {OAUTH_CLIENT_FILE}")
    print(
        wrap_text(
            "5. Return to setup and press Enter. Setup will verify the Web "
            "client type, project, JavaScript origin, and redirect URI from "
            "that file before sending its client ID and secret to Identity "
            "Platform. The secret will not be saved in Lagniappe settings.\n"
        )
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_validators_cover_expected_inputs
# @features setup
# @dimensions validation
def validate_oauth_client_id(client_id):
    """Validate OAuth client ID format."""
    return bool(re.match(r"^\d+[-\w]+\.apps\.googleusercontent\.com$", client_id))


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_web_client_probe_accepts_exact_callback
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_web_client_probe_rejects_redirect_mismatch
# @features setup
# @dimensions oauth client-type redirect-uri validation provider-apis failure-isolation
def verify_oauth_web_client(client_id, redirect_uri, *, request_get=None):
    """Verify that Google accepts Lagniappe's callback for an OAuth client."""
    client_id = str(client_id or "").strip()
    redirect_uri = str(redirect_uri or "").strip()
    parsed_redirect = urlsplit(redirect_uri)
    if not validate_oauth_client_id(client_id):
        raise ProviderInvalidInput("Invalid Google OAuth Client ID format.")
    if (
        parsed_redirect.scheme != "https"
        or not parsed_redirect.hostname
        or parsed_redirect.query
        or parsed_redirect.fragment
    ):
        raise ProviderInvalidInput(
            "Google OAuth verification requires the saved HTTPS callback URI."
        )

    if request_get is None:
        from .package_install import install_if_missing

        install_if_missing("requests", "HTTP library for Python")
        import requests

        request_get = requests.get

    try:
        response = request_get(
            GOOGLE_OAUTH_AUTHORIZE_URL,
            params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": "lagniappe-oauth-client-check",
            },
            allow_redirects=False,
            timeout=OAUTH_CLIENT_PROBE_TIMEOUT,
        )
    except Exception as error:
        raise classify_provider_error(
            error,
            message=f"Could not verify the Google OAuth client: {error}",
        ) from error

    status_code = int(getattr(response, "status_code", 0) or 0)
    headers = getattr(response, "headers", {}) or {}
    location = str(headers.get("Location") or "")
    location_parts = urlsplit(location)
    provider_detail = " ".join(
        (
            str(getattr(response, "text", "") or ""),
            location,
        )
    ).casefold()
    repair_action = (
        "Download a Google OAuth Web-client JSON containing the exact "
        f"redirect URI {redirect_uri}, place it at {OAUTH_CLIENT_FILE}, then "
        f"run {setup_command('oauth')}."
    )
    if (
        "redirect_uri_mismatch" in provider_detail
        or "redirect uri mismatch" in provider_detail
        or (
            location_parts.hostname == "accounts.google.com"
            and location_parts.path.rstrip("/") == "/signin/oauth/error"
        )
    ):
        raise ProviderInvalidInput(
            "Google rejected Lagniappe's required OAuth callback. The selected "
            "client may not be a Web application client, may not list this "
            "exact authorized redirect URI, or may still be propagating: "
            f"{redirect_uri}",
            repair_action=repair_action,
        )
    if (
        "invalid_client" in provider_detail
        or "oauth client was not found" in provider_detail
        or "oauth client was deleted" in provider_detail
    ):
        raise ProviderInvalidInput(
            "Google did not recognize the selected OAuth client. Confirm that "
            "the client belongs to this project and is still active.",
            repair_action=repair_action,
        )
    if status_code < 200 or status_code >= 400:
        raise classify_provider_error(
            RuntimeError(
                "Google OAuth authorization probe returned "
                f"HTTP {status_code}."
            ),
            message=(
                "Google did not accept the OAuth client verification request "
                f"(HTTP {status_code})."
            ),
            status_code=status_code,
        )
    return True


# @testable false
# @covered-by installer/admin.py::load_oauth_client_credentials
# @reason downloaded OAuth JSON list normalization is exercised by file validation
def _oauth_uri_values(value):
    """Return the nonempty URI strings from one downloaded OAuth JSON field."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_credentials_file_requires_web_project_and_exact_urls
# @features setup
# @dimensions oauth credential-file client-type project-isolation javascript-origin redirect-uri secrets validation
def load_oauth_client_credentials(
    credential_path,
    *,
    project_id,
    javascript_origin,
    redirect_uri,
):
    """Validate downloaded Web-client JSON and return its in-memory credentials."""
    credential_path = Path(credential_path)
    try:
        if credential_path.stat().st_size > OAUTH_CLIENT_FILE_MAX_BYTES:
            raise ProviderInvalidInput(
                "The Google OAuth credential JSON is unexpectedly large."
            )
        payload = json.loads(credential_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ProviderInvalidInput(
            f"Google OAuth credential JSON was not found at: {credential_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ProviderInvalidInput(
            f"Google OAuth credential file is not valid JSON: {credential_path}"
        ) from error
    except OSError as error:
        raise ProviderInvalidInput(
            f"Could not read Google OAuth credential JSON at {credential_path}: "
            f"{error}"
        ) from error

    if not isinstance(payload, dict):
        raise ProviderInvalidInput(
            "Google OAuth credential JSON must contain one client object."
        )
    web = payload.get("web")
    if not isinstance(web, dict):
        client_type = "Desktop app" if "installed" in payload else "unknown"
        raise ProviderInvalidInput(
            "Google OAuth credential JSON is not for a Web application "
            f"client (detected type: {client_type})."
        )

    client_id = str(web.get("client_id") or "").strip()
    client_secret = str(web.get("client_secret") or "").strip()
    file_project_id = str(web.get("project_id") or "").strip()
    origins = _oauth_uri_values(web.get("javascript_origins"))
    redirect_uris = _oauth_uri_values(web.get("redirect_uris"))

    if not validate_oauth_client_id(client_id):
        raise ProviderInvalidInput(
            "Google OAuth credential JSON contains an invalid Client ID."
        )
    if not client_secret:
        raise ProviderInvalidInput(
            "Google OAuth credential JSON does not contain a Client secret."
        )
    if file_project_id != str(project_id or "").strip():
        raise ProviderInvalidInput(
            "Google OAuth credential JSON belongs to project "
            f"'{file_project_id or 'unknown'}', not the selected project "
            f"'{project_id}'."
        )
    if javascript_origin not in origins:
        raise ProviderInvalidInput(
            "Google OAuth credential JSON does not contain the required "
            f"Authorized JavaScript origin: {javascript_origin}"
        )
    if redirect_uri not in redirect_uris:
        raise ProviderInvalidInput(
            "Google OAuth credential JSON does not contain the required "
            f"Authorized redirect URI: {redirect_uri}"
        )
    return client_id, client_secret


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_credentials_file_retry_reloads_or_waits_for_propagation
# @features setup
# @dimensions oauth credential-file propagation interactive-retry secrets
def _get_verified_oauth_credentials(settings, credential_path=OAUTH_CLIENT_FILE):
    """Load exact local OAuth settings and keep setup active through propagation."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    credential_path = Path(credential_path)
    project_id = settings.GCLOUD_CONFIG["PROJECT"]
    javascript_origin = (
        f"https://{settings.APP['CUSTOM_DOMAIN']}"
        if settings.APP.get("CUSTOM_DOMAIN")
        else settings.APP["APP_URL"]
    )
    redirect_uri = settings.APP["GOOGLE_LOGIN_URI"]
    credentials = None
    print("\nPlace the downloaded Google OAuth JSON at:")
    print(f"  {credential_path}")
    account = str(settings.GCLOUD_CONFIG.get("ACCOUNT") or "").strip()
    account_guidance = f" while signed in as '{account}'" if account else ""
    choice = input(
        f.info(
            "Complete the Google Auth Platform browser steps"
            f"{account_guidance}, place the downloaded JSON at the path "
            "above, then press Enter to verify it, or X to stop: "
        )
    ).strip().casefold()
    if choice in {"x", "exit"}:
        raise ProviderInvalidInput(
            "Google OAuth credential setup stopped before verification.",
            repair_action=(
                f"Place a correct Web-client JSON at {credential_path}, "
                f"then run {setup_command('oauth')}."
            ),
        )

    while True:
        if credentials is None:
            try:
                credentials = load_oauth_client_credentials(
                    credential_path,
                    project_id=project_id,
                    javascript_origin=javascript_origin,
                    redirect_uri=redirect_uri,
                )
            except ProviderInvalidInput as error:
                print(f.error(wrap_text(str(error))))
                choice = input(
                    f.info(
                        "Place or correct the JSON at the path above, then "
                        "press Enter to retry, or X to stop: "
                    )
                ).strip().casefold()
                if choice in {"x", "exit"}:
                    raise ProviderInvalidInput(
                        str(error),
                        repair_action=(
                            f"Place a correct Web-client JSON at "
                            f"{credential_path}, then run "
                            f"{setup_command('oauth')}."
                        ),
                    ) from error
                continue

        client_id, _client_secret = credentials
        try:
            verify_oauth_web_client(client_id, redirect_uri)
            return credentials
        except ProviderInvalidInput as error:
            print(f.error(wrap_text(str(error))))
            print(
                wrap_text(
                    "The downloaded JSON already matches the required Web "
                    "client type, project, JavaScript origin, and redirect "
                    "URI. Google may still be applying the new client, or the "
                    "client may no longer be active."
                )
            )
            choice = input(
                f.info(
                    "Press Enter to retry Google, R to reload a replaced JSON "
                    "file, or X to stop: "
                )
            ).strip().casefold()
            if choice in {"x", "exit"}:
                raise
            if choice in {"r", "reload", "replace"}:
                credentials = None


# @testable false
# @covered-by installer/admin.py::setup_admin_and_oauth
# @reason existing-client propagation retry is covered by the admin setup boundary
def _verify_saved_oauth_client(client_id, redirect_uri):
    """Keep an existing setup run at OAuth while Google applies saved state."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    while True:
        try:
            return verify_oauth_web_client(client_id, redirect_uri)
        except ProviderInvalidInput as error:
            print(f.error(wrap_text(str(error))))
            choice = input(
                f.info(
                    "Press Enter to retry this saved client, or X to stop and "
                    f"run {setup_command('oauth')} with a replacement: "
                )
            ).strip().casefold()
            if choice in {"x", "exit"}:
                raise


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_credential_retention_message
# @features setup
# @dimensions oauth credential-file secrets retention rotation
def _print_oauth_file_retention_message(credential_path=OAUTH_CLIENT_FILE):
    """Explain the local credential file's post-setup retention choices."""
    print(
        wrap_text(
            "Identity Platform now stores the OAuth client secret. Lagniappe "
            f"runtime does not need {credential_path}. You may delete the "
            "local JSON or move it to secure storage. The config/files path "
            "is excluded from Git and App Engine uploads, but the JSON still "
            "contains a secret. To replace or rotate Google OAuth later, "
            "place the new downloaded JSON at that path and run "
            f"{setup_command('oauth')}."
        )
    )


# @testable false
# @covered-by installer/admin.py::setup_admin_and_oauth
# @reason interactive input wrapper owned by the admin/OAuth setup flow
@validate_input("Enter admin name", default="Admin")
def _get_admin_name(value):
    return value


# @testable false
# @covered-by installer/admin.py::setup_admin_and_oauth
# @reason interactive input wrapper owned by the admin/OAuth setup flow
@validate_input("Enter admin email")
def _get_admin_email(value):
    return value


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_google_signin_is_an_explicit_preserved_setup_choice
# @features setup
# @dimensions google-oauth optional settings-save rerun
def configure_google_signin_choice():
    """Read or collect the persisted operator choice for Google sign-in."""
    from config import SETTINGS

    existing = SETTINGS.APP.get("GOOGLE_SIGNIN_ENABLED")
    if existing is None and str(SETTINGS.APP.get("GOOGLE_CLIENT_ID") or "").strip():
        existing = True
    if existing is not None:
        if not isinstance(existing, bool):
            normalized = str(existing).strip().casefold()
            if normalized not in {"true", "false"}:
                raise ValueError("GOOGLE_SIGNIN_ENABLED must be true or false.")
            existing = normalized == "true"
        SETTINGS.APP["GOOGLE_SIGNIN_ENABLED"] = existing
        print(f"Google sign-in is {'enabled' if existing else 'disabled'}.")
        return existing

    print("\nOptional Google Sign-In")
    print(
        wrap_text(
            "Email and password authentication will remain available either "
            "way. Enabling Google sign-in adds the Google Auth Platform and "
            "OAuth client setup steps."
        )
    )
    enabled = input("Enable Google sign-in? [Y/n]: ").strip().casefold() not in {
        "n",
        "no",
    }
    SETTINGS.APP["GOOGLE_SIGNIN_ENABLED"] = enabled
    print(f"Google sign-in {'enabled' if enabled else 'disabled'}.")
    return enabled


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_disabled_google_signin_skips_oauth_setup
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_admin_oauth_rejection_precedes_provider_update
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_existing_admin_oauth_can_replace_rejected_saved_client
# @features setup
# @dimensions admin oauth settings-save client-type redirect-uri failure-isolation identity-platform interactive-retry optional disabled-provider
def setup_admin_and_oauth():
    """Configure the admin and Identity Platform's Google provider."""
    from config import SETTINGS
    from installer.identity import setup_google_provider

    settings_changed = False
    if "ADMIN_NAME" not in SETTINGS.APP:
        SETTINGS.APP["ADMIN_NAME"] = _get_admin_name()
        SETTINGS.APP["ADMIN_EMAIL"] = _get_admin_email()
        settings_changed = True

    previous_google_choice = SETTINGS.APP.get("GOOGLE_SIGNIN_ENABLED")
    google_signin_enabled = configure_google_signin_choice()
    if previous_google_choice is None or previous_google_choice is not google_signin_enabled:
        settings_changed = True

    if settings_changed:
        SETTINGS.save()

    if not google_signin_enabled:
        print("Skipping Google OAuth and Identity Platform provider setup.")
        return True

    if "GOOGLE_CLIENT_ID" not in SETTINGS.APP:
        print_oauth_instructions()
        client_id, client_secret = _get_verified_oauth_credentials(SETTINGS)
        setup_google_provider(client_id, client_secret)
        SETTINGS.APP["GOOGLE_CLIENT_ID"] = client_id
        SETTINGS.save()
        _print_oauth_file_retention_message()
    else:
        saved_client_id = SETTINGS.APP["GOOGLE_CLIENT_ID"]
        _verify_saved_oauth_client(
            saved_client_id,
            SETTINGS.APP["GOOGLE_LOGIN_URI"],
        )
        client_id = saved_client_id
        try:
            setup_google_provider(client_id)
        except ProviderInvalidInput:
            print(
                wrap_text(
                    "Identity Platform needs OAuth credentials to repair its "
                    "Google provider. Download the existing Web client's JSON "
                    "if it is still available, or create a replacement Web "
                    "client using the exact values below."
                )
            )
            print_oauth_instructions()
            client_id, client_secret = _get_verified_oauth_credentials(SETTINGS)
            setup_google_provider(client_id, client_secret)
            _print_oauth_file_retention_message()
        if client_id != saved_client_id:
            SETTINGS.APP["GOOGLE_CLIENT_ID"] = client_id
            SETTINGS.save()


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_cli_replaces_settings_and_deploys
# @features setup
# @dimensions oauth cli client-type redirect-uri identity-platform settings-save deploy
def configure_oauth():
    """Replace Google Sign-In OAuth settings for an existing installation."""
    from .verify import prepare_existing_installation

    prepare_existing_installation()

    from config import SETTINGS
    from installer import FORMATTER, utils
    from installer.identity import setup_google_provider

    f = FORMATTER.initialize()
    current_client_id = str(SETTINGS.APP.get("GOOGLE_CLIENT_ID") or "").strip()
    print(f"\n{f.info('Lagniappe Google OAuth Configuration')}")
    if current_client_id:
        print(f"Current OAuth client ID: {current_client_id}")
    print_oauth_instructions()

    client_id, client_secret = _get_verified_oauth_credentials(SETTINGS)
    setup_google_provider(client_id, client_secret)
    SETTINGS.APP["GOOGLE_CLIENT_ID"] = client_id
    SETTINGS.APP["GOOGLE_SIGNIN_ENABLED"] = True
    SETTINGS.save()
    print(f.success("Google OAuth settings verified and saved."))
    _print_oauth_file_retention_message()

    consent = input(f.info("Deploy the updated OAuth settings now? [Y/n]: "))
    if consent.strip().casefold() != "n":
        utils.deploy_to_app_engine()
        print(f.success("Google OAuth settings deployed."))
    else:
        print(
            f.warning(
                "OAuth settings were saved locally but are not active in the "
                "deployed app. Google sign-in may remain unavailable until "
                "the app is deployed."
            )
        )
    return 0
