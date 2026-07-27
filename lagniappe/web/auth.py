"""Route authorization decorators.

Every decorator follows a common pattern:
1. Check authentication (401 if not logged in)
2. Load the entity from the URL key (404 if missing)
3. Set g.fingerprint for ETag caching on GET requests (304 if unchanged)
4. Check permission (403 if denied)
5. Pass the loaded entity to the route via ``entity=`` kwarg
"""

import hashlib
from functools import wraps

from flask import abort, current_app, g, request, session
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database

LOGIN_USER_KEY = CONFIG.LOGIN_USER_KEY
LOGIN_USER_PAGE_KEY = CONFIG.LOGIN_USER_PAGE_KEY
LOGIN_MESSAGING_DISABLED_KEY = CONFIG.LOGIN_MESSAGING_DISABLED_KEY
LOGIN_INVALIDATE_CACHE_KEY = CONFIG.LOGIN_INVALIDATE_CACHE_KEY
AUTH_SESSION_CACHE_KEYS = CONFIG.AUTH_SESSION_CACHE_KEYS


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_google_signin_enforces_double_submit_csrf_before_provider_auth
# @pair login:google-signin
# @pair csrf:double-submit
# @pair csrf:missing-cookie
# @pair csrf:missing-body
# @pair csrf:mismatch
# @pair csrf:match
def verify_google_csrf(response):
    """Verify Google's double-submit CSRF token (cookie vs. body)."""
    csrf_token_cookie = response.cookies.get("g_csrf_token")
    if not csrf_token_cookie:
        abort(400, "Google: No CSRF token in Cookie.")

    csrf_token_body = response.form.get("g_csrf_token")
    if not csrf_token_body:
        csrf_token_body = response.get_json(silent=True)
        if csrf_token_body:
            csrf_token_body = csrf_token_body.get("g_csrf_token")

    if not csrf_token_body:
        abort(400, "Google: No CSRF token in post body.")

    if csrf_token_cookie != csrf_token_body:
        abort(400, "Google: Failed to verify double submit cookie.")


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_authenticated_home_response_headers_include_etag
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_task_route_is_forbidden_without_model_or_page_permission
# @pairs cache:etag cache:permissions cache:build-id
def _etag_fingerprint(base_fingerprint, user):
    """Hash the resource fingerprint, build id, and viewer permissions."""
    value = f"{base_fingerprint}-{CONFIG.BUILD_ID}-{user.permissions_fingerprint}"
    return hashlib.md5(value.encode("utf-8")).hexdigest()


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_authenticated_home_response_headers_include_etag
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_download_uses_original_filename_and_mimetype
# @pairs cache:etag cache:standard-header cache:missing-fingerprint cache:byte-range
def _fingerprint_matches_etag():
    """Check if the client's If-None-Match header matches the current fingerprint."""
    if not getattr(g, "fingerprint", None):
        return False
    if request.headers.get("Range"):
        return False

    cached = request.headers.get("If-None-Match")
    if cached:
        expected_value = str(g.fingerprint)
        for candidate in cached.split(","):
            cached_value = candidate.strip().removeprefix("W/").strip('"')
            if cached_value == expected_value:
                return True

    return False


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_stale_preloaded_session_keys_fall_back_to_flask_login_user
# @tests tests_e2e/001_site/test_001b_login.py::test_logout_clears_session_and_returns_login
# @features login
# @dimensions session-keys clear
def clear_login_session():
    """Clear request-auth helper keys and derived permission caches."""
    for key in AUTH_SESSION_CACHE_KEYS:
        session.pop(key, None)


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_switching_session_user_requests_client_cache_invalidation
# @tests tests_e2e/001_site/test_001b_login.py::test_logout_flags_user_cache_invalidation
# @features auth
# @dimensions session-keys invalidation
def request_client_cache_invalidation(user=None, persist_user=False):
    """Mark this session response as requiring a client response-cache clear."""
    session[LOGIN_INVALIDATE_CACHE_KEY] = True
    if user is not None and persist_user:
        user.invalidate_cache = True
        user.save()


# @testable false
# @covered-by lagniappe/web/routes/home/site.py::validate_user
# @reason session flag cleanup is part of the validated client-cache acknowledgement route
def clear_client_cache_invalidation():
    """Clear the session flag once the client confirms its cache was wiped."""
    session.pop(LOGIN_INVALIDATE_CACHE_KEY, None)


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_switching_session_user_requests_client_cache_invalidation
# @features auth
# @dimensions session-user switch
def login_cache_invalidation_required(user):
    """Return True when login is switching an existing session to another user."""
    session_user_key = session.get(LOGIN_USER_KEY)
    if session_user_key:
        return session_user_key != user.urlsafe_key

    session_user_id = session.get("_user_id")
    if session_user_id:
        return session_user_id != user.get_id()

    return False


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_switching_session_user_requests_client_cache_invalidation
# @tests tests_e2e/001_site/test_001b_login.py::test_stale_preloaded_session_keys_fall_back_to_flask_login_user
# @tests tests_e2e/001_site/test_001c_messaging.py::test_public_user_suppresses_messaging_permission
# @features auth
# @dimensions session-keys user-key page-key messaging-disabled invalidation
def seed_login_session(user, messaging_disabled=False, invalidate_cache=False):
    """Store direct entity keys for faster auth loads on later requests."""
    clear_login_session()

    if not getattr(user, "is_authenticated", False):
        return

    session[LOGIN_USER_KEY] = user.urlsafe_key
    session[LOGIN_USER_PAGE_KEY] = user.page.urlsafe_key
    if invalidate_cache or getattr(user, "invalidate_cache", False):
        request_client_cache_invalidation()

    agent_email = str(getattr(CONFIG, "AGENT_ACCESS_EMAIL", "") or "").strip().lower()
    user_email = str(getattr(user, "email", "") or "").strip().lower()
    if (
        messaging_disabled
        or getattr(user, "is_public", False)
        or (agent_email and user_email == agent_email)
    ):
        session[LOGIN_MESSAGING_DISABLED_KEY] = True


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_file_and_photo_actions_are_forbidden
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_restricted_schedules_are_forbidden
# @features public-users
# @dimensions restriction-gate
def abort_public_user_action():
    """Reject actions that public users may not invoke despite edit access."""
    if getattr(current_user, "is_public", False):
        abort(403)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_ai_actions_are_forbidden
# @features public-users
# @dimensions metered-actions restriction-gate
def abort_ai_restricted_action():
    """Reject AI-backed actions for users that may edit but may not invoke AI."""
    restrictions = getattr(
        getattr(current_user, "properties", None),
        "restrictions",
        None,
    )
    if not restrictions or not restrictions.can_use_ai_tools:
        abort(403)


# @testable false
# @covered-by lagniappe/web/auth.py::_load_session_user_context
# @reason small Flask-Login adapter used by the session preload path
def _session_protection_failed():
    login_manager = getattr(current_app, "login_manager", None)
    if not login_manager:
        return False

    failed = login_manager._session_protection_failed()
    if failed:
        login_manager._update_request_context_with_user()
    return failed


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_stale_preloaded_session_keys_fall_back_to_flask_login_user
# @features auth
# @dimensions session-preload stale-session flask-login-skip batch-load session-keys clear user-key page-key
def _load_session_user_context(entity_identifier=None):
    if not session.get("_user_id"):
        clear_login_session()
        return None, None

    if _session_protection_failed():
        clear_login_session()
        return None, None

    user_identifier = session.get(LOGIN_USER_KEY)
    user_page_identifier = session.get(LOGIN_USER_PAGE_KEY)
    if not user_identifier or not user_page_identifier:
        return None, None

    loaded = Entities.fetch(
        user_identifier,
        user_page_identifier,
        entity_identifier,
        request=Fetch.direct(),
    )
    user = next(
        (
            entity
            for entity in loaded
            if isinstance(entity, Entities.USER)
            and entity.urlsafe_key == user_identifier
        ),
        None,
    )
    entity = next(
        (
            entity
            for entity in loaded
            if entity_identifier and entity.urlsafe_key == entity_identifier
        ),
        None,
    )
    if not isinstance(user, Entities.USER) or user.get_id() != session.get("_user_id"):
        clear_login_session()
        return None, None

    g._login_user = user
    if user.invalidate_cache:
        request_client_cache_invalidation()
    return current_user, entity


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_stale_preloaded_session_keys_fall_back_to_flask_login_user
# @features auth
# @dimensions session-preload fallback
def _load_request_context(entity_identifier=None):
    user, entity = _load_session_user_context(entity_identifier)
    if user:
        return user, entity

    if getattr(current_user, "is_authenticated", False):
        seed_login_session(current_user)

    loaded = (
        Entities.fetch(entity_identifier, request=Fetch.direct())
        if entity_identifier
        else []
    )
    entity = loaded[0] if loaded else None
    return current_user, entity


# @testable true
# @tests tests_e2e/002_home/test_002h_home_permissions.py::test_one_category_permissions
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_task_route_is_forbidden_without_model_or_page_permission
# @features permissions
# @dimensions resource-gates etag authorization-before-cache
def permission(resource=None, requested=None):
    """Check route access using the fixed direct request-auth graph."""

    # @testable false
    # @covered-by lagniappe/web/auth.py::permission
    # @reason closure factory delegates behavior to the parent decorator contract
    def decorator(f):
        # @testable false
        # @covered-by lagniappe/web/auth.py::permission
        # @reason route wrapper behavior is owned by the parent decorator contract
        @wraps(f)
        def wrapped(*args, **kwargs):
            user, entity = _load_request_context(kwargs.get("key"))
            if not user.is_authenticated:
                abort(401)
            elif not resource and not kwargs.get("key"):
                abort(403)

            allowed = False

            if kwargs.get("key") and not entity:
                abort(404)

            if request.method == "GET":
                base_fingerprint = (
                    entity.fingerprint
                    if entity
                    else database.site_fingerprint(request.path)
                )
                g.fingerprint = _etag_fingerprint(base_fingerprint, user)

            if entity:
                allowed = entity.allowed(requested, user)
            elif resource and user.has_permission(resource, requested):
                allowed = True

            if not allowed:
                abort(403)

            if request.method == "GET" and _fingerprint_matches_etag():
                return "", 304

            if entity:
                return f(*args, entity=entity, **kwargs)

            return f(*args, **kwargs)

        return wrapped

    return decorator


# @testable true
# @tests tests_e2e/002_home/test_002h_home_permissions.py::test_anonymous_home_redirects_to_login
# @features home permissions
# @dimensions anonymous-access
def home_permission():
    """Permission for home page sections. No entity-level check, just authentication + ETag."""

    # @testable false
    # @covered-by lagniappe/web/auth.py::home_permission
    # @reason closure factory delegates behavior to the parent decorator contract
    def decorator(f):
        # @testable false
        # @covered-by lagniappe/web/auth.py::home_permission
        # @reason route wrapper behavior is owned by the parent decorator contract
        @wraps(f)
        def wrapped(*args, **kwargs):
            user, _entity = _load_request_context()
            if not user.is_authenticated:
                abort(401)

            if request.method == "GET":
                if kwargs.get("kind") == "starred":
                    base_fingerprint = user.modified.timestamp()
                else:
                    site_fingerprint = database.site_fingerprint(request.path)
                    user_fingerprint = user.modified.timestamp()
                    base_fingerprint = f"{site_fingerprint}:{user_fingerprint}"

                g.fingerprint = _etag_fingerprint(base_fingerprint, user)

                if _fingerprint_matches_etag():
                    return "", 304

            return f(*args, **kwargs)

        return wrapped

    return decorator


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_page_requires_login
# @features search
# @dimensions anonymous-access
def logged_in(f):
    """Simple authentication check with no entity loading or ETag."""

    # @testable false
    # @covered-by lagniappe/web/auth.py::logged_in
    # @reason route wrapper behavior is owned by the parent decorator contract
    @wraps(f)
    def wrapped(*args, **kwargs):
        user, _entity = _load_request_context()
        if not user.is_authenticated:
            abort(401)

        return f(*args, **kwargs)

    return wrapped


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
# @features manual
# @dimensions section-navigation
def manual_permission():
    """Permission for the user manual. Public if CONFIG.PUBLIC_MANUAL is set."""

    # @testable false
    # @covered-by lagniappe/web/auth.py::manual_permission
    # @reason closure factory delegates behavior to the parent decorator contract
    def decorator(f):
        # @testable false
        # @covered-by lagniappe/web/auth.py::manual_permission
        # @reason route wrapper behavior is owned by the parent decorator contract
        @wraps(f)
        def wrapped(*args, **kwargs):
            if CONFIG.PUBLIC_MANUAL:
                return f(*args, **kwargs)

            user, _entity = _load_request_context()
            if user.is_authenticated:
                return f(*args, **kwargs)
            abort(401)

        return wrapped

    return decorator


# @testable true
# @tests tests_e2e/001_site/test_001c_messaging.py::test_allow_messages
# @features messaging
# @dimensions permission-modal
def test_permission(f):
    """Only allows authenticated test users. Returns 404 (not 403) to hide the endpoint."""

    # @testable false
    # @covered-by lagniappe/web/auth.py::test_permission
    # @reason route wrapper behavior is owned by the parent decorator contract
    @wraps(f)
    def wrapped(*args, **kwargs):
        user, _entity = _load_request_context()
        if not user.is_authenticated:
            abort(401)
        if not user.db.get("test_user"):
            abort(404)

        return f(*args, **kwargs)

    return wrapped
