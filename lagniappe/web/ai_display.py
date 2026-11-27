"""Request-local AI settings for page fingerprints and rendered controls."""

from flask import g, has_request_context, request
from google.cloud.datastore import Key

from config.remote_mcp import mcp_issuer
from lagniappe import CONFIG
from lagniappe.core.tools.ai.auto_execute import site_auto_execute_enabled
from lagniappe.core.tools.ai.settings import auto_execute_setting
from lagniappe.core.tools.database import site


def home_ai_context_keys() -> tuple[Key, ...]:
    if not CONFIG.AI_ENABLED or request.if_none_match:
        return ()
    g.home_ai_key = site.key("ai")
    return (g.home_ai_key,)


def auto_execute_site_enabled() -> bool:
    if not has_request_context():
        return site_auto_execute_enabled()
    if "_auto_execute_site_enabled" not in g:
        key = g.get("home_ai_key")
        records = g.get("request_context_records")
        if key is not None and records is not None:
            g._auto_execute_site_enabled = auto_execute_setting(records.get(key), CONFIG)
        else:
            g._auto_execute_site_enabled = site_auto_execute_enabled()
    return g._auto_execute_site_enabled


def oauth_connection_available() -> bool:
    if (
        not CONFIG.AI_ENABLED
        or not CONFIG.EXTERNAL_AI_ENABLED
        or not CONFIG.MCP_RESOURCE
        or not CONFIG.MCP_SERVICE_ACCOUNT
        or not has_request_context()
    ):
        return False
    try:
        issuer = mcp_issuer(vars(CONFIG))
    except ValueError:
        return False
    return request.host_url.rstrip("/") == issuer
