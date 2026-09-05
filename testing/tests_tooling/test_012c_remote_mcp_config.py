"""Remote pilot configuration has one explicit, closed trust boundary."""

import pytest

from config.remote_mcp import CLIENT_ID, REDIRECT_URI, normalize_remote_mcp_config


# @matrix mcp-oauth : configuration validation
@pytest.mark.tooling
def test_remote_mcp_configuration_is_opt_in_and_exact():
    assert normalize_remote_mcp_config(None) == {"enabled": False}
    valid = {
        "enabled": True,
        "issuer": "https://lagniappe.test",
        "resource": "https://pilot.run.app/mcp",
        "actors": ["Pilot@Example.com"],
        "service_account": "lagniappe-mcp@pilot-project.iam.gserviceaccount.com",
    }
    result = normalize_remote_mcp_config(valid)
    assert result["actors"] == ("pilot@example.com",)
    assert result["client_id"] == CLIENT_ID
    assert result["redirect_uri"] == REDIRECT_URI
    # Discovery may be deployed before selecting the pilot user; nobody may
    # authorize while the explicit actor allowlist is empty.
    assert normalize_remote_mcp_config({**valid, "actors": []})["actors"] == ()
    for field, value in (
        ("enabled", "true"),
        ("codex_enabled", "true"),
        ("issuer", "http://lagniappe.test"),
        ("issuer", "https://lagniappe.test/"),
        ("issuer", "https://lagniappe.test?"),
        ("issuer", "https://user@lagniappe.test"),
        ("issuer", "https://LAGNIAPPE.test"),
        ("issuer", "https://lagniappe.test:443"),
        ("resource", "https://lagniappe.test/mcp"),
        ("resource", "https://pilot.run.app/mcp/"),
        ("resource", "https://pilot.run.app/mcp#"),
        ("client_id", "https://attacker.test/oauth/client.json"),
        ("client_id", "https://chatgpt.com/arbitrary"),
        ("redirect_uri", "https://attacker.test/callback"),
        ("actors", None),
        ("actors", ["A@example.com", "a@example.com"]),
        ("actors", ["bad"]),
        ("service_account", "human@example.com"),
    ):
        with pytest.raises(ValueError):
            normalize_remote_mcp_config({**valid, field: value})
    with pytest.raises(ValueError):
        normalize_remote_mcp_config({**valid, "client_secret": "forbidden"})


# @matrix mcp-oauth : configuration validation loopback
@pytest.mark.tooling
def test_codex_client_requires_opt_in_and_exact_loopback_callback():
    from config.remote_mcp import CODEX_CLIENT_ID, client_allowed, redirect_allowed

    config = {"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI}
    assert client_allowed(config, CLIENT_ID)
    assert redirect_allowed(config, CLIENT_ID, REDIRECT_URI)
    assert not client_allowed(config, CODEX_CLIENT_ID)
    assert not redirect_allowed(config, CODEX_CLIENT_ID, "http://127.0.0.1:54321/callback")
    config["codex_enabled"] = True
    for target in ("http://127.0.0.1/callback", "http://127.0.0.1:54321/callback"):
        assert redirect_allowed(config, CODEX_CLIENT_ID, target)
        assert not redirect_allowed(config, CLIENT_ID, target)
    for target in (
        "http://localhost:54321/callback", "http://127.0.0.2:54321/callback",
        "http://127.0.0.1:0/callback", "http://127.0.0.1:65536/callback",
        "http://127.0.0.1:00080/callback", "http://127.0.0.1:54321/callback/",
        "http://127.0.0.1:54321/callback?", "http://127.0.0.1:54321/callback#",
        "http://127.0.0.1:54321/callback/other", "http://user@127.0.0.1:54321/callback",
        "http://127.0.0.1.attacker.test/callback", "https://127.0.0.1/callback",
        "http://127.0.0.1:54321/callback\\evil", None,
    ):
        assert not redirect_allowed(config, CODEX_CLIENT_ID, target)
    assert not client_allowed(config, "unregistered")
