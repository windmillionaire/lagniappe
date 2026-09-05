"""Opt-in configuration for the ChatGPT and Codex remote MCP pilot."""

import re
from urllib.parse import urlsplit


SCOPE = "mcp:use"
USER_TOKEN_HEADER = "X-Lagniappe-MCP-Token"
CLIENT_ID = "https://chatgpt.com/oauth/client.json"
REDIRECT_URI = "https://chatgpt.com/connector_platform_oauth_redirect"
CODEX_CLIENT_ID = "lagniappe-codex"
ACCESS_SECONDS = 30 * 60
CODE_SECONDS = 5 * 60
PENDING_SECONDS = 10 * 60
REFRESH_SECONDS = 30 * 24 * 60 * 60


# @testable false
# @covered-by config/remote_mcp.py::normalize_remote_mcp_config
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
def normalize_remote_mcp_config(value):
    if value is None:
        return {"enabled": False}
    allowed = {
        "enabled",
        "issuer",
        "resource",
        "client_id",
        "redirect_uri",
        "actors",
        "service_account",
        "codex_enabled",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Unknown remote MCP configuration field")
    if type(value.get("enabled", False)) is not bool:
        raise ValueError("Remote MCP enabled must be a boolean")
    if type(value.get("codex_enabled", False)) is not bool:
        raise ValueError("Remote MCP codex_enabled must be a boolean")
    if not value.get("enabled", False):
        return {**value, "enabled": False}
    issuer = https_url(value.get("issuer"), origin=True)
    resource = https_url(value.get("resource"))
    if urlsplit(resource).path != "/mcp" or resource == issuer + "/mcp":
        raise ValueError("Remote MCP requires one separate-origin /mcp resource")
    client_id = https_url(value.get("client_id", CLIENT_ID))
    if urlsplit(client_id).hostname != "chatgpt.com" or not re.fullmatch(
        r"/oauth/(?:[A-Za-z0-9_-]+/)?client\.json", urlsplit(client_id).path
    ):
        raise ValueError("Remote MCP accepts one ChatGPT CIMD URL")
    redirect_uri = https_url(value.get("redirect_uri", REDIRECT_URI))
    if urlsplit(redirect_uri).hostname != "chatgpt.com":
        raise ValueError("Remote MCP redirect must belong to ChatGPT")
    actors = value.get("actors")
    if not isinstance(actors, (list, tuple)) or len(actors) > 10:
        raise ValueError("Remote MCP requires an explicit pilot actor list")
    if any(
        not isinstance(actor, str)
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", actor)
        for actor in actors
    ):
        raise ValueError("Invalid remote MCP pilot actor")
    actors = tuple(actor.casefold() for actor in actors)
    if len(set(actors)) != len(actors):
        raise ValueError("Duplicate remote MCP pilot actor")
    service_account = value.get("service_account")
    if not isinstance(service_account, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com",
        service_account,
    ):
        raise ValueError("Remote MCP requires its exact runtime service account")
    return {
        "enabled": True,
        "issuer": issuer,
        "resource": resource,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "actors": actors,
        "service_account": service_account,
        "codex_enabled": value.get("codex_enabled", False),
    }


# @testable true
# @tests tests_tooling/test_012c_remote_mcp_config.py::test_codex_client_requires_opt_in_and_exact_loopback_callback
# @matrix mcp-oauth : configuration validation loopback
def client_allowed(config, client_id):
    return client_id == config["client_id"] or (
        config.get("codex_enabled") is True and client_id == CODEX_CLIENT_ID
    )


# @testable true
# @tests tests_tooling/test_012c_remote_mcp_config.py::test_codex_client_requires_opt_in_and_exact_loopback_callback
# @matrix mcp-oauth : configuration validation loopback
def redirect_allowed(config, client_id, redirect_uri):
    if not client_allowed(config, client_id):
        return False
    if client_id == config["client_id"]:
        return redirect_uri == config["redirect_uri"]
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
