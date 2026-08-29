"""Google Identity Platform token and account operations."""

import re

from urllib.parse import quote, urlencode

import requests as http_requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

IDENTITY_TOOLKIT_API = "https://identitytoolkit.googleapis.com/v1"
IDENTITY_TOOLKIT_ADMIN_API = "https://identitytoolkit.googleapis.com/admin/v2"
IDENTITY_REQUEST_TIMEOUT = 10


# @testable false
# @covered-by lagniappe/core/tools/services/identity_platform.py::exchange_google_credential
# @covered-by lagniappe/core/tools/services/identity_platform.py::google_provider_enabled
# @covered-by lagniappe/core/tools/services/identity_platform.py::generate_email_action_code
# @covered-by lagniappe/core/tools/services/identity_platform.py::delete_account_by_email
# @reason typed provider exception is exercised by the public request operations
class IdentityPlatformError(RuntimeError):
    """Raised when Identity Platform rejects or cannot complete an operation."""

    def __init__(self, message, *, provider_code=None):
        super().__init__(message)
        self.provider_code = str(provider_code or "").strip() or None


# @testable false
# @covered-by lagniappe/core/tools/services/identity_platform.py::exchange_google_credential
# @reason provider error normalization is exercised through credential exchange
def _provider_error_code(value):
    """Extract a stable provider code without retaining diagnostic prose."""
    match = re.match(r"^([A-Z][A-Z0-9_]+)(?:\b|\s|:)", str(value or "").strip())
    return match.group(1) if match else None


# @testable false
# @covered-by lagniappe/core/tools/services/identity_platform.py::exchange_google_credential
# @covered-by lagniappe/core/tools/services/identity_platform.py::google_provider_enabled
# @covered-by lagniappe/core/tools/services/identity_platform.py::generate_email_action_code
# @covered-by lagniappe/core/tools/services/identity_platform.py::delete_account_by_email
# @reason response normalization is exercised through public provider operations
def _response_json(response, operation):
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.ok:
        return data
    provider_error = data.get("error") if isinstance(data, dict) else {}
    provider_error = provider_error if isinstance(provider_error, dict) else {}
    provider_message = str(provider_error.get("message") or "").strip()
    provider_code = _provider_error_code(provider_message) or _provider_error_code(
        provider_error.get("status")
    )
    detail = provider_message or f"HTTP {response.status_code}"
    raise IdentityPlatformError(
        f"{operation} failed: {detail}",
        provider_code=provider_code,
    )


# @testable false
# @covered-by lagniappe/core/tools/services/identity_platform.py::exchange_google_credential
# @reason client config validation is owned by the public credential exchange
def _client_config(config):
    api_key = str((config or {}).get("apiKey") or "").strip()
    project_id = str((config or {}).get("projectId") or "").strip()
    if not api_key or not project_id:
        raise IdentityPlatformError(
            "Identity Platform client configuration is incomplete."
        )
    return api_key, project_id


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_verify_identity_token_enforces_project_issuer_and_subject
# @matrix login : audience identity-platform issuer token-verification
def verify_identity_token(token, project_id, request_adapter=None):
    """Verify a Secure Token ID token for exactly one Identity Platform project."""
    project_id = str(project_id or "").strip()
    if not token or not project_id:
        raise ValueError("Identity token and project ID are required.")
    claims = id_token.verify_firebase_token(
        token,
        request_adapter or google_requests.Request(),
        audience=project_id,
    )
    expected_issuer = f"https://securetoken.google.com/{project_id}"
    if claims.get("iss") != expected_issuer:
        raise ValueError("Identity token issuer is invalid.")
    if claims.get("aud") != project_id:
        raise ValueError("Identity token audience is invalid.")
    if not str(claims.get("sub") or "").strip():
        raise ValueError("Identity token subject is missing.")
    return claims


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_verify_google_credential_enforces_client_and_verified_email
# @matrix login : audience email-verification google-oauth token-verification
def verify_google_credential(credential, client_id, request_adapter=None):
    """Verify a Google Identity Services credential before account exchange."""
    client_id = str(client_id or "").strip()
    if not credential or not client_id:
        raise ValueError("Google credential and client ID are required.")
    claims = id_token.verify_oauth2_token(
        credential,
        request_adapter or google_requests.Request(),
        audience=client_id,
    )
    if not str(claims.get("sub") or "").strip():
        raise ValueError("Google credential subject is missing.")
    if not str(claims.get("email") or "").strip():
        raise ValueError("Google credential email is missing.")
    if claims.get("email_verified") is not True:
        raise ValueError("Google credential email is not verified.")
    return claims


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_exchange_google_credential_uses_identity_platform_idp_endpoint
# @matrix login : google-oauth identity-platform provider-error-code token-exchange
def exchange_google_credential(
    credential,
    client_config,
    request_uri,
    session=None,
):
    """Exchange a popup-free GIS credential for an Identity Platform ID token."""
    api_key, _ = _client_config(client_config)
    if not credential:
        raise IdentityPlatformError("Google credential is required.")
    request_uri = str(request_uri or "").strip()
    if not request_uri.startswith("https://"):
        raise IdentityPlatformError(
            "Google credential exchange requires an HTTPS request URI."
        )

    session = session or http_requests.Session()
    url = f"{IDENTITY_TOOLKIT_API}/accounts:signInWithIdp?key={api_key}"
    response = session.post(
        url,
        json={
            "requestUri": request_uri,
            "postBody": urlencode(
                {
                    "id_token": credential,
                    "providerId": "google.com",
                }
            ),
            "returnSecureToken": True,
            "returnIdpCredential": True,
        },
        timeout=IDENTITY_REQUEST_TIMEOUT,
    )
    data = _response_json(response, "Google identity exchange")
    provider_code = _provider_error_code(data.get("errorMessage"))
    if provider_code:
        raise IdentityPlatformError(
            f"Google identity exchange was rejected: {provider_code}",
            provider_code=provider_code,
        )
    if data.get("needConfirmation"):
        raise IdentityPlatformError(
            "This Google email is already attached to another sign-in method."
        )
    if not data.get("idToken"):
        raise IdentityPlatformError(
            "Google identity exchange returned no Identity Platform token."
        )
    return data


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_google_provider_enabled_reads_live_provider_state
# @matrix login : google-oauth identity-platform provider-state
def google_provider_enabled(
    *,
    project_id=None,
    access_token=None,
    session=None,
):
    """Return whether the project's live Google sign-in provider is enabled."""
    config = None
    if not project_id or not access_token:
        from lagniappe import CONFIG

        config = CONFIG
    project_id = str(project_id or config.GOOGLE_CLOUD_PROJECT or "").strip()
    if not project_id:
        raise IdentityPlatformError(
            "Google provider status requires an Identity Platform project ID."
        )
    access_token = access_token or config.google_access_token()
    session = session or http_requests.Session()
    try:
        response = session.get(
            (
                f"{IDENTITY_TOOLKIT_ADMIN_API}/projects/"
                f"{quote(project_id, safe='')}/defaultSupportedIdpConfigs/google.com"
            ),
            headers=_admin_headers(access_token),
            timeout=IDENTITY_REQUEST_TIMEOUT,
        )
    except http_requests.RequestException as error:
        raise IdentityPlatformError("Google provider status lookup failed.") from error
    if response.status_code == 404:
        return False
    data = _response_json(response, "Google provider status lookup")
    # This API uses protobuf JSON encoding, which omits scalar fields at their
    # default value. An enabled provider returns ``enabled: true``; a disabled
    # provider can therefore omit ``enabled`` entirely.
    return isinstance(data, dict) and data.get("enabled") is True


# @testable false
# @covered-by lagniappe/core/tools/services/identity_platform.py::google_provider_enabled
# @covered-by lagniappe/core/tools/services/identity_platform.py::generate_email_action_code
# @covered-by lagniappe/core/tools/services/identity_platform.py::delete_account_by_email
# @reason bearer-header construction is exercised through public admin operations
def _admin_headers(access_token):
    access_token = str(access_token or "").strip()
    if not access_token:
        raise IdentityPlatformError(
            "Identity Platform administration requires a Google access token."
        )
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_generate_email_action_code_returns_provider_code_without_sending
# @matrix login : action-codes authentication-email identity-platform
def generate_email_action_code(
    request_type,
    email,
    *,
    user_ip=None,
    project_id=None,
    access_token=None,
    session=None,
):
    """Generate an Identity Platform OOB code without provider email delivery."""
    request_type = str(request_type or "").strip()
    if request_type not in {"PASSWORD_RESET", "VERIFY_EMAIL"}:
        raise IdentityPlatformError("Unsupported Identity Platform email action.")
    email = str(email or "").strip().lower()
    if not email:
        raise IdentityPlatformError("Identity Platform email action requires an email.")

    config = None
    if not project_id or not access_token:
        from lagniappe import CONFIG

        config = CONFIG
    project_id = str(project_id or config.GOOGLE_CLOUD_PROJECT or "").strip()
    if not project_id:
        raise IdentityPlatformError(
            "Identity Platform email action requires a project ID."
        )
    access_token = access_token or config.google_access_token()
    payload = {
        "requestType": request_type,
        "email": email,
        "returnOobLink": True,
    }
    if request_type == "PASSWORD_RESET":
        user_ip = str(user_ip or "").strip()
        if not user_ip:
            raise IdentityPlatformError(
                "Password-reset action generation requires the caller IP."
            )
        payload["userIp"] = user_ip

    session = session or http_requests.Session()
    data = _response_json(
        session.post(
            (
                f"{IDENTITY_TOOLKIT_API}/projects/"
                f"{quote(project_id, safe='')}/accounts:sendOobCode"
            ),
            headers=_admin_headers(access_token),
            json=payload,
            timeout=IDENTITY_REQUEST_TIMEOUT,
        ),
        "Identity email action generation",
    )
    oob_code = str(data.get("oobCode") or "").strip()
    if not oob_code:
        raise IdentityPlatformError(
            "Identity email action generation returned no action code."
        )
    return oob_code


# @testable true
# @tests tests_unit/test_025_identity_platform.py::test_delete_account_by_email_looks_up_and_deletes_identity_user
# @matrix users : account-delete identity-platform
def delete_account_by_email(
    email,
    *,
    project_id=None,
    access_token=None,
    session=None,
):
    """Delete the Identity Platform account for an email, if one exists."""
    email = str(email or "").strip().lower()
    if not email:
        return False
    config = None
    if not project_id or not access_token:
        from lagniappe import CONFIG

        config = CONFIG
    project_id = str(project_id or config.GOOGLE_CLOUD_PROJECT or "").strip()
    if not project_id:
        raise IdentityPlatformError(
            "Identity Platform account deletion requires a project ID."
        )
    access_token = access_token or config.google_access_token()
    headers = _admin_headers(access_token)
    session = session or http_requests.Session()
    lookup_url = f"{IDENTITY_TOOLKIT_API}/projects/{project_id}/accounts:lookup"
    lookup = _response_json(
        session.post(
            lookup_url,
            headers=headers,
            json={"email": [email]},
            timeout=IDENTITY_REQUEST_TIMEOUT,
        ),
        "Identity account lookup",
    )
    users = lookup.get("users") or ()
    matching = next(
        (
            user
            for user in users
            if str(user.get("email") or "").strip().lower() == email
        ),
        None,
    )
    if matching is None:
        return False
    local_id = str(matching.get("localId") or "").strip()
    if not local_id:
        raise IdentityPlatformError(
            "Identity account lookup returned no local user ID."
        )

    delete_url = f"{IDENTITY_TOOLKIT_API}/projects/{project_id}/accounts:delete"
    _response_json(
        session.post(
            delete_url,
            headers=headers,
            json={"localId": local_id},
            timeout=IDENTITY_REQUEST_TIMEOUT,
        ),
        "Identity account deletion",
    )
    return True
