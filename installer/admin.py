import re
import webbrowser

from installer import wrap_text
from installer.errors import ProviderInvalidInput

from .utils import validate_input


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_oauth_instructions_open_current_project_clients_page
# @features setup
# @dimensions oauth browser provider-apis
def print_oauth_instructions():
    """Print instructions for setting up OAuth credentials."""
    from config import SETTINGS

    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
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
    try:
        webbrowser.open_new_tab(clients_url)
    except webbrowser.Error:
        pass

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
    print(wrap_text("2. On the Clients page, click 'Create client'."))
    print(wrap_text("3. Choose 'Web application' and enter:"))
    print(f"   - Name: {app_name}")
    print(f"   - Authorized JavaScript origin: {app_origin}")
    print(f"   - Authorized redirect URI: {SETTINGS.APP['GOOGLE_LOGIN_URI']}")
    print(
        wrap_text(
            "4. Click 'Create', then copy the Client ID and Client secret. "
            "Setup will register both with Identity Platform and will not save "
            "the secret locally.\n"
        )
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_validators_cover_expected_inputs
# @features setup
# @dimensions validation
def validate_oauth_client_id(client_id):
    """Validate OAuth client ID format."""
    return bool(re.match(r"^\d+[-\w]+\.apps\.googleusercontent\.com$", client_id))


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


# @testable false
# @covered-by installer/admin.py::setup_admin_and_oauth
# @reason interactive input wrapper owned by the admin/OAuth setup flow
@validate_input(
    "Enter your OAuth Client ID",
    validation_fn=validate_oauth_client_id,
    error_msg="Invalid OAuth Client ID format",
)
def _get_oauth_client_id(value):
    return value


# @testable false
# @covered-by installer/admin.py::setup_admin_and_oauth
# @reason interactive secret input wrapper owned by the admin/OAuth setup flow
@validate_input("Enter your OAuth Client Secret")
def _get_oauth_client_secret(value):
    return value.strip()


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @features setup
# @dimensions admin oauth settings-save
def setup_admin_and_oauth():
    """Configure the admin and Identity Platform's Google provider."""
    from config import SETTINGS
    from installer.identity import setup_google_provider

    if "ADMIN_NAME" not in SETTINGS.APP:
        SETTINGS.APP["ADMIN_NAME"] = _get_admin_name()
        SETTINGS.APP["ADMIN_EMAIL"] = _get_admin_email()
        SETTINGS.save()

    if "GOOGLE_CLIENT_ID" not in SETTINGS.APP:
        print_oauth_instructions()
        client_id = _get_oauth_client_id()
        client_secret = _get_oauth_client_secret()
        setup_google_provider(client_id, client_secret)
        SETTINGS.APP["GOOGLE_CLIENT_ID"] = client_id
        SETTINGS.save()
    else:
        client_id = SETTINGS.APP["GOOGLE_CLIENT_ID"]
        try:
            setup_google_provider(client_id)
        except ProviderInvalidInput:
            print(
                wrap_text(
                    "Identity Platform still needs the client secret for the "
                    "saved Google OAuth client. It will be sent directly to "
                    "Google and will not be saved locally."
                )
            )
            setup_google_provider(client_id, _get_oauth_client_secret())
