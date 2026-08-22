"""Construct the process-global Flask application during module import.

Boot sequence: Sentry (prod only) -> Flask app + CSRF -> initialize_app
(cache, database, AI, entities, jinja, errors, blueprints) -> LoginManager.
The after_request hook adds security headers and
the X-Lagniappe-Invalidate-Cache header that triggers service worker
cache clearing.
"""

from datetime import timedelta
import json
from urllib.parse import urlsplit

from flask import Flask, g, request, session
from flask_wtf.csrf import CSRFProtect

from lagniappe import CONFIG
from lagniappe.core.exceptions.request import filter_sentry_event, sanitize_sentry_event
from lagniappe.core.tools import cache

from .start import initialize_app


SENTRY_LOADED = False

if CONFIG.capture_errors:
    import sentry_sdk
    from sentry_sdk.integrations.google_genai import GoogleGenAIIntegration

    sentry_sdk.init(
        dsn=CONFIG.SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=1.0,
        profile_session_sample_rate=1.0,
        profile_lifecycle="trace",
        before_send=filter_sentry_event,
        before_send_transaction=sanitize_sentry_event,
        integrations=[GoogleGenAIIntegration()],
    )
    SENTRY_LOADED = True


app = Flask(
    __name__, static_url_path="", static_folder="static", template_folder="templates"
)

app.config.update(
    USE_SESSION_FOR_NEXT=True,
    SECRET_KEY=CONFIG.SECRET_KEY,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_DURATION=timedelta(days=30),
    PERMANENT_SESSION_LIFETIME=timedelta(days=1),
)

app.debug = CONFIG.development
app.testing = CONFIG.testing

csrf = CSRFProtect()
csrf.init_app(app)
initialize_app(app, csrf)

GOOGLE_IDENTITY_BASE = "https://accounts.google.com/gsi/"
GOOGLE_IDENTITY_SCRIPT = f"{GOOGLE_IDENTITY_BASE}client"
GOOGLE_IDENTITY_STYLE = f"{GOOGLE_IDENTITY_BASE}style"
SCRIPT_SRC = f"script-src 'self' {GOOGLE_IDENTITY_SCRIPT}"
CONNECT_SRC = f"connect-src 'self' https://*.googleapis.com {GOOGLE_IDENTITY_BASE}"
STORAGE_SRC = "https://storage.googleapis.com"

if SENTRY_LOADED and CONFIG.SENTRY_JS_DSN:
    sentry_dsn = urlsplit(CONFIG.SENTRY_JS_DSN)
    if sentry_dsn.scheme in {"http", "https"} and sentry_dsn.hostname:
        sentry_host = sentry_dsn.hostname
        if ":" in sentry_host:
            sentry_host = f"[{sentry_host}]"
        if sentry_dsn.port:
            sentry_host = f"{sentry_host}:{sentry_dsn.port}"
        CONNECT_SRC += f" {sentry_dsn.scheme}://{sentry_host}"

CSP = "; ".join(
    [
        "default-src 'self'",
        SCRIPT_SRC,
        f"style-src 'self' 'unsafe-inline' {GOOGLE_IDENTITY_STYLE}",
        f"img-src 'self' blob: data: {STORAGE_SRC}",
        f"media-src 'self' {STORAGE_SRC}",
        "font-src 'self'",
        CONNECT_SRC,
        (f"frame-src 'self' https://www.youtube-nocookie.com {GOOGLE_IDENTITY_BASE}"),
        "frame-ancestors 'self'",
        "worker-src 'self' blob:",
        "manifest-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


# @testable false
# @covered-by lagniappe/web/__init__.py::add_lagniappe_headers
# @reason local predicate for the response-header hook
def _client_cache_invalidation_requested():
    invalidate = bool(session.get(CONFIG.LOGIN_INVALIDATE_CACHE_KEY))
    if invalidate and not session.get("_user_id"):
        session.pop(CONFIG.LOGIN_INVALIDATE_CACHE_KEY, None)
    return invalidate


# @testable infrastructure
@app.before_request
def clear_request_notification_state():
    """Start every request without a stale post-commit projection result."""
    cache.clear_recorded_notification_states()
    cache.clear_request_owner_projection()


# @testable false
# @covered-by lagniappe/core/tools/email/notifications/presence.py::record_site_activity
# @reason Flask response-hook wiring delegates to the tested coarse activity service
@app.after_request
def record_authenticated_site_activity(response):
    """Keep a coarse Redis activity hint without adding browser requests."""
    user_key = session.get(CONFIG.LOGIN_USER_KEY) if session.get("_user_id") else None
    if user_key and request.endpoint != "static":
        from lagniappe.core.tools.email.notifications import presence

        presence.record_site_activity(user_key)
    return response


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_authenticated_home_response_headers_include_etag
# @tests tests_e2e/001_site/test_001b_login.py::test_logout_flags_user_cache_invalidation
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_update_category_info_from_tools
# @features web-headers
# @dimensions etag security conditional-request missing-fingerprint entity-revision
@app.after_request
def add_lagniappe_headers(response):
    """Add security headers, ETag fingerprinting, and cache invalidation flag."""
    headers = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cache-Control": "no-store" if g.get("NO_CACHE") else "private, no-cache",
        "Content-Security-Policy": CSP,
    }

    if getattr(g, "fingerprint", False):
        headers["ETag"] = f'"{g.fingerprint}"'

    entity_revisions = list(getattr(g, "ENTITY_RESPONSE_REVISIONS", {}).values())
    if entity_revisions:
        headers["X-Lagniappe-Entity-Revisions"] = json.dumps(
            entity_revisions, separators=(",", ":")
        )

    notification_state = getattr(g, "NOTIFICATION_STATE", None)
    if notification_state is None:
        user_key = session.get(CONFIG.LOGIN_USER_KEY)
        if user_key:
            notification_state = cache.take_recorded_notification_state(user_key)
    if notification_state is not None:
        headers["X-Lagniappe-Notification-State"] = json.dumps(
            notification_state,
            separators=(",", ":"),
        )

    if _client_cache_invalidation_requested():
        headers["X-Lagniappe-Invalidate-Cache"] = True

    if getattr(CONFIG, "DEBUG_TRACING", False):
        from lagniappe.core.exceptions.entity_load import print_entity_load_trace

        print_entity_load_trace(response)

    response.headers.update(headers)
    return response
