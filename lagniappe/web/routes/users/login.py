from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models

from datetime import datetime, UTC
import re
import secrets
from urllib.parse import urlencode, urlsplit, urlunsplit

from flask import (
    abort,
    g,
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
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.auth import agent_access
from lagniappe.core.tools.email import smtp as auth_email
from lagniappe.core.tools.services import identity_platform
from lagniappe.core.tools.cache.rate_limit import check_limit, client_ip
from lagniappe.web.auth import (
    clear_login_session,
    is_demo_guest_session,
    login_cache_invalidation_required,
    request_client_cache_invalidation,
    seed_login_session,
    verify_google_csrf,
)
from lagniappe.web.routes.analytics.main import record_login

from . import users

REMEMBER_PREFERENCE_COOKIE = "lagniappe_remember"
AGENT_ACCESS_SCOPE = "agent-login"
DEMO_LOGIN_SCOPE = "demo-login"
_LOGIN_NOTICE_MAX_LENGTH = 500
_LOGIN_NOTICE_LINK_PATTERN = re.compile(
    r"\[([^\[\]\n]{1,120})\]\(([^()\s]{1,300})\)"
)


class LoginNoticeSegment(TypedDict):
    kind: Literal["text", "link", "break"]
    text: str
    href: str
    external: bool


def _safe_notice_link(url: str) -> tuple[str, bool] | None:
    """Allow only internal root-relative paths or explicit HTTPS URLs."""
    candidate = url.strip()
    if not candidate or any(ord(ch) < 32 for ch in candidate):
        return None
    if candidate.startswith("/"):
        if candidate.startswith(("//", "/\\")):
            return None
        return candidate, False
    parts = urlsplit(candidate)
    if parts.scheme == "https" and parts.netloc:
        return candidate, True
    return None


def parse_login_notice(raw: object) -> list[LoginNoticeSegment]:
    """Parse an optional plain-text login notice with safe inline links."""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > _LOGIN_NOTICE_MAX_LENGTH:
        text = text[:_LOGIN_NOTICE_MAX_LENGTH].rstrip()

    segments: list[LoginNoticeSegment] = []

    def append_plain(chunk: str) -> None:
        if not chunk:
            return
        lines = chunk.split("\n")
        for index, line in enumerate(lines):
            if line:
                segments.append(
                    {"kind": "text", "text": line, "href": "", "external": False}
                )
            if index < len(lines) - 1:
                segments.append(
                    {"kind": "break", "text": "", "href": "", "external": False}
                )

    cursor = 0
    for match in _LOGIN_NOTICE_LINK_PATTERN.finditer(text):
        append_plain(text[cursor : match.start()])
        label = match.group(1).strip()
        safe = _safe_notice_link(match.group(2)) if label else None
        if safe is not None:
            href, external = safe
            segments.append(
                {
                    "kind": "link",
                    "text": label,
                    "href": href,
                    "external": external,
                }
            )
        else:
            append_plain(match.group(0))
        cursor = match.end()

    append_plain(text[cursor:])
    return segments


def _demo_guest_email() -> str:
    return str(getattr(CONFIG, "DEMO_GUEST_EMAIL", "") or "").strip().casefold()


def _demo_guest_privileged_email(email: str) -> bool:
    owner_email = str(getattr(CONFIG, "ADMIN_EMAIL", "") or "").strip().casefold()
    bootstrap_email = (
        str(getattr(CONFIG, "BOOTSTRAP_ADMIN_EMAIL", "") or "").strip().casefold()
    )
    return bool(email and email in {owner_email, bootstrap_email})


def _demo_guest_enabled(owner_setup: bool) -> bool:
    demo_email = _demo_guest_email()
    return bool(
        demo_email
        and not owner_setup
        and not _demo_guest_privileged_email(demo_email)
    )


def _login_and_seed(user, remember=False):
    invalidate_cache = login_cache_invalidation_required(user)
    login_user(user, remember=remember)
    seed_login_session(
        user,
        invalidate_cache=invalidate_cache,
    )


def _remember_preference(default=True):
    """Read the user's remember-me preference from a lightweight cookie."""
    preference = request.cookies.get(REMEMBER_PREFERENCE_COOKIE)
    if preference is None:
        return default

    return preference not in {"0", "false", "False"}


def _owner_requires_first_login():
    """Return whether the configured owner still needs an initial login."""
    owner_email = str(CONFIG.ADMIN_EMAIL or "").strip().lower()
    if not owner_email:
        return False

    exists = database_get.user(owner_email)
    if not exists:
        return True

    return Entities.USER(exists).last_login is None


def _bootstrap_admin_allowed(email):
    """Allow exactly the configured installer while the Owner is uninitialized."""
    bootstrap_email = (
        str(getattr(CONFIG, "BOOTSTRAP_ADMIN_EMAIL", "") or "").strip().casefold()
    )
    candidate = str(email or "").strip().casefold()
    return bool(
        bootstrap_email
        and candidate == bootstrap_email
        and _owner_requires_first_login()
    )


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


def _wants_json_response():
    return (
        request.headers.get("X-Lagniappe-Request") == "true"
        or request.is_json
        or request.accept_mimetypes["application/json"]
        > request.accept_mimetypes["text/html"]
    )


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


def _rate_limit_response(message, retry_after, json_mode=True):
    """Return either JSON or plain-text 429 responses for auth endpoints."""
    if json_mode:
        response = jsonify({"success": False, "error": message})
    else:
        response = make_response(message)

    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


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


def _auth_action_url(mode, oob_code, next_target=None):
    """Build a Lagniappe action URL on the configured login origin."""
    login_uri = str(getattr(CONFIG, "GOOGLE_LOGIN_URI", "") or "").strip()
    configured_url = login_uri or str(CONFIG.APP_URL or "").strip()
    origin = urlsplit(configured_url)
    if origin.scheme != "https" or not origin.netloc:
        raise RuntimeError("Authentication email requires a configured HTTPS URL.")
    query_values = {"mode": mode, "oobCode": oob_code}
    if next_target:
        query_values["next"] = next_target
    query = urlencode(query_values)
    return urlunsplit((origin.scheme, origin.netloc, "/users/login", query, ""))


def _send_auth_action_email(email, action, *, user_ip=None, next_target=None):
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
    action_url = _auth_action_url(action, oob_code, next_target)
    subject, text_body, html_body = auth_email.auth_action_message(
        action,
        CONFIG.APP_NAME,
        action_url,
    )
    auth_email.send_auth_email(email, subject, text_body, html_body)


def verify_user(
    email: str,
    name: str | None,
    picture: str | None,
    *,
    allow_bootstrap_admin: bool = False,
) -> models.User | None:
    """Verify and create/update user based on authentication."""
    email = str(email or "").strip().lower()
    exists = database_get.user(email)

    owner_email = str(CONFIG.ADMIN_EMAIL or "").strip().lower()
    if not exists and email == owner_email:
        user = Entities.USER.create(
            {
                "email": email,
                "name": name,
                "picture": picture,
            }
        )
    elif not exists and allow_bootstrap_admin and _bootstrap_admin_allowed(email):
        user = Entities.USER.create(
            {
                "email": email,
                "name": name,
                "picture": picture,
                "admin": True,
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

    user.last_login = datetime.now(UTC)
    user.save()

    return user


@users.route("/login", methods=["GET"])
def login() -> ResponseReturnValue:
    test_user = request.values.get("test_user", "").strip()
    if current_user.is_authenticated and not test_user:
        return render_template("users/logged_in.html")

    if CONFIG.development:
        email = test_user or CONFIG.ADMIN_EMAIL
        if not email:
            abort(400, "No email provided")

        name = test_user.split("@")[0] or CONFIG.ADMIN_NAME
        remember = _remember_preference(default=True)
        exists = database_get.user(email)
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
        exists = database_get.user(test_user)
        if not exists and test_user == CONFIG.ADMIN_EMAIL:
            user = Entities.USER.create({"email": test_user, "name": CONFIG.ADMIN_NAME})
            user.save()
        elif not exists:
            abort(403, "User not registered")
        else:
            user = Entities.USER(exists)
        if not user.is_test_user:
            user.is_test_user = True
            user.save()

        _login_and_seed(user, remember=_remember_preference(default=True))
        record_login(user, "testing")

        return redirect(_login_redirect_url(), code=302)

    next_url = _store_safe_next_from_query()
    allow_registration = Entities.PUBLIC_GROUP.enabled()
    owner_setup = _owner_requires_first_login()
    google_signin_enabled = CONFIG.GOOGLE_SIGNIN_ENABLED is True
    google = CONFIG.production and google_signin_enabled
    if google:
        try:
            google = identity_platform.google_provider_enabled()
        except (identity_platform.IdentityPlatformError, RuntimeError) as error:
            exceptions.capture(
                error,
                context={"auth": {"operation": "google_provider_status"}},
                level="warning",
            )
            # A control-plane read failure should not disable a working login method.
            google = True
    if google:
        # GIS copies the script nonce onto its injected button stylesheet.
        g.google_style_nonce = secrets.token_urlsafe(32)
    auth_error = {
        "google-not-registered": (
            "That Google account does not have access to this site. "
            "Contact the site owner if you think this is a mistake."
        ),
        "google-user-disabled": (
            "This account is disabled and cannot sign in. "
            "Contact the site owner if you think this is a mistake."
        ),
    }.get(request.args.get("authError", ""))
    return render_template(
        "users/login.html",
        mode=request.args.get("mode"),
        code=request.args.get("oobCode"),
        google=google,
        google_available=google_signin_enabled and (not CONFIG.production or google),
        g_client_id=CONFIG.GOOGLE_CLIENT_ID,
        g_login_uri=CONFIG.GOOGLE_LOGIN_URI,
        next_url=next_url,
        allow_registration=allow_registration,
        owner_setup=owner_setup,
        owner_email=CONFIG.ADMIN_EMAIL if owner_setup else "",
        auth_error=auth_error,
        demo_guest_enabled=_demo_guest_enabled(owner_setup),
        login_notice_segments=parse_login_notice(getattr(CONFIG, "LOGIN_NOTICE", "")),
    )


@users.route("/demo-login", methods=["POST"])
def demo_login() -> ResponseReturnValue:
    """Sign into the optional read-only demo guest account."""
    demo_email = _demo_guest_email()
    if not demo_email or _owner_requires_first_login():
        abort(404)

    wants_json = _wants_json_response()
    limited = _enforce_auth_rate_limit(
        DEMO_LOGIN_SCOPE, 20, 300, json_mode=wants_json
    )
    if limited:
        return limited

    if _demo_guest_privileged_email(demo_email):
        exceptions.capture(
            "Refusing demo guest login for privileged account",
            context={"auth": {"operation": "demo_login"}},
            level="warning",
        )
        abort(403, "Demo guest account is unavailable.")

    exists = database_get.user(demo_email)
    if not exists:
        abort(403, "Demo guest account is unavailable.")

    user = Entities.USER(exists)
    if getattr(user, "is_owner", False) or getattr(user, "is_admin", False):
        exceptions.capture(
            "Refusing demo guest login for administrator account",
            context={"auth": {"operation": "demo_login"}},
            level="warning",
        )
        abort(403, "Demo guest account is unavailable.")

    _login_and_seed(user, remember=False)
    session[CONFIG.LOGIN_DEMO_GUEST_KEY] = True
    record_login(user, "demo-guest")

    target = _login_redirect_url()
    if wants_json:
        return jsonify({"success": True, "redirect": target})
    return redirect(target, code=302)


@users.route("/agent-login", methods=["GET", "POST"])
def login_agent() -> ResponseReturnValue:
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
    if not isinstance(user, Entities.USER):
        abort(403)
    _login_and_seed(user, remember=_remember_preference(default=True))
    record_login(user, "agent")

    if wants_json:
        return jsonify({"success": True, "redirect": _login_redirect_url()})
    return redirect(_login_redirect_url(), code=302)


@users.route("/google-signin", methods=["POST"])
def login_google() -> ResponseReturnValue:
    """Exchange a Google credential through Identity Platform and sign in."""
    limited = _enforce_auth_rate_limit("google-signin", 20, 300, json_mode=False)
    if limited:
        return limited

    # Startup exempts only this users view from Flask-WTF. This route must keep
    # Google's independent cookie/body double-submit verification before auth.
    verify_google_csrf(request)

    if CONFIG.GOOGLE_SIGNIN_ENABLED is not True:
        query = {}
        safe_state = _safe_redirect_target(request.values.get("state"))
        if safe_state:
            query["next"] = safe_state
        return redirect(url_for("users.login", authError=query.get("authError"), next=query.get("next")))

    token = request.values.get("credential")
    if not token:
        abort(400, "No credential provided")

    try:
        google_claims = identity_platform.verify_google_credential(
            token,
            CONFIG.GOOGLE_CLIENT_ID,
        )
        google_email = str(google_claims.get("email") or "").strip().lower()
        owner_email = str(CONFIG.ADMIN_EMAIL or "").strip().lower()
        registered = bool(database_get.user(google_email))
        if (
            not registered
            and google_email != owner_email
            and not _bootstrap_admin_allowed(google_email)
            and not Entities.PUBLIC_GROUP.enabled()
        ):
            query = {"authError": "google-not-registered"}
            safe_state = _safe_redirect_target(request.values.get("state"))
            if safe_state:
                query["next"] = safe_state
            return redirect(url_for("users.login", authError=query.get("authError"), next=query.get("next")))

        google_login = urlsplit(CONFIG.GOOGLE_LOGIN_URI)
        identity_request_uri = urlunsplit(
            (google_login.scheme, google_login.netloc, "", "", "")
        )
        exchange = identity_platform.exchange_google_credential(
            token,
            CONFIG.IDENTITY_PLATFORM_CONFIG,
            identity_request_uri,
        )
        id_token = exchange.get("idToken")
        if not isinstance(id_token, str):
            raise identity_platform.IdentityPlatformError("Missing identity token")
        idinfo = identity_platform.verify_identity_token(
            id_token,
            CONFIG.IDENTITY_PLATFORM_CONFIG["projectId"],
        )

        email = str(idinfo.get("email") or exchange.get("email") or "").strip().lower()
        if not email or idinfo.get("email_verified") is not True:
            abort(401, "Google email is not verified")
        if email != google_email:
            abort(401, "Google identity email does not match")
        name = idinfo.get("name") or exchange.get("displayName")
        picture = idinfo.get("picture") or exchange.get("photoUrl")

        user = verify_user(
            email,
            name if isinstance(name, str) else None,
            picture if isinstance(picture, str) else None,
            allow_bootstrap_admin=True,
        )
        if not user:
            abort(401, "Authentication failed")

        _login_and_seed(user, remember=_remember_preference(default=True))
        record_login(user, "identity-google")
    except identity_platform.IdentityPlatformError as e:
        context = {
            "auth": {
                "operation": "identity_google_exchange",
                "has_token": bool(token),
                "provider_code": e.provider_code,
            }
        }
        exceptions.capture(e, context)
        if e.provider_code in {"USER_DISABLED", "OPERATION_NOT_ALLOWED"}:
            query = {}
            if e.provider_code == "USER_DISABLED":
                query["authError"] = "google-user-disabled"
            safe_state = _safe_redirect_target(request.values.get("state"))
            if safe_state:
                query["next"] = safe_state
            return redirect(url_for("users.login", authError=query.get("authError"), next=query.get("next")))
        abort(401, "Invalid token")
    except ValueError as e:
        context = {
            "auth": {
                "operation": "identity_google_exchange",
                "has_token": bool(token),
            }
        }
        exceptions.capture(e, context)
        abort(401, "Invalid token")

    return redirect(_login_redirect_url())


@users.route("/login-identity", methods=["POST"])
def login_identity() -> ResponseReturnValue:
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

        email_claim = decoded_token.get("email")
        email = email_claim.strip().lower() if isinstance(email_claim, str) else ""
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

        picture = decoded_token.get("picture")
        user = verify_user(
            email, name if isinstance(name, str) else None,
            picture if isinstance(picture, str) else None,
        )
        if not user:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Incorrect email or password.",
                    }
                ),
                401,
            )

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


@users.route("/send-password-reset-email", methods=["POST"])
def send_password_reset_email() -> ResponseReturnValue:
    """Generate and deliver a password-reset link without enumerating accounts."""
    limited = _enforce_auth_rate_limit("password-reset-email", 5, 900)
    if limited:
        return limited
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"success": False, "error": "Email required"}), 400

    try:
        # Check the sender before consulting Identity Platform so an unavailable
        # SMTP account produces the same response for every submitted address.
        auth_email.check_auth_email_connection()
    except auth_email.AuthEmailError as error:
        exceptions.capture(
            error,
            {
                "auth": {
                    "operation": "password_reset_email_availability",
                }
            },
        )
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Password reset email is temporarily unavailable",
                }
            ),
            503,
        )

    try:
        _send_auth_action_email(
            email,
            "resetPassword",
            user_ip=client_ip(request),
            next_target=_safe_redirect_target(session.get("next")),
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


@users.route("/send-verification-email", methods=["POST"])
def send_verification_email() -> ResponseReturnValue:
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
        _send_auth_action_email(
            email,
            "verifyEmail",
            next_target=_safe_redirect_target(session.get("next")),
        )
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


@users.route("/check-user-status", methods=["GET"])
def check_user_status() -> ResponseReturnValue:
    """Return the next login step without exposing detailed account metadata."""
    try:
        limited = _enforce_auth_rate_limit("check-user-status", 30, 300)
        if limited:
            return limited

        email = request.args.get("email", "").strip().lower()

        if not email:
            return jsonify({"success": False, "error": "Email required"}), 400

        next_step = "signin"
        exists = database_get.user(email)
        if exists:
            user = Entities.USER(exists)
            if user.last_login is None:
                next_step = "first_time_setup"
        elif Entities.PUBLIC_GROUP.enabled():
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


def _mark_logout_cache_invalidation():
    """Flag the current user's client cache before ending the session."""
    if not getattr(current_user, "is_authenticated", False):
        return None

    user = Entities.fetch_one(
        current_user._get_current_object(),
        request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
    )
    if not isinstance(user, Entities.USER):
        return None
    user.invalidate_cache = True
    user.save()
    return user


@users.route("/logout", methods=["POST"])
def logout() -> ResponseReturnValue:
    """Log the user out and return the normal login-page redirect target."""
    if not is_demo_guest_session():
        _mark_logout_cache_invalidation()
    logout_user()
    clear_login_session()
    request_client_cache_invalidation()
    return jsonify({"success": True, "redirect": url_for("users.login")})
