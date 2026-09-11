"""MCP deployment settings and the supported public OAuth clients."""

import re
from urllib.parse import urlsplit


# Accepted only for credentials and clients issued before scope negotiation ended.
LEGACY_SCOPE = "mcp:use"
USER_TOKEN_HEADER = "X-Lagniappe-MCP-Token"
CLIENT_ID = "https://chatgpt.com/oauth/client.json"
REDIRECT_URI = "https://chatgpt.com/connector_platform_oauth_redirect"
CODEX_CLIENT_ID = "lagniappe-codex"
ACCESS_SECONDS = 30 * 60
CODE_SECONDS = 5 * 60
PENDING_SECONDS = 10 * 60
REFRESH_SECONDS = 30 * 24 * 60 * 60


# @testable true
# @tests tests_tooling/test_012c_remote_mcp_config.py::test_mcp_connection_name_is_safe_for_copyable_commands
# @matrix mcp-oauth : configuration validation
def mcp_connection_name(value="lagniappe-remote"):
    """Validate the connection alias embedded in user-facing shell commands."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError(
            "MCP connection name must be 1–64 letters, numbers, hyphens or "
            "underscores, starting with a letter or number"
        )
    return value


# @testable false
# @covered-by config/remote_mcp.py::normalize_mcp_config
def https_url(value, *, origin=False):
    """Require an exact, canonical HTTPS URL rather than normalizing identity."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Remote MCP requires an absolute HTTPS URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.netloc != parsed.hostname
        or parsed.hostname.endswith(".")
        or "." not in parsed.hostname
        or not re.fullmatch(r"[a-z0-9.-]+", parsed.hostname)
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        or "\\" in value
        or (origin and parsed.path)
    ):
        raise ValueError(
            "Remote MCP URL must be canonical HTTPS without credentials or query"
        )
    return value


# @testable true
# @tests tests_tooling/test_012c_remote_mcp_config.py::test_remote_mcp_configuration_is_opt_in_and_exact
# @matrix mcp-oauth : configuration validation
def normalize_mcp_config(settings):
    """Validate the installed endpoint and identity, including while AI is off."""
    name = mcp_connection_name(settings.get("MCP_NAME", "lagniappe-remote"))
    resource = settings.get("MCP_RESOURCE")
    service_account = settings.get("MCP_SERVICE_ACCOUNT")
    if resource is None and service_account is None:
        return {"MCP_NAME": name, "MCP_RESOURCE": None, "MCP_SERVICE_ACCOUNT": None}
    issuer = mcp_issuer(settings)
    resource = https_url(resource)
    if urlsplit(resource).path != "/mcp" or resource == issuer + "/mcp":
        raise ValueError("Remote MCP requires one separate-origin /mcp resource")
    if not isinstance(service_account, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com",
        service_account,
    ):
        raise ValueError("Remote MCP requires its exact runtime service account")
    return {"MCP_NAME": name, "MCP_RESOURCE": resource, "MCP_SERVICE_ACCOUNT": service_account}


# @testable true
# @tests tests_tooling/test_012c_remote_mcp_config.py::test_remote_mcp_configuration_is_opt_in_and_exact
# @matrix mcp-oauth : configuration validation
def mcp_issuer(settings):
    """Use the application's canonical origin for OAuth and workload identity."""
    domain = settings.get("CUSTOM_DOMAIN")
    issuer = f"https://{domain}" if domain else settings.get("APP_URL")
    return https_url(issuer.rstrip("/") if isinstance(issuer, str) else issuer, origin=True)


# @testable true
# @tests tests_tooling/test_012c_remote_mcp_config.py::test_supported_clients_require_exact_callbacks
# @matrix mcp-oauth : configuration validation loopback
def client_allowed(client_id):
    return client_id in (CLIENT_ID, CODEX_CLIENT_ID)


# @testable true
# @tests tests_tooling/test_012c_remote_mcp_config.py::test_supported_clients_require_exact_callbacks
# @matrix mcp-oauth : configuration validation loopback
def redirect_allowed(client_id, redirect_uri):
    if not client_allowed(client_id):
        return False
    if client_id == CLIENT_ID:
        return redirect_uri == REDIRECT_URI
    # RFC 8252 native clients bind an ephemeral port. Every other byte of the
    # pre-registered loopback callback stays exact; localhost/DNS is not used.
    if not isinstance(redirect_uri, str) or not re.fullmatch(
        r"http://127\.0\.0\.1(?::[1-9][0-9]{0,4})?/callback", redirect_uri
    ):
        return False
    try:
        return urlsplit(redirect_uri).port != 0
    except ValueError:
        return False
