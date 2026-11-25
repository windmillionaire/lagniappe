"""MCP deployment settings and the supported public OAuth clients."""

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

# Accepted only for credentials and clients issued before scope negotiation ended.
LEGACY_SCOPE = "mcp:use"
USER_TOKEN_HEADER = "X-Lagniappe-MCP-Token"
CLIENT_ID = "https://chatgpt.com/oauth/client.json"
REDIRECT_URI = "https://chatgpt.com/connector_platform_oauth_redirect"
ANTIGRAVITY_CLIENT_ID = "https://antigravity.google/oauth/client-metadata.json"
ANTIGRAVITY_REDIRECT_URI = "https://antigravity.google/oauth-callback"
CLAUDE_CLIENT_ID = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
CLAUDE_CODE_CLIENT_ID = "https://claude.ai/oauth/claude-code-client-metadata"
PI_CLIENT_ID = "https://pi.dev/oauth/client.json"
CIMD_CLIENTS: dict[str, str] = {
    CLIENT_ID: REDIRECT_URI,
    ANTIGRAVITY_CLIENT_ID: ANTIGRAVITY_REDIRECT_URI,
    CLAUDE_CLIENT_ID: CLAUDE_REDIRECT_URI,
}
CIMD_LOOPBACK_CLIENTS: dict[str, tuple[str, ...]] = {
    CLAUDE_CODE_CLIENT_ID: ("http://localhost/callback", "http://127.0.0.1/callback"),
    PI_CLIENT_ID: ("http://127.0.0.1/callback", "http://localhost/callback"),
}
CODEX_CLIENT_ID = "lagniappe-codex"
ACCESS_SECONDS = 30 * 60
CODE_SECONDS = 5 * 60
PENDING_SECONDS = 10 * 60
REFRESH_SECONDS = 30 * 24 * 60 * 60
REFRESH_RACE_GRACE_SECONDS = 15
REFRESH_RACE_MAX_MINTS = 8


def mcp_connection_name(value: object = "lagniappe-remote") -> str:
    """Validate the connection alias embedded in user-facing shell commands."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError(
            "MCP connection name must be 1–64 letters, numbers, hyphens or "
            "underscores, starting with a letter or number"
        )
    return value


def https_url(value: object, *, origin: bool = False) -> str:
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


def normalize_mcp_config(settings: Mapping[str, object]) -> dict[str, str | None]:
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


def mcp_issuer(settings: Mapping[str, object]) -> str:
    """Use the application's canonical origin for OAuth and workload identity."""
    domain = settings.get("CUSTOM_DOMAIN")
    issuer = f"https://{domain}" if domain else settings.get("APP_URL")
    return https_url(issuer.rstrip("/") if isinstance(issuer, str) else issuer, origin=True)


def loopback_redirect_base(
    redirect_uri: object, *, allow_localhost: bool = False
) -> str | None:
    """Validate an RFC 8252 loopback callback and return its port-stripped base URI."""
    pattern = (
        r"http://(127\.0\.0\.1|localhost)(?::[1-9][0-9]{0,4})?/callback"
        if allow_localhost
        else r"http://(127\.0\.0\.1)(?::[1-9][0-9]{0,4})?/callback"
    )
    if not isinstance(redirect_uri, str):
        return None
    match = re.fullmatch(pattern, redirect_uri)
    if not match:
        return None
    try:
        if urlsplit(redirect_uri).port == 0:
            return None
    except ValueError:
        return None
    return f"http://{match.group(1)}/callback"


def client_allowed(client_id: object) -> bool:
    return isinstance(client_id, str) and (
        client_id in CIMD_CLIENTS
        or client_id in CIMD_LOOPBACK_CLIENTS
        or client_id == CODEX_CLIENT_ID
    )


def redirect_allowed(client_id: object, redirect_uri: object) -> bool:
    if not client_allowed(client_id):
        return False
    assert isinstance(client_id, str)
    if client_id in CIMD_CLIENTS:
        return redirect_uri == CIMD_CLIENTS[client_id]
    if client_id in CIMD_LOOPBACK_CLIENTS:
        base = loopback_redirect_base(redirect_uri, allow_localhost=True)
        return base is not None and base in CIMD_LOOPBACK_CLIENTS[client_id]
    # RFC 8252 native clients bind an ephemeral port. Every other byte of the
    # pre-registered loopback callback stays exact; localhost/DNS is not used.
    return loopback_redirect_base(redirect_uri, allow_localhost=False) is not None
