from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

from flask import (
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import agent_access, auth_email, database, identity_platform
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip
from lagniappe.web import csrf
from lagniappe.web.auth import (
    clear_login_session,
    login_cache_invalidation_required,
    request_client_cache_invalidation,
    seed_login_session,
    verify_google_csrf,
)
from lagniappe.web.routes.analytics.main import record_login

from . import users

REMEMBER_PREFERENCE_COOKIE = "lagniappe_remember"
AGENT_ACCESS_SCOPE = "agent-login"


# @testable false
# @covered-by lagniappe/web/routes/users/login.py::login
# @covered-by lagniappe/web/routes/users/login.py::login_agent
# @covered-by lagniappe/web/routes/users/login.py::login_identity
# @reason tiny wrapper keeps Flask-Login and Lagniappe session seeding together
def _login_and_seed(user, remember=False, messaging_disabled=False):
    invalidate_cache = login_cache_invalidation_required(user)
    login_user(user, remember=remember)
    seed_login_session(
        user,
        messaging_disabled=messaging_disabled,
        invalidate_cache=invalidate_cache,
    )


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_sets_hardened_auth_cookies
# @features login
# @dimensions remember-cookie
def _remember_preference(default=True):
    """Read the user's remember-me preference from a lightweight cookie."""
    preference = request.cookies.get(REMEMBER_PREFERENCE_COOKIE)
    if preference is None:
        return default

    return preference not in {"0", "false", "False"}


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_returns_to_requested_url_after_redirect
# @features login
# @dimensions redirect-target
def _safe_redirect_target(target):
    """Return an internal redirect target, or None if the target is unsafe."""
    if not target:
        return None

    target = target.strip()
    if not target or target.startswith(("\\", "//", "/\\")):
        return None

    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        host_url = urlsplit(request.host_url)
        if parts.scheme != host_url.scheme or parts.netloc != host_url.netloc:
            return None

    if not parts.path.startswith("/"):
        return None

    if parts.path == url_for("users.login"):
        return None

    return urlunsplit(("", "", parts.path, parts.query, parts.fragment))


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_returns_to_requested_url_after_redirect
# @tests tests_e2e/001_site/test_001b_login.py::test_login_accepts_google_state_redirect_target
# @features login
# @dimensions redirect-target
def _login_redirect_url():
    """Choose the post-login destination, falling back to home."""
    targets = (
        request.values.get("next"),
        request.values.get("state"),
        session.pop("next", None),
    )
    for target in targets:
        safe_target = _safe_redirect_target(target)
        if safe_target:
            return safe_target

    return url_for("home.home_page")


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_returns_to_requested_url_after_redirect
# @tests tests_e2e/001_site/test_001b_login.py::test_login_google_buttons_carry_safe_next_state
# @features login
# @dimensions redirect-target
def _store_safe_next_from_query():
    """Persist a safe next query parameter for redirect-based auth handoffs."""
    target = request.args.get("next")
    if target is not None:
        safe_target = _safe_redirect_target(target)
        if safe_target:
            session["next"] = safe_target
            return safe_target
        session.pop("next", None)
        return None

    return _safe_redirect_target(session.get("next"))


# @testable false
# @covered-by lagniappe/web/routes/users/login.py::login_agent
# @reason tiny content negotiation helper owned by agent login route
def _wants_json_response():
    return (
        request.headers.get("X-Lagniappe-Request") == "true"
        or request.is_json
        or request.accept_mimetypes["application/json"]
        > request.accept_mimetypes["text/html"]
    )


# @testable false
# @covered-by lagniappe/web/routes/users/login.py::login_agent
# @reason template context helper owned by agent login route
def _agent_login_template(error=None, status=200):
    _store_safe_next_from_query()
    return (
        render_template(
            "users/agent_login.html",
            error=error,
            mode=None,
            code=None,
            google=False,
            g_client_id=getattr(CONFIG, "GOOGLE_CLIENT_ID", ""),
            g_login_uri=getattr(CONFIG, "GOOGLE_LOGIN_URI", ""),
            allow_registration=False,
        ),
        status,
    )


# @testable false
# @covered-by lagniappe/web/routes/users/login.py::_enforce_auth_rate_limit
# @reason response-shaping helper exercised through the auth rate-limit wrapper
def _rate_limit_response(message, retry_after, json_mode=True):
    """Return either JSON or plain-text 429 responses for auth endpoints."""
    if json_mode:
        response = jsonify({"success": False, "error": message})
    else:
        response = make_response(message)

    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_identity_returns_rate_limit_response
# @features login
# @dimensions rate-limit
def _enforce_auth_rate_limit(scope, limit, window_seconds, json_mode=True):
    """Apply a small fixed-window auth rate limit keyed by client IP."""
    ip = client_ip(request)
    result = check_limit(scope, ip, limit, window_seconds)
    if result["allowed"]:
        return None

    exceptions.capture(
        "Auth rate limit exceeded",
        context={
            "auth": {
                "operation": scope,
                "client_ip": ip,
                "retry_after": result["retry_after"],
                "count": result["count"],
            }
        },
        level="warning",
    )
    return _rate_limit_response(
        "Too many login attempts. Please wait and try again.",
        result["retry_after"],
        json_mode=json_mode,
    )


# @testable false
# @manual true
# @reason configured-origin URL selection is validated with live authentication email
def _auth_action_url(mode, oob_code):
    """Build a Lagniappe action URL on the configured login origin."""
    login_uri = str(getattr(CONFIG, "GOOGLE_LOGIN_URI", "") or "").strip()
    configured_url = login_uri or str(CONFIG.APP_URL or "").strip()
    origin = urlsplit(configured_url)
    if origin.scheme != "https" or not origin.netloc:
        raise RuntimeError("Authentication email requires a configured HTTPS URL.")
    query = urlencode({"mode": mode, "oobCode": oob_code})
    return urlunsplit((origin.scheme, origin.netloc, "/users/login", query, ""))


# @testable false
# @manual true
# @reason orchestration requires live Identity Platform code generation and Gmail
def _send_auth_action_email(email, action, *, user_ip=None):
    """Generate an Identity Platform action code and email its Lagniappe URL."""
    request_type = {
        "resetPassword": "PASSWORD_RESET",
        "verifyEmail": "VERIFY_EMAIL",
    }[action]
    oob_code = identity_platform.generate_email_action_code(
        request_type,
        email,
        user_ip=user_ip,
    )
    action_url = _auth_action_url(action, oob_code)
    subject, text_body, html_body = auth_email.auth_action_message(
        action,
        CONFIG.APP_NAME,
        action_url,
    )
    auth_email.send_auth_email(email, subject, text_body, html_body)


# @testable false
# @manual true
# @reason account provisioning decisions are validated through live auth smoke testing
def verify_user(email, name, picture):
    """Verify and create/update user based on authentication."""
    exists = database.get.user(email)

    if not exists and email == CONFIG.ADMIN_EMAIL:
        user = Entities.USER.create(
            {
                "email": email,
                "name": name,
                "picture": picture,
            }
        )
    elif not exists:
        if Entities.PUBLIC_GROUP.enabled():
            user = Entities.USER.create(
                {
                    "is_public": True,
                    "email": email,
                    "name": name,
                    "picture": picture,
                }
            )
        else:
            return None
    else:
        user = Entities.USER(exists)

    user.last_login = datetime.now(timezone.utc)
    user.save()

    return user


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_page_loads
# @tests tests_e2e/001_site/test_001b_login.py::test_user_login_success
# @tests tests_e2e/001_site/test_001b_login.py::test_login_sets_hardened_auth_cookies
# @features login
# @dimensions page-load form-state test-user session cookie-hardening
@users.route("/login", methods=["GET"])
def login():
    test_user = request.values.get("test_user", "").strip()
    if current_user.is_authenticated and not test_user:
        return render_template("users/logged_in.html")

    if CONFIG.development:
        email = test_user or CONFIG.ADMIN_EMAIL
        if not email:
            abort(400, "No email provided")

        name = test_user.split("@")[0] or CONFIG.ADMIN_NAME
        remember = _remember_preference(default=True)
        exists = database.get.user(email)
        if exists:
            user = Entities.USER(exists)
        else:
            user = Entities.USER.create({"email": email, "name": name})

        user.invalidate_cache = True
        user.save()
        _login_and_seed(user, remember=remember)
        record_login(user, "development")
        return redirect(_login_redirect_url(), code=302)
    elif CONFIG.testing and test_user:
        exists = database.get.user(test_user)
        if not exists and test_user == CONFIG.ADMIN_EMAIL:
            user = Entities.USER.create({"email": test_user, "name": CONFIG.ADMIN_NAME})
            user.save()
            exists = user.db
        elif not exists:
            abort(403, "User not registered")

        user = Entities.USER(exists)
        if not user.is_test_user:
            user.is_test_user = True
            user.save()

        _login_and_seed(user, remember=_remember_preference(default=True))
        record_login(user, "testing")

        return redirect(_login_redirect_url(), code=302)

    next_url = _store_safe_next_from_query()
    return render_template(
        "users/login.html",
        mode=request.args.get("mode"),
        code=request.args.get("oobCode"),
        google=CONFIG.production,
        g_client_id=CONFIG.GOOGLE_CLIENT_ID,
        g_login_uri=CONFIG.GOOGLE_LOGIN_URI,
        next_url=next_url,
        allow_registration=Entities.PUBLIC_GROUP.enabled(),
    )


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_agent_access_login_form_creates_session
# @features login
# @dimensions agent-access session user-page
@users.route("/agent-login", methods=["GET", "POST"])
def login_agent():
    if not agent_access.enabled():
        abort(404)

    if request.method == "GET":
        return _agent_login_template()

    wants_json = _wants_json_response()
    limited = _enforce_auth_rate_limit(AGENT_ACCESS_SCOPE, 8, 300, json_mode=wants_json)
    if limited:
        return limited

    data = request.get_json(silent=True) if request.is_json else request.form
    if not agent_access.code_matches((data or {}).get("code")):
        if wants_json:
            return jsonify({"success": False, "error": "Invalid access code"}), 401
        return _agent_login_template("Invalid access code", status=401)

    user = agent_access.get_or_create_user()
    _login_and_seed(
        user,
        remember=_remember_preference(default=True),
        messaging_disabled=True,
    )
    record_login(user, "agent")

    if wants_json:
        return jsonify({"success": True, "redirect": _login_redirect_url()})
    return redirect(_login_redirect_url(), code=302)


# @testable false
# @manual true
# @reason live Google OAuth callback requires manual/provider validation
@users.route("/google-signin", methods=["POST"])
@csrf.exempt
def login_google():
    """Exchange a Google credential through Identity Platform and sign in."""
    limited = _enforce_auth_rate_limit("google-signin", 20, 300, json_mode=False)
    if limited:
        return limited

    verify_google_csrf(request)

    token = request.values.get("credential")
    if not token:
        abort(400, "No credential provided")

    try:
        google_login = urlsplit(CONFIG.GOOGLE_LOGIN_URI)
        identity_request_uri = urlunsplit(
            (google_login.scheme, google_login.netloc, "", "", "")
        )
        exchange = identity_platform.exchange_google_credential(
            token,
            CONFIG.IDENTITY_PLATFORM_CONFIG,
            identity_request_uri,
        )
        idinfo = identity_platform.verify_identity_token(
            exchange["idToken"],
            CONFIG.IDENTITY_PLATFORM_CONFIG["projectId"],
        )

        email = str(idinfo.get("email") or exchange.get("email") or "").strip()
        if not email or idinfo.get("email_verified") is not True:
            abort(401, "Google email is not verified")
        name = idinfo.get("name") or exchange.get("displayName")
        picture = idinfo.get("picture") or exchange.get("photoUrl")

        user = verify_user(email, name, picture)
        if not user:
            abort(401, "User not registered")

        _login_and_seed(user, remember=_remember_preference(default=True))
        record_login(user, "identity-google")
    except (ValueError, identity_platform.IdentityPlatformError) as e:
        context = {
            "auth": {
                "operation": "identity_google_exchange",
                "has_token": bool(token),
            }
        }
        exceptions.capture(e, context)
        abort(401, "Invalid token")

    return redirect(_login_redirect_url())


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_identity_returns_rate_limit_response
# @features login
# @dimensions identity-platform rate-limit
@users.route("/login-identity", methods=["POST"])
def login_identity():
    """Handle Identity Platform email/password authentication."""
    try:
        limited = _enforce_auth_rate_limit("login-identity", 20, 300)
        if limited:
            return limited

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        token = data.get("authResult")
        if not token:
            return jsonify({"success": False, "error": "No token provided"}), 400

        try:
            identity_config = CONFIG.IDENTITY_PLATFORM_CONFIG
            decoded_token = identity_platform.verify_identity_token(
                token,
                identity_config["projectId"],
            )
        except Exception as e:
            context = {
                "auth": {
                    "operation": "identity_token_verify",
                    "has_token": bool(token),
                }
            }
            exceptions.capture(e, context)
            return jsonify({"success": False, "error": "Invalid token"}), 401

        email = decoded_token.get("email", "").strip().lower()
        if not email:
            return jsonify({"success": False, "error": "No email in token"}), 401

        email_verified = decoded_token.get("email_verified", False)
        if not email_verified:
            return (
                jsonify(
                    {
                        "success": False,
                        "requires_verification": True,
                    }
                ),
                403,
            )

        name = data.get("name") or decoded_token.get("name") or email.split("@")[0]
        remember = data.get("remember", False)

        user = verify_user(email, name, decoded_token.get("picture"))
        if not user:
            return jsonify({"success": False, "error": "User not registered"}), 401

        _login_and_seed(user, remember=remember)
        return jsonify(
            {
                "success": True,
                "redirect": _login_redirect_url(),
            }
        )

    except Exception as e:
        context = {
            "auth": {
                "operation": "identity_login",
                "has_data": bool(request.get_json()),
            }
        }
        exceptions.capture(e, context)
        return jsonify({"success": False, "error": "Authentication failed"}), 500


# @testable false
# @manual true
# @reason password-reset email delivery requires live Identity Platform and Gmail
@users.route("/send-password-reset-email", methods=["POST"])
def send_password_reset_email():
    """Generate and deliver a password-reset link without enumerating accounts."""
    limited = _enforce_auth_rate_limit("password-reset-email", 5, 900)
    if limited:
        return limited
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"success": False, "error": "Email required"}), 400

    try:
        _send_auth_action_email(
            email,
            "resetPassword",
            user_ip=client_ip(request),
        )
    except Exception as error:
        # The response remains identical for unknown accounts and delivery
        # failures so this endpoint cannot reveal registered email addresses.
        exceptions.capture(
            error,
            {
                "auth": {
                    "operation": "password_reset_email",
                }
            },
        )
    return jsonify({"success": True})


# @testable false
# @manual true
# @reason verification email delivery requires live Identity Platform and Gmail
@users.route("/send-verification-email", methods=["POST"])
def send_verification_email():
    """Deliver a verification link for the authenticated Identity user."""
    limited = _enforce_auth_rate_limit("verification-email", 5, 900)
    if limited:
        return limited
    data = request.get_json(silent=True) or {}
    token = str(data.get("idToken") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Identity token required"}), 400

    try:
        identity_config = CONFIG.IDENTITY_PLATFORM_CONFIG
        claims = identity_platform.verify_identity_token(
            token,
            identity_config["projectId"],
        )
    except Exception as error:
        exceptions.capture(
            error,
            {
                "auth": {
                    "operation": "verification_email_identity",
                    "has_token": bool(token),
                }
            },
        )
        return jsonify({"success": False, "error": "Invalid identity"}), 401
    email = str(claims.get("email") or "").strip().lower()
    if not email:
        return jsonify({"success": False, "error": "No email in token"}), 401

    try:
        _send_auth_action_email(email, "verifyEmail")
    except (
        auth_email.AuthEmailError,
        identity_platform.IdentityPlatformError,
    ) as error:
        exceptions.capture(
            error,
            {
                "auth": {
                    "operation": "verification_email_delivery",
                }
            },
        )
        return jsonify({"success": False, "error": "Email delivery failed"}), 503
    return jsonify({"success": True})


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_check_user_status_endpoint_does_not_enumerate_accounts
# @tests tests_e2e/001_site/test_001b_login.py::test_check_user_status_endpoint_returns_first_time_setup
# @features login
# @dimensions account-enumeration first-time-setup endpoint
@users.route("/check-user-status", methods=["GET"])
def check_user_status():
    """Return the next login step without exposing detailed account metadata."""
    try:
        limited = _enforce_auth_rate_limit("check-user-status", 30, 300)
        if limited:
            return limited

        email = request.args.get("email", "").strip().lower()

        if not email:
            return jsonify({"success": False, "error": "Email required"}), 400

        next_step = "signin"
        exists = database.get.user(email)
        if exists:
            user = Entities.USER(exists)
            if user.last_login is None:
                next_step = "first_time_setup"

        return jsonify(
            {
                "success": True,
                "next": next_step,
            }
        )

    except Exception as e:
        context = {
            "auth": {
                "operation": "check_user_status",
                "email": request.args.get("email", "unknown"),
            }
        }
        exceptions.capture(e, context)
        return jsonify({"success": False, "error": "System error"}), 500


# @testable false
# @covered-by lagniappe/web/routes/users/login.py::logout
# @reason logout route owns the authenticated user/session transition
def _mark_logout_cache_invalidation():
    """Flag the current user's client cache before ending the session."""
    if not getattr(current_user, "is_authenticated", False):
        return None

    user = Entities.fetch_one(
        current_user._get_current_object(),
        request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
    )
    user.invalidate_cache = True
    user.save()
    return user


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_logout_clears_session_and_returns_login
# @tests tests_e2e/001_site/test_001b_login.py::test_logout_flags_user_cache_invalidation
# @features login
# @dimensions logout session invalidation ajax redirect
@users.route("/logout", methods=["POST"])
def logout():
    """Log the user out and return the normal login-page redirect target."""
    _mark_logout_cache_invalidation()
    logout_user()
    clear_login_session()
    request_client_cache_invalidation()
    return jsonify({"success": True, "redirect": url_for("users.login")})
