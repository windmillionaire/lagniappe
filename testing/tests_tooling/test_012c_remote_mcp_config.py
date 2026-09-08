"""MCP deployment settings and supported OAuth client boundaries."""

import pytest

from config.remote_mcp import CLIENT_ID, REDIRECT_URI, mcp_issuer, normalize_mcp_config


# @matrix mcp-oauth : configuration validation
@pytest.mark.tooling
def test_remote_mcp_configuration_is_opt_in_and_exact():
    assert normalize_mcp_config({}) == {
        "MCP_RESOURCE": None, "MCP_SERVICE_ACCOUNT": None,
    }
    valid = {
        "APP_URL": "https://lagniappe.test",
        "MCP_RESOURCE": "https://pilot.run.app/mcp",
        "MCP_SERVICE_ACCOUNT": "lagniappe-mcp@pilot-project.iam.gserviceaccount.com",
    }
    assert normalize_mcp_config(valid) == {
        key: valid[key] for key in ("MCP_RESOURCE", "MCP_SERVICE_ACCOUNT")
    }
    assert mcp_issuer(valid) == "https://lagniappe.test"
    assert mcp_issuer({**valid, "APP_URL": "https://lagniappe.test/"}) == "https://lagniappe.test"
    assert mcp_issuer({**valid, "CUSTOM_DOMAIN": "workspace.example.test"}) == "https://workspace.example.test"
    # Policy changes retain the same endpoint and workload identity for re-enable.
    assert normalize_mcp_config({**valid, "EXTERNAL_AI_ENABLED": False}) == normalize_mcp_config(valid)
    for field, value in (
        ("APP_URL", None),
        ("APP_URL", "http://lagniappe.test"),
        ("APP_URL", "https://lagniappe.test/path"),
        ("APP_URL", "https://lagniappe.test?"),
        ("APP_URL", "https://user@lagniappe.test"),
        ("APP_URL", "https://LAGNIAPPE.test"),
        ("APP_URL", "https://lagniappe.test:443"),
        ("CUSTOM_DOMAIN", "user@workspace.example.test"),
        ("MCP_RESOURCE", None),
        ("MCP_RESOURCE", "https://lagniappe.test/mcp"),
        ("MCP_RESOURCE", "https://pilot.run.app/mcp/"),
        ("MCP_RESOURCE", "https://pilot.run.app/mcp#"),
        ("MCP_SERVICE_ACCOUNT", None),
        ("MCP_SERVICE_ACCOUNT", "human@example.com"),
    ):
        with pytest.raises(ValueError):
            normalize_mcp_config({**valid, field: value})
    with pytest.raises(ValueError):
        normalize_mcp_config({**valid, "CUSTOM_DOMAIN": "pilot.run.app"})


# @matrix mcp-oauth : configuration validation loopback
@pytest.mark.tooling
def test_supported_clients_require_exact_callbacks():
    from config.remote_mcp import CODEX_CLIENT_ID, client_allowed, redirect_allowed

    assert client_allowed(CLIENT_ID)
    assert redirect_allowed(CLIENT_ID, REDIRECT_URI)
    assert client_allowed(CODEX_CLIENT_ID)
    assert not redirect_allowed(CODEX_CLIENT_ID, REDIRECT_URI)
    assert not redirect_allowed(CLIENT_ID, REDIRECT_URI + "/")
    assert not redirect_allowed("unregistered", REDIRECT_URI)
    for target in ("http://127.0.0.1/callback", "http://127.0.0.1:54321/callback"):
        assert redirect_allowed(CODEX_CLIENT_ID, target)
        assert not redirect_allowed(CLIENT_ID, target)
    for target in (
        "http://localhost:54321/callback", "http://127.0.0.2:54321/callback",
        "http://127.0.0.1:0/callback", "http://127.0.0.1:65536/callback",
        "http://127.0.0.1:00080/callback", "http://127.0.0.1:54321/callback/",
        "http://127.0.0.1:54321/callback?", "http://127.0.0.1:54321/callback#",
        "http://127.0.0.1:54321/callback/other", "http://user@127.0.0.1:54321/callback",
        "http://127.0.0.1.attacker.test/callback", "https://127.0.0.1/callback",
        "http://127.0.0.1:54321/callback\\evil", None,
    ):
        assert not redirect_allowed(CODEX_CLIENT_ID, target)
    assert not client_allowed("unregistered")
