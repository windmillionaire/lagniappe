"""
Login functionality tests.

Tests the complete login workflow including Identity Platform integration,
form state transitions, query parameter modes, and test authentication bypass.

Related Files:
    Application:
        - lagniappe/web/routes/users/login.py: Login route, test_user bypass
        - lagniappe/web/routes/users/main.py: User routes
        - lagniappe/web/templates/users/login.html: Login page template
        - src/script/views/login.mjs: Client-side form state management

    Test Framework:
        - testing/definitions/site_pages.py: SitePages.LOGIN_PAGE
        - testing/resources/site.py: LoginPage form selectors
        - testing/resources/tools/site_common.py: Buttons.SIGNIN, FormElements.EMAIL, Roles.ERROR
        - config/__init__.py: SETTINGS.test_config ADMIN_EMAIL for registered-user flows

Authentication Modes:
    The login page supports multiple modes via query parameters:
    - (default): Sign-in form
    - ?mode=resetPassword&oobCode=xxx: Password reset form
    - ?mode=verifyEmail&oobCode=xxx: Email verification form

    In test environment, ?test_user={email} bypasses Identity Platform and creates
    a session directly (see lagniappe/web/routes/users/login.py).

Form State Machine:
    The login page uses a client-side state machine (login.mjs) that shows/hides
    forms based on user state:
    1. AUTH_METHOD_FORM: Default Google-or-email chooser
    2. EMAIL_CHECK_FORM: Email-only account routing
    3. SIGN_IN_FORM or FIRST_TIME_SETUP_FORM: Password-only step
    4. FORGOT_PASSWORD_FORM: Password reset request
    5. RESET_PASSWORD_FORM: New password entry
    6. VERIFY_EMAIL_FORM: Email verification confirmation
"""

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import expect

from config import SETTINGS, Environment, constants
from lagniappe import CONFIG
from lagniappe.core.entities import Entities
from lagniappe.core.tools import auth_email, database, identity_platform
from lagniappe.web import app

from testing.definitions import SitePages, Users
from testing.elements import Buttons, FormElements, Roles
from testing.utility import assert_lagniappe_error_response, expect_successful_response

pytestmark = pytest.mark.e2e


def _site_url(path):
    return f"{SETTINGS.test_config['BASE_URL']}{path}"


def _set_cookie_headers(response):
    headers_array = response.headers_array
    if callable(headers_array):
        headers_array = headers_array()
    return [
        header["value"]
        for header in headers_array
        if header["name"].lower() == "set-cookie"
    ]


def _session_serializer():
    app = Flask(__name__)
    app.config.update(SECRET_KEY=CONFIG.SECRET_KEY)
    return SecureCookieSessionInterface().get_signing_serializer(app)


def _session_cookie(context):
    return next(cookie for cookie in context.cookies() if cookie["name"] == "session")


REMEMBER_ME = "input[name='remember-me']"
PASSWORD = "input[type='password']"
FIRST_TIME_BACK = "button[data-role='back-to-email']"
FORGOT_BACK = "button[data-role='back-to-signin']"
VERIFY_FORGOT_PASSWORD = "#verifyEmail button[data-role='show-forgot-form']"
RESET_PASSWORD = "button[data-role='reset-password']"
REQUEST_NEW_RESET_LINK = "button[data-role='request-new-reset-link']"
OWNER_PASSWORD_SETUP = "[data-role='owner-password-setup']"

_IDENTITY_PLATFORM_API = re.compile(
    r"https://identitytoolkit\.googleapis\.com/(?:v1|v2)/.*"
)


def _json_response(route, data, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(data),
    )


def _request_json(request):
    return json.loads(request.post_data or "{}")


def _base64url(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def _identity_id_token(email, uid, verified=True, name=None):
    now = int(time.time())
    payload = {
        "iss": "https://securetoken.google.com/lagniappe-test",
        "aud": "lagniappe-test",
        "auth_time": now,
        "user_id": uid,
        "sub": uid,
        "iat": now,
        "exp": now + 3600,
        "email": email,
        "email_verified": verified,
        "firebase": {"sign_in_provider": "password"},
    }
    if name:
        payload["name"] = name

    return ".".join(
        [
            _base64url({"alg": "RS256", "typ": "JWT"}),
            _base64url(payload),
            "signature",
        ]
    )


def _identity_error(route, message):
    _json_response(route, {"error": {"message": message}}, status=400)


def _mock_identity_platform(
    page,
    *,
    sign_up_errors=None,
    sign_in_errors=None,
    reset_password_errors=None,
    sign_up_verified=True,
    sign_in_verified=True,
):
    calls = {
        "lookup": [],
        "send_oob": [],
        "sign_in": [],
        "sign_up": [],
        "reset_password": [],
        "update": [],
        "unexpected": [],
    }
    sign_up_errors = list(sign_up_errors or [])
    sign_in_errors = list(sign_in_errors or [])
    reset_password_errors = list(reset_password_errors or [])
    users_by_token = {}

    def success_response(payload, verified):
        email = payload["email"]
        uid = f"identity-{uuid4().hex}"
        token = _identity_id_token(email, uid, verified=verified)
        users_by_token[token] = {
            "localId": uid,
            "email": email,
            "emailVerified": verified,
            "displayName": payload.get("displayName"),
            "passwordHash": "test-password-hash",
            "providerUserInfo": [],
            "createdAt": "0",
            "lastLoginAt": "0",
        }
        return {
            "idToken": token,
            "email": email,
            "refreshToken": f"refresh-{uid}",
            "expiresIn": "3600",
            "localId": uid,
        }

    def handler(route):
        url = route.request.url
        payload = _request_json(route.request)

        if "accounts:signUp" in url:
            calls["sign_up"].append(payload)
            if sign_up_errors:
                _identity_error(route, sign_up_errors.pop(0))
            else:
                _json_response(route, success_response(payload, sign_up_verified))
        elif "accounts:signInWithPassword" in url:
            calls["sign_in"].append(payload)
            if sign_in_errors:
                _identity_error(route, sign_in_errors.pop(0))
            else:
                _json_response(route, success_response(payload, sign_in_verified))
        elif "accounts:resetPassword" in url:
            calls["reset_password"].append(payload)
            reset_error = (
                reset_password_errors.pop(0) if reset_password_errors else None
            )
            if reset_error:
                _identity_error(route, reset_error)
            else:
                _json_response(route, {"email": "reset-user@example.test"})
        elif "accounts:lookup" in url:
            calls["lookup"].append(payload)
            user_data = users_by_token[payload["idToken"]]
            _json_response(route, {"users": [user_data]})
        elif "accounts:sendOobCode" in url:
            calls["send_oob"].append(payload)
            user_data = users_by_token[payload["idToken"]]
            _json_response(route, {"email": user_data["email"]})
        elif "accounts:update" in url:
            calls["update"].append(payload)
            _json_response(route, {"email": payload.get("email", "verified@test.com")})
        else:
            calls["unexpected"].append({"url": url, "payload": payload})
            _json_response(
                route,
                {"error": {"message": "Unexpected Identity Platform call"}},
                500,
            )

    page.route(_IDENTITY_PLATFORM_API, handler)
    return calls


def _mock_login_identity(page, calls, response, status=200):
    def handler(route):
        calls.append(_request_json(route.request))
        _json_response(route, response, status=status)

    page.route("**/users/login-identity", handler)


def _mock_verification_email_delivery(page, calls, failures=None):
    """Stub the live provider/email boundary while preserving the browser request."""

    failures = list(failures or [])

    def handler(route):
        calls.append(_request_json(route.request))
        if failures and failures.pop(0):
            _json_response(
                route,
                {
                    "success": False,
                    "error": "Email delivery failed: private provider detail",
                },
                status=503,
            )
            return
        _json_response(route, {"success": True})

    page.route("**/users/send-verification-email", handler)


def _mock_password_reset_email_delivery(page, calls, failures=None):
    """Stub password-reset delivery while preserving the visible form flow."""

    failures = list(failures or [])

    def handler(route):
        calls.append(_request_json(route.request))
        if failures and failures.pop(0):
            _json_response(
                route,
                {
                    "success": False,
                    "error": "Password reset failed: private provider detail",
                },
                status=503,
            )
            return
        _json_response(route, {"success": True})

    page.route("**/users/send-password-reset-email", handler)


def _mock_document(page, path, title):
    page.route(
        f"**{path}",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=f"<!doctype html><title>{title}</title><main>{title}</main>",
        ),
    )


def _create_first_time_user(email, name="First Time User"):
    from lagniappe.core.entities import Entities

    provisioned_user = Entities.USER.create(
        {
            "email": email,
            "name": name,
            "groups": [],
            "test_user": True,
        }
    )
    provisioned_user.save()
    return provisioned_user


def _ensure_owner_initialized():
    """Ensure ordinary login tests do not enter the owner bootstrap state."""
    email = SETTINGS.test_config["ADMIN_EMAIL"]
    exists = database.get.user(email)
    owner = (
        Entities.USER(exists)
        if exists
        else Entities.USER.create(
            {
                "email": email,
                "name": SETTINGS.test_config["ADMIN_NAME"],
                "test_user": True,
            }
        )
    )
    owner.last_login = datetime.now(timezone.utc)
    owner.save()


@contextmanager
def _owner_waiting_for_first_login():
    """Temporarily place an existing test owner back into first-login state."""
    email = SETTINGS.test_config["ADMIN_EMAIL"]
    exists = database.get.user(email)
    had_last_login = bool(exists and "last_login" in exists)
    previous_last_login = exists.get("last_login") if exists else None
    if exists:
        exists.pop("last_login", None)
        database.save_raw(exists)
    try:
        yield
    finally:
        if exists:
            if had_last_login:
                exists["last_login"] = previous_last_login
            else:
                exists.pop("last_login", None)
            database.save_raw(exists)


def _open_email_check_form(user, login_page):
    if user.locate(login_page.OWNER_SETUP_FORM).is_visible():
        _ensure_owner_initialized()
        user.page.reload()

    auth_method = user.locate(login_page.AUTH_METHOD_FORM)
    expect(auth_method).to_be_visible()
    auth_method.locator("[data-role='show-email-check']").click()

    email_form = user.locate(login_page.EMAIL_CHECK_FORM)
    expect(email_form).to_be_visible()
    return email_form


def _open_sign_in_form(user, login_page, email):
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(email)
    email_form.locator(Buttons.SIGNIN).click()

    sign_in_form = user.locate(login_page.SIGN_IN_FORM)
    expect(sign_in_form).to_be_visible()
    expect(sign_in_form.locator("input[name='email']")).to_have_value(email)
    return sign_in_form


# @features login
# @dimensions page-load form-state
# @template users/login.html::button
# @template users/login.html::heading
# @template users/login.html::subheading
# @template users/login.html::guidance
# @template users/login.html::success
# @style login.heading
# @style login.subheading
# @style login.guidance
# @style login.error
# @style login.success
# @style form.login
def test_login_page_loads(get_user):
    """
    Verify login page loads with all authentication forms in DOM.

    Tests that the login page renders correctly with all form elements
    attached to the DOM. Forms may be hidden via CSS but must be present
    for the state machine to function.

    Verifies:
        - lagniappe/web/templates/users/login.html: All form sections rendered
        - src/script/views/login.mjs: Form elements have correct IDs

    Forms checked (from testing/resources/site.py LoginPage):
        - OWNER_SETUP_FORM (#ownerSetup)
        - AUTH_METHOD_FORM (#authMethod)
        - EMAIL_CHECK_FORM (#emailCheck)
        - SIGN_IN_FORM (#signIn)
        - FIRST_TIME_SETUP_FORM (#firstTimeSetup)
        - FORGOT_PASSWORD_FORM (#forgotPassword)
        - RESET_PASSWORD_FORM (#resetPassword)
        - VERIFY_EMAIL_FORM (#verifyEmail)

    Note: Uses to_be_attached() not to_be_visible() because forms are
    shown/hidden dynamically based on authentication state.
    """
    user = get_user(Users.ANONYMOUS)
    login_page = user.go(SitePages.LOGIN_PAGE)

    # Verify page has a title (customizable, so just check it exists)
    expect(user.page).not_to_have_title("")

    # Verify all login forms are present in DOM
    expect(user.locate(login_page.OWNER_SETUP_FORM)).to_be_attached()
    expect(user.locate(login_page.AUTH_METHOD_FORM)).to_be_attached()
    expect(user.locate(login_page.EMAIL_CHECK_FORM)).to_be_attached()
    expect(user.locate(login_page.SIGN_IN_FORM)).to_be_attached()
    expect(user.locate(login_page.FIRST_TIME_SETUP_FORM)).to_be_attached()
    expect(user.locate(login_page.FORGOT_PASSWORD_FORM)).to_be_attached()
    expect(user.locate(login_page.RESET_PASSWORD_FORM)).to_be_attached()
    expect(user.locate(login_page.VERIFY_EMAIL_FORM)).to_be_attached()

    action_buttons = user.locate(
        "#ownerSetup button[data-role='signin'], "
        "#emailCheck button[data-role='signin'], "
        "#firstTimeSetup button[data-role='signin'], "
        "#signIn button[data-role='signin'], "
        "#forgotPassword button[data-role='reset-password-email'], "
        "#resetPassword button[data-role='reset-password'], "
        "#verifyEmail button[data-role='signin']"
    )
    expect(action_buttons).to_have_count(7)
    expect(user.locate("#signIn button[data-role='create']")).to_have_count(0)
    for index in range(7):
        button = action_buttons.nth(index)
        expect(button.locator(":scope > [data-role='icon']")).to_have_count(1)
        expect(button.locator(":scope > [data-role='text']")).to_have_count(1)

    workflow_forms = user.locate(
        "#ownerSetup, #authMethod, #emailCheck, #firstTimeSetup, #signIn, "
        "#forgotPassword, #resetPassword, #verifyEmail"
    )
    expect(workflow_forms).to_have_count(8)
    for index in range(8):
        workflow_form = workflow_forms.nth(index)
        expect(workflow_form).to_have_class(re.compile(r".*\bmax-w-md\b.*"))
        expect(workflow_form).to_have_class(re.compile(r".*\brounded-lg\b.*"))
        heading = workflow_form.locator(":scope > h1")
        expect(heading).to_have_count(1)
        expect(heading).to_have_class(re.compile(r".*\btext-2xl\b.*"))

    errors = user.locate("[data-role='error']")
    expect(errors).to_have_count(9)
    for index in range(9):
        error = errors.nth(index)
        expect(error).to_have_class(re.compile(r".*\bbg-delete-bg\b.*"))
        expect(error).to_have_class(re.compile(r".*\bborder-delete-default\b.*"))

    confirmations = user.locate("[data-role='success']")
    expect(confirmations).to_have_count(6)
    for index in range(6):
        confirmation = confirmations.nth(index)
        expect(confirmation).to_have_attribute("data-kind", "user")
        expect(confirmation).to_have_class(re.compile(r".*\bbg-kind-bg\b.*"))
        expect(confirmation).to_have_class(
            re.compile(r".*\bborder-kind-default\b.*")
        )


# @features login
# @dimensions test-user session
def test_user_login_success(get_user):
    """
    Verify test user authentication and home page access.

    Tests the complete authentication flow for Users.OWNER:
    1. get_user() triggers User.login() in conftest.py
    2. login() navigates to /users/login?test_user={email}
    3. Server creates Flask-Login session (bypasses external authentication)
    4. Session stored in Playwright context storage_state
    5. Subsequent requests include session cookie

    Verifies:
        - lagniappe/web/routes/users/login.py: test_user parameter handling
        - Flask-Login session creation works
        - Authenticated user can access protected home page

    Framework usage:
        - Users.OWNER: Authenticated admin user with persisted session
        - SitePages.HOME: Protected route requiring authentication
        - to_have_title("Home"): Confirms successful redirect after auth
    """
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    # Should be on home page with "Home" title (after redirect)
    expect(user.page).to_have_title("Home")


# @features auth
# @dimensions session-user switch invalidation session-keys user-key page-key
# @pair cache:invalidation-acknowledgement
def test_switching_session_user_requests_client_cache_invalidation(get_user):
    owner = get_user(Users.OWNER)
    source = get_user(Users.session_switch_source, creator=owner)
    target = get_user(Users.session_switch_target, creator=owner)
    source.go(SitePages.HOME)

    login_url = _site_url(f"/users/login?test_user={quote(target.email)}")
    with (
        source.page.expect_response(
            lambda response: response.url == login_url and response.status == 302
        ) as login_response,
        source.page.context.expect_event(
            "response",
            predicate=lambda response: (
                response.url.endswith("/l/validate-user")
                and response.request.method == "POST"
            ),
        ) as validation_info,
    ):
        source.page.goto(login_url)

    assert login_response.value.headers.get("x-lagniappe-invalidate-cache") == "True"
    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    expect(source.page).to_have_title("Home")

    payload = _session_serializer().loads(_session_cookie(source.page.context)["value"])
    assert payload[CONFIG.LOGIN_USER_KEY] == target.entity.urlsafe_key
    assert payload[CONFIG.LOGIN_USER_PAGE_KEY] == target.entity.page.urlsafe_key


# @features auth
# @dimensions stale-session fallback clear session-preload session-keys user-key page-key flask-login-skip batch-load
def test_stale_preloaded_session_keys_fall_back_to_flask_login_user(get_user):
    owner = get_user(Users.OWNER)
    stale = get_user(Users.create_user_from_index, creator=owner)
    owner.go(SitePages.HOME)

    serializer = _session_serializer()
    cookie = _session_cookie(owner.page.context)
    payload = serializer.loads(cookie["value"])
    payload[CONFIG.LOGIN_USER_KEY] = stale.entity.urlsafe_key
    payload[CONFIG.LOGIN_USER_PAGE_KEY] = stale.entity.page.urlsafe_key
    payload["restrictions"] = ["stale"]
    payload["belongs_to"] = ["stale"]
    payload["assign"] = ["stale"]
    payload["create_pages"] = ["stale"]
    cookie["value"] = serializer.dumps(payload)
    owner.page.context.add_cookies([cookie])

    owner.page.goto(_site_url("/"))
    expect(owner.page).to_have_title("Home")

    refreshed = serializer.loads(_session_cookie(owner.page.context)["value"])
    assert refreshed[CONFIG.LOGIN_USER_KEY] == owner.entity.urlsafe_key
    assert refreshed[CONFIG.LOGIN_USER_PAGE_KEY] == owner.entity.page.urlsafe_key
    for stale_key in ("restrictions", "belongs_to", "assign", "create_pages"):
        assert stale_key not in refreshed


# @features login
# @dimensions redirect-target
def test_login_returns_to_requested_url_after_redirect(get_user):
    user = get_user(Users.ANONYMOUS)

    user.page.goto(_site_url("/tasks/index"))
    expect(user.page).to_have_url(_site_url("/users/login?next=/tasks/index"))

    email = quote(SETTINGS.test_config["ADMIN_EMAIL"])
    user.page.goto(_site_url(f"/users/login?test_user={email}"))

    expect(user.page).to_have_url(_site_url("/tasks/index"))


# @features login
# @dimensions redirect-target
def test_login_google_buttons_carry_safe_next_state(get_user):
    user = get_user(Users.ANONYMOUS)
    target = "/pages/public-target?from=public#notes"
    user.page.goto(_site_url(f"/users/login?next={quote(target, safe='')}"))

    expect(user.locate("#google-signin-method")).to_have_attribute("data-state", target)
    expect(user.locate("#google-signin-owner")).to_have_attribute("data-state", target)

    user.page.goto(_site_url("/users/login?next=https%3A%2F%2Fevil.example%2Fpage"))
    expect(user.locate("#google-signin-method")).not_to_have_attribute(
        "data-state", re.compile(".+")
    )


# @features login
# @dimensions authentication-email redirect-target
def test_auth_action_url_preserves_safe_login_destination(monkeypatch):
    target = "/tasks/index?from=email#details"
    delivered = {}
    monkeypatch.setattr(CONFIG, "GOOGLE_LOGIN_URI", "https://login.example.test")
    monkeypatch.setattr(auth_email, "check_auth_email_connection", lambda: True)
    monkeypatch.setattr(
        identity_platform,
        "generate_email_action_code",
        lambda *_args, **_kwargs: "code-1",
    )
    monkeypatch.setattr(
        auth_email,
        "send_auth_email",
        lambda recipient, subject, text_body, html_body: delivered.update(
            {
                "recipient": recipient,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
            }
        ),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["next"] = target
    login_response = client.get("/users/login")
    csrf_token = re.search(
        r'id="token" type="hidden" value="([^"]+)"',
        login_response.get_data(as_text=True),
    ).group(1)
    response = client.post(
        "/users/send-password-reset-email",
        json={"email": "reset@example.test"},
        headers={"X-CSRFToken": csrf_token},
        environ_base={"REMOTE_ADDR": f"2001:db8::{uuid4().hex}"},
    )

    assert response.status_code == 200
    action_url = urlsplit(re.search(r"https://\S+", delivered["text_body"]).group())
    assert action_url.scheme == "https"
    assert action_url.netloc == "login.example.test"
    assert action_url.path == "/users/login"
    assert parse_qs(action_url.query) == {
        "mode": ["resetPassword"],
        "oobCode": ["code-1"],
        "next": [target],
    }


# @pair login:google-signin
# @pair csrf:double-submit
# @pair csrf:missing-cookie
# @pair csrf:missing-body
# @pair csrf:mismatch
# @pair csrf:match
def test_google_signin_enforces_double_submit_csrf_before_provider_auth(get_user):
    user = get_user(Users.ANONYMOUS)
    url = _site_url("/users/google-signin")
    api = user.page.context.request

    missing_cookie = api.post(url, form={"g_csrf_token": "body-token"})
    assert_lagniappe_error_response(missing_cookie, status=400)
    assert "No CSRF token in Cookie" in missing_cookie.text()

    user.page.context.add_cookies(
        [{"name": "g_csrf_token", "value": "cookie-token", "url": _site_url("/")}]
    )

    missing_body = api.post(url, form={})
    assert_lagniappe_error_response(missing_body, status=400)
    assert "No CSRF token in post body" in missing_body.text()

    mismatch = api.post(url, form={"g_csrf_token": "different-token"})
    assert_lagniappe_error_response(mismatch, status=400)
    assert "Failed to verify double submit cookie" in mismatch.text()

    matched = api.post(url, form={"g_csrf_token": "cookie-token"})
    assert_lagniappe_error_response(matched, status=400)
    assert "No credential provided" in matched.text()
    cookie_names = {cookie["name"] for cookie in user.page.context.cookies()}
    assert "session" not in cookie_names
    assert "remember_token" not in cookie_names


# @features login
# @dimensions redirect-target
def test_login_accepts_google_state_redirect_target(get_user):
    user = get_user(Users.ANONYMOUS)
    target = "/tasks/index?from=google"
    email = quote(SETTINGS.test_config["ADMIN_EMAIL"])

    user.page.goto(
        _site_url(f"/users/login?test_user={email}&state={quote(target, safe='')}")
    )

    expect(user.page).to_have_url(_site_url(target))


# @features login
# @dimensions agent-access session user-page
# @template users/agent_login.html::agent_login_form
# @style login.heading
def test_agent_access_login_form_creates_session(get_user, browser_failures):
    user = get_user(Users.ANONYMOUS)
    user.page.goto(_site_url("/users/agent-login"))

    heading = user.locate("[data-role='message']")
    expect(heading).to_have_text("Agent access")
    expect(heading).to_have_class(re.compile(r".*\btext-2xl\b.*"))

    agent_button = user.locate("button[data-role='agent-login']")
    expect(agent_button.locator(":scope > [data-role='icon']")).to_have_count(1)
    expect(agent_button.locator(":scope > [data-role='text']")).to_have_count(1)

    user.locate("input[name='code']").fill("wrong-code")
    with browser_failures.expect_http_error(
        user,
        status=401,
        path="/users/agent-login",
    ):
        agent_button.click()
        expect(user.locate("[data-role='error']")).to_have_text("Invalid access code")

    user.locate("input[name='code']").fill(constants.DEFAULT_AGENT_ACCESS_TEST_CODE)
    agent_button.click()

    expect(user.page).to_have_title("Home")
    expect(user.locate("[lp-view]")).to_have_attribute("initialized", "")

    my_page = user.page.get_by_role("link", name="My Page")
    expect(my_page).to_be_visible()

    with user.page.expect_navigation():
        my_page.click()

    expect(user.page).to_have_title(constants.DEFAULT_AGENT_ACCESS_NAME)
    expect(user.locate("[lp-view]")).to_have_attribute("initialized", "")
    expect(user.locate("[data-widget='PageInfo']")).to_have_attribute(
        "initialized",
        "",
    )
    expect(user.locate("[data-widget='UserSettings']")).to_be_attached()


# @features login
# @dimensions owner-bootstrap verify-email password-validation auth-errors
# @template users/login.html::google_signin
# @style login.heading
# @style login.subheading
# @style login.guidance
def test_uninitialized_owner_starts_google_first_setup(get_user, browser_failures):
    """A new owner sees Google first and verifies any separate password."""
    with _owner_waiting_for_first_login():
        user = get_user(Users.ANONYMOUS)
        identity_calls = _mock_identity_platform(
            user.page,
            sign_up_errors=["WEAK_PASSWORD : Password should be at least 6 characters"],
            sign_up_verified=False,
        )
        login_identity_calls = []
        verification_email_calls = []
        _mock_login_identity(
            user.page,
            login_identity_calls,
            {"success": False, "requires_verification": True},
            status=403,
        )
        _mock_verification_email_delivery(user.page, verification_email_calls)

        login_page = user.go(SitePages.LOGIN_PAGE)
        owner_setup = user.locate(login_page.OWNER_SETUP_FORM)
        password_setup = owner_setup.locator(OWNER_PASSWORD_SETUP)

        expect(owner_setup).to_be_visible()
        owner_title = owner_setup.locator("[data-role='owner-setup-title']")
        expect(owner_title).to_have_text("Finish setting up Lagniappe")
        expect(owner_title).to_have_class(re.compile(r".*\btext-2xl\b.*"))
        expect(owner_setup.locator("#google-signin-owner")).to_be_attached()
        expect(password_setup).not_to_be_visible()
        expect(user.locate(login_page.EMAIL_CHECK_FORM)).not_to_be_visible()
        expect(user.locate(login_page.SIGN_IN_FORM)).not_to_be_visible()

        owner_setup.locator("[data-role='show-owner-password']").click()

        expect(password_setup).to_be_visible()
        password_title = password_setup.locator("[data-role='owner-password-title']")
        guidance = password_setup.locator("[data-role='password-guidance']")
        error = password_setup.locator(Roles.ERROR)
        expect(password_title).to_have_class(re.compile(r".*\btext-lg\b.*"))
        expect(guidance).to_contain_text("Do not enter your Google password")
        expect(guidance).to_have_class(re.compile(r".*\btext-sm\b.*"))
        expect(password_setup.locator("input[type='email']")).to_have_count(0)

        password_setup.locator(Buttons.SIGNIN).click()
        expect(error).to_be_visible()
        expect(error).to_have_text("Please choose a password")
        assert identity_calls["sign_up"] == []

        password_setup.locator(PASSWORD).fill("short")
        with browser_failures.expect_http_error(
            user,
            status=400,
            path="/v1/accounts:signUp",
        ):
            password_setup.locator(Buttons.SIGNIN).click()
            expect(error).to_be_visible()
            expect(error).to_have_text("Password must be at least 6 characters long.")
            expect(error).not_to_contain_text("WEAK_PASSWORD")

        password_setup.locator(PASSWORD).fill("separate-owner-password")

        with browser_failures.expect_http_error(
            user,
            status=403,
            path="/users/login-identity",
        ):
            password_setup.locator(Buttons.SIGNIN).click()
            expect(password_setup.locator("[data-role='success']")).to_have_text(
                "We've sent a verification link to the application owner email on file."
            )
            expect(password_setup.locator(PASSWORD)).not_to_be_visible()
            expect(password_setup.locator(Buttons.SIGNIN)).not_to_be_visible()

        owner_email = SETTINGS.test_config["ADMIN_EMAIL"]
        assert identity_calls["sign_up"][1]["email"] == owner_email
        assert identity_calls["sign_up"][1]["password"] == "separate-owner-password"
        assert login_identity_calls[0]["email"] == owner_email
        assert verification_email_calls == [
            {"idToken": login_identity_calls[0]["authResult"]}
        ]
        assert not identity_calls["unexpected"]


# @features login
# @dimensions auth-method google-oauth email-signin
def test_login_defaults_to_auth_method_form(get_user):
    """
    Verify ordinary login starts with a Google-or-email method choice.

    No password field is shown beside Google sign-in. Choosing email advances
    to an email-only screen.
    """
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    login_page = user.go(SitePages.LOGIN_PAGE)

    auth_method = user.locate(login_page.AUTH_METHOD_FORM)
    expect(auth_method).to_be_visible()
    expect(auth_method.locator("#google-signin-method")).to_be_attached()
    expect(auth_method.locator(PASSWORD)).to_have_count(0)
    expect(user.locate(login_page.SIGN_IN_FORM)).not_to_be_visible()

    auth_method.locator("[data-role='show-email-check']").click()
    email_form = user.locate(login_page.EMAIL_CHECK_FORM)
    expect(email_form).to_be_visible()
    expect(email_form.locator(PASSWORD)).to_have_count(0)
    expect(email_form.locator(".g_id_signin")).to_have_count(0)


# @features login
# @dimensions google-oauth authorization-error auth-method
def test_unregistered_google_error_returns_to_method_chooser(get_user):
    """A verified but unprovisioned Google account gets a useful login error."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    login_page = user.go(
        SitePages.LOGIN_PAGE,
        query_params={"authError": "google-not-registered"},
    )

    auth_method = user.locate(login_page.AUTH_METHOD_FORM)
    expect(auth_method).to_be_visible()
    expect(auth_method.locator(Roles.ERROR)).to_have_text(
        "That Google account does not have access to this site. "
        "Contact the site owner if you think this is a mistake."
    )
    expect(auth_method.locator(PASSWORD)).to_have_count(0)


# @features login
# @dimensions google-oauth disabled-account auth-method safe-error
def test_disabled_google_error_returns_to_method_chooser(get_user):
    """A disabled Identity Platform account gets a useful, provider-safe error."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    login_page = user.go(
        SitePages.LOGIN_PAGE,
        query_params={"authError": "google-user-disabled"},
    )

    auth_method = user.locate(login_page.AUTH_METHOD_FORM)
    expect(auth_method).to_be_visible()
    error = auth_method.locator(Roles.ERROR)
    expect(error).to_have_text(
        "This account is disabled and cannot sign in. "
        "Contact the site owner if you think this is a mistake."
    )
    expect(error).not_to_contain_text("USER_DISABLED")
    expect(auth_method.locator(PASSWORD)).to_have_count(0)


# @features login
# @dimensions google-oauth disabled-provider auth-method
# @template users/login.html::google_signin
def test_login_hides_google_when_provider_is_disabled(monkeypatch):
    """Production login omits Google controls when the live provider is off."""
    _ensure_owner_initialized()
    monkeypatch.setattr(CONFIG, "ENV", Environment.PRODUCTION)
    monkeypatch.setattr(
        identity_platform,
        "google_provider_enabled",
        lambda: False,
    )

    response = app.test_client().get("/users/login")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "google-signin-method" not in html
    assert "google-signin-owner" not in html
    assert "accounts.google.com/gsi/client" not in html
    assert 'data-role="show-email-check"' in html

    with _owner_waiting_for_first_login():
        owner_response = app.test_client().get("/users/login")
    owner_html = owner_response.get_data(as_text=True)
    password_setup_class = re.search(
        r'data-role="owner-password-setup"\s+class="([^"]*)"',
        owner_html,
    )

    assert owner_response.status_code == 200
    assert "google-signin-owner" not in owner_html
    assert password_setup_class is not None
    assert "hidden" not in password_setup_class.group(1).split()
    assert 'data-role="back-to-owner-google"' not in owner_html


# @features login
# @dimensions google-oauth disabled-provider operator-intent auth-method
def test_google_signin_setting_disables_ui_and_callback(monkeypatch):
    """The persisted opt-out hides Google and rejects direct callback posts."""
    _ensure_owner_initialized()
    monkeypatch.setattr(CONFIG, "ENV", Environment.PRODUCTION)
    monkeypatch.setattr(CONFIG, "GOOGLE_SIGNIN_ENABLED", False)
    monkeypatch.setattr(
        identity_platform,
        "google_provider_enabled",
        lambda: pytest.fail("disabled intent must skip live provider lookup"),
    )

    response = app.test_client().get("/users/login")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "google-signin-method" not in html
    assert "accounts.google.com/gsi/client" not in html
    assert 'data-role="show-email-check"' in html

    client = app.test_client()
    client.set_cookie("g_csrf_token", "csrf-token")
    callback = client.post(
        "/users/google-signin",
        data={
            "credential": "unused-google-credential",
            "g_csrf_token": "csrf-token",
            "state": "/tasks/index?from=google",
        },
    )
    location = urlsplit(callback.headers["Location"])

    assert callback.status_code == 302
    assert location.path == "/users/login"
    assert parse_qs(location.query) == {
        "next": ["/tasks/index?from=google"],
    }


@pytest.mark.parametrize(
    ("provider_code", "expected_auth_error"),
    [
        ("USER_DISABLED", "google-user-disabled"),
        ("OPERATION_NOT_ALLOWED", None),
    ],
)
# @features login
# @dimensions google-oauth disabled-account disabled-provider safe-error redirect-target
def test_google_provider_rejections_return_safely(
    monkeypatch,
    provider_code,
    expected_auth_error,
):
    """Known provider rejections return to login without a raw error page."""
    _ensure_owner_initialized()
    monkeypatch.setattr(
        identity_platform,
        "verify_google_credential",
        lambda *_args, **_kwargs: {
            "sub": "google-user-1",
            "email": CONFIG.ADMIN_EMAIL,
            "email_verified": True,
        },
    )

    def reject_exchange(*_args, **_kwargs):
        raise identity_platform.IdentityPlatformError(
            "provider rejected credential",
            provider_code=provider_code,
        )

    monkeypatch.setattr(
        identity_platform,
        "exchange_google_credential",
        reject_exchange,
    )
    client = app.test_client()
    client.set_cookie("g_csrf_token", "csrf-token")

    response = client.post(
        "/users/google-signin",
        data={
            "credential": "google-credential",
            "g_csrf_token": "csrf-token",
            "state": "/tasks/index?from=google",
        },
    )
    location = urlsplit(response.headers["Location"])
    query = parse_qs(location.query)

    assert response.status_code == 302
    assert location.path == "/users/login"
    assert query["next"] == ["/tasks/index?from=google"]
    if expected_auth_error:
        assert query["authError"] == [expected_auth_error]
    else:
        assert "authError" not in query
    assert provider_code not in response.headers["Location"]


# @features login
# @dimensions account-enumeration sign-in-transition
def test_unknown_email_transitions_to_sign_in_without_leaking_existence(
    get_user,
    browser_failures,
):
    """
    Verify unknown emails no longer show an explicit account-not-found error.

    The compatibility endpoint now returns a generic next step, so the user
    should land on the sign-in form instead of seeing an existence leak.
    """
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    _mock_identity_platform(user.page, sign_in_errors=["EMAIL_NOT_FOUND"])
    login_page = user.go(SitePages.LOGIN_PAGE)
    email = "nonexistent@test.com"
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(email)
    email_form.locator(Buttons.SIGNIN).click()

    sign_in_form = user.locate(login_page.SIGN_IN_FORM)
    expect(sign_in_form).to_be_visible()
    expect(sign_in_form.locator("[data-role='selected-email']")).to_have_text(email)
    expect(sign_in_form.locator("input[type='email']")).to_have_count(0)
    expect(sign_in_form.locator(".g_id_signin")).to_have_count(0)
    expect(email_form.locator(Roles.ERROR)).not_to_be_visible()

    sign_in_form.locator(PASSWORD).fill("not-a-real-password")
    with browser_failures.expect_http_error(
        user,
        status=400,
        path="/v1/accounts:signInWithPassword",
    ):
        sign_in_form.locator(Buttons.SIGNIN).click()
        expect(sign_in_form.locator(Roles.ERROR)).to_have_text(
            "Incorrect email or password."
        )


# @features login
# @dimensions account-enumeration endpoint
def test_check_user_status_endpoint_does_not_enumerate_accounts(get_user):
    """Unknown accounts should receive the generic sign-in next step."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    email = f"unknown-{uuid4().hex}@example.test"
    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(email)

    with expect_successful_response(
        user.page,
        method="GET",
        path="/users/check-user-status",
        query={"email": email},
    ) as response_info:
        email_form.locator(Buttons.SIGNIN).click()

    response = response_info.value
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"success": True, "next": "signin"}
    expect(user.locate(login_page.SIGN_IN_FORM)).to_be_visible()


# @features login
# @dimensions first-time-setup endpoint
def test_check_user_status_endpoint_returns_first_time_setup(get_user):
    """Provisioned users without a prior login should get first-time setup."""
    from lagniappe.core.entities import Entities

    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    email = f"first-time-{uuid4().hex}@example.test"
    provisioned_user = Entities.USER.create(
        {
            "email": email,
            "name": "First Time User",
            "groups": [],
            "test_user": True,
        }
    )
    provisioned_user.save()

    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(email)

    with expect_successful_response(
        user.page,
        method="GET",
        path="/users/check-user-status",
        query={"email": email},
    ) as response_info:
        email_form.locator(Buttons.SIGNIN).click()

    response = response_info.value
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"success": True, "next": "first_time_setup"}
    expect(user.locate(login_page.FIRST_TIME_SETUP_FORM)).to_be_visible()


# @features login
# @dimensions reset-password query-mode action-code-validation expired-link
def test_reset_password_mode(get_user, browser_failures):
    """
    Verify reset password form displays with correct query parameters.

    Tests that navigating with ?mode=resetPassword&oobCode=xxx shows
    the password reset form. The oobCode is a Identity Platform one-time code
    from the reset email link.

    Verifies:
        - lagniappe/web/templates/users/login.html: Reset form visibility logic
        - src/script/views/login.mjs: Query parameter parsing for mode
        - Reset form has new-password input field

    Framework usage:
        - user.go() with query_params: Appends URL parameters
        - RESET_PASSWORD_FORM (#resetPassword): Password reset form selector
    """
    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(
        user.page,
        reset_password_errors=[None, None, "INVALID_OOB_CODE"],
    )
    params = {"mode": "resetPassword", "oobCode": "test123"}
    login_page = user.go(SitePages.LOGIN_PAGE, query_params=params)

    reset_form = user.locate(login_page.RESET_PASSWORD_FORM)
    expect(reset_form).to_be_visible()
    expect(reset_form.locator('input[name="new-password"]')).to_be_visible()
    expect(reset_form.locator(RESET_PASSWORD)).to_be_enabled()
    assert identity_calls["reset_password"] == [{"oobCode": "test123"}]

    reset_form.locator('input[name="new-password"]').fill("new-password-123")
    reset_form.locator(RESET_PASSWORD).click()
    sign_in_form = user.locate(login_page.SIGN_IN_FORM)
    expect(sign_in_form).to_be_visible()
    expect(sign_in_form.locator("input[name='email']")).to_have_value(
        "reset-user@example.test"
    )
    expect(sign_in_form.locator("[data-role='success']")).to_have_text(
        "Password updated successfully. Please sign in with your new password."
    )

    with browser_failures.expect_http_error(
        user,
        status=400,
        path="/v1/accounts:resetPassword",
    ):
        user.go(
            SitePages.LOGIN_PAGE,
            query_params={"mode": "resetPassword", "oobCode": "used-code"},
        )
        reset_form = user.locate(login_page.RESET_PASSWORD_FORM)
        expect(reset_form).to_be_visible()
        expect(reset_form.locator(Roles.ERROR)).to_have_text(
            "This link is invalid or expired. Please request a new one."
        )
        expect(reset_form.locator('input[name="new-password"]')).not_to_be_visible()
        expect(reset_form.locator(RESET_PASSWORD)).not_to_be_visible()
        expect(reset_form.locator(REQUEST_NEW_RESET_LINK)).to_be_visible()

    reset_form.locator(REQUEST_NEW_RESET_LINK).click()
    forgot_form = user.locate(login_page.FORGOT_PASSWORD_FORM)
    expect(forgot_form).to_be_visible()
    expect(forgot_form.locator('input[name="reset-email"]')).to_be_visible()

    assert identity_calls["reset_password"] == [
        {"oobCode": "test123"},
        {"oobCode": "test123", "newPassword": "new-password-123"},
        {"oobCode": "used-code"},
    ]
    assert not identity_calls["unexpected"]


# @features login
# @dimensions verify-email query-mode
def test_verify_email_mode(get_user):
    """
    Verify email verification form displays with correct query parameters.

    Tests that navigating with ?mode=verifyEmail&oobCode=xxx shows
    the email verification confirmation form. This is the landing page
    from Identity Platform email verification links.

    Verifies:
        - lagniappe/web/templates/users/login.html: Verify form visibility logic
        - src/script/views/login.mjs: Query parameter parsing for mode

    Framework usage:
        - VERIFY_EMAIL_FORM (#verifyEmail): Email verification form selector
    """
    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(user.page)
    params = {"mode": "verifyEmail", "oobCode": "test123"}
    login_page = user.go(SitePages.LOGIN_PAGE, query_params=params)

    verify_form = user.locate(login_page.VERIFY_EMAIL_FORM)
    expect(verify_form).to_be_visible()
    expect(verify_form.locator("[data-role='success']")).to_have_text(
        "Email verified successfully"
    )
    expect(verify_form.locator(Buttons.SIGNIN)).to_be_enabled()
    assert identity_calls["update"] == [{"oobCode": "test123"}]
    assert not identity_calls["unexpected"]


# @features login
# @dimensions email-validation
def test_email_input_validation(get_user):
    """
    Verify HTML5 email validation prevents invalid submissions.

    Tests that the email input field uses HTML5 validation (type='email')
    to prevent form submission with invalid email formats.

    Verifies:
        - lagniappe/web/templates/users/login.html: input[type='email'] attribute
        - Browser HTML5 validation behavior

    Note: Exact validation behavior varies by browser (Chromium shows tooltip,
    prevents submission). Test confirms form stays visible after invalid submit.
    """
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    login_page = user.go(SitePages.LOGIN_PAGE)

    email_form = _open_email_check_form(user, login_page)
    email_input = email_form.locator(FormElements.EMAIL)
    expect(email_input).to_be_visible()

    # Test that it requires email format (HTML5 validation)
    email_input.fill("invalid-email")
    submit_button = email_form.locator(Buttons.SIGNIN)
    submit_button.click()

    # HTML5 validation should prevent submission
    # The exact behavior varies by browser, so just check form is still visible
    expect(email_form).to_be_visible()


# @features login
# @dimensions responsive-layout
def test_login_responsive_design(get_user):
    """
    Verify login page displays correctly across device sizes.

    Tests responsive design by resizing viewport to common device
    dimensions and confirming the email form remains visible.

    Verifies:
        - lagniappe/web/templates/users/login.html: Responsive CSS
        - Form layout adapts to viewport without breaking

    Viewport sizes tested:
        - Mobile: 375x667 (iPhone SE)
        - Tablet: 768x1024 (iPad)
        - Desktop: 1280x720 (standard laptop)

    Framework usage:
        - user.page.set_viewport_size(): Playwright viewport control
    """
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    login_page = user.go(SitePages.LOGIN_PAGE)
    login_form = user.locate(login_page.AUTH_METHOD_FORM)

    # Test mobile size
    user.page.set_viewport_size({"width": 375, "height": 667})
    expect(login_form).to_be_visible()

    # Test tablet size
    user.page.set_viewport_size({"width": 768, "height": 1024})
    expect(login_form).to_be_visible()

    # Test desktop size
    user.page.set_viewport_size({"width": 1280, "height": 720})
    expect(login_form).to_be_visible()


# @pair error-handling:csrf
def test_csrf_failure_is_identified_for_targeted_retry(get_user, browser_failures):
    """Only Flask-WTF CSRF failures should trigger the frontend retry path."""
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    with browser_failures.expect_http_error(
        user,
        status=400,
        path="/users/logout",
    ):
        response = user.page.evaluate(
            """async () => {
                const response = await fetch("/users/logout", {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": "stale-token",
                        "X-Lagniappe-Request": "true",
                    },
                    body: JSON.stringify({}),
                });
                return {
                    status: response.status,
                    csrf: response.headers.get("X-Lagniappe-CSRF"),
                    body: await response.text(),
                };
            }"""
        )

    assert response["status"] == 400
    assert response["csrf"] == "invalid"
    assert response["body"]


# @features login
# @dimensions logout session redirect session-keys clear
# @pair cache:invalidation-acknowledgement
# @style login.heading
def test_logout_clears_session_and_returns_login(get_user):
    """
    Authenticated users visiting /users/login see logged-in shell; POST logout
    redirects to login again; protected routes redirect anonymous users to login.

    Verifies:
        - lagniappe/web/routes/users/login.py: logged_in.html vs login.html
        - users.logout: POST clears Flask-Login session and redirects to login
        - lagniappe/web/start/errors.py: 401 → redirect to login
    """
    owner = get_user(Users.OWNER)
    user = get_user(Users.logout_navigation, creator=owner)
    home = SitePages.HOME.get(user)
    login_page = user.go(SitePages.LOGIN_PAGE)

    expect(user.page).to_have_title("Logged In")
    expect(user.page.get_by_role("heading", name="You are logged in")).to_have_class(
        re.compile(r".*\btext-2xl\b.*")
    )
    logout = user.page.get_by_role("button", name="Logout")
    expect(logout).to_be_visible()

    with user.page.expect_navigation():
        logout.click()

    expect(user.page).to_have_title("Login")
    expect(user.locate(login_page.AUTH_METHOD_FORM)).to_be_visible()

    user.navigate(home.url)
    expect(user.page).to_have_title("Login")

    login_url = _site_url(f"/users/login?test_user={quote(user.email)}")
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        user.page.goto(login_url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(user.email).invalidate_cache is False
    expect(user.page).to_have_title("Home")


# @features login
# @dimensions logout invalidation control redirect
# @pair cache:invalidation-acknowledgement
def test_logout_flags_user_cache_invalidation(get_user):
    """The logout control should expose invalidation and navigate to login."""
    owner = get_user(Users.OWNER)
    user = get_user(Users.logout_ajax, creator=owner)
    user.go(SitePages.LOGIN_PAGE)
    logout = user.page.get_by_role("button", name="Logout")
    expect(logout).to_be_visible()

    with (
        user.page.expect_response(
            lambda response: (
                response.url.endswith("/users/logout")
                and response.request.method == "POST"
            )
        ) as logout_info,
        user.page.expect_navigation(),
    ):
        logout.click()

    response = logout_info.value
    assert response.status == 200
    assert response.headers["x-lagniappe-invalidate-cache"] == "True"

    saved_user = Entities.USER.load(user.email)
    assert saved_user.invalidate_cache is True

    expect(user.page).to_have_title("Login")
    login_url = _site_url(f"/users/login?test_user={quote(user.email)}")
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        user.page.goto(login_url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(user.email).invalidate_cache is False
    expect(user.page).to_have_title("Home")


# @features login
# @dimensions cookie-hardening remember-cookie
def test_login_sets_hardened_auth_cookies(get_user):
    """Test login should issue hardened session and remember-me cookies."""
    owner = get_user(Users.OWNER)
    user = get_user(Users.ANONYMOUS)
    login_page = SitePages.LOGIN_PAGE.get(user)
    login_url = login_page.login_url(owner.email)

    with user.page.expect_response(
        lambda response: response.url == login_url and response.status == 302
    ) as response_info:
        user.page.goto(login_url)

    response = response_info.value
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["location"] == "/"
    set_cookies = _set_cookie_headers(response)
    session_cookie = next(
        cookie for cookie in set_cookies if cookie.startswith("session=")
    )
    remember_cookie = next(
        cookie for cookie in set_cookies if cookie.startswith("remember_token=")
    )

    for cookie in [session_cookie, remember_cookie]:
        assert "Secure" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie

    stored_cookies = {cookie["name"]: cookie for cookie in user.page.context.cookies()}
    for name in ("session", "remember_token"):
        assert stored_cookies[name]["secure"] is True
        assert stored_cookies[name]["httpOnly"] is True
        assert stored_cookies[name]["sameSite"] == "Lax"

    expect(user.page).to_have_title("Home")


# @features login
# @dimensions email-check sign-in-transition
def test_known_registered_email_shows_sign_in(get_user):
    """
    check-user-status returns ``signin`` for existing users who have logged in
    before (OWNER); UI should show the password sign-in form.
    """
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(SETTINGS.test_config["ADMIN_EMAIL"])
    email_form.locator(Buttons.SIGNIN).click()

    expect(user.locate(login_page.SIGN_IN_FORM)).to_be_visible()


# @features login
# @dimensions forgot-password sign-in-transition
# @template users/login.html::success
# @style login.success
def test_forgot_password_form_opens_from_sign_in(get_user):
    """Forgot-password delivery replaces its inputs with confirmation feedback."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    reset_email_calls = []
    _mock_password_reset_email_delivery(user.page, reset_email_calls)
    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(SETTINGS.test_config["ADMIN_EMAIL"])
    email_form.locator(Buttons.SIGNIN).click()

    expect(user.locate(login_page.SIGN_IN_FORM)).to_be_visible()
    user.locate(login_page.SIGN_IN_FORGOT_PASSWORD).click()

    expect(user.locate(login_page.FORGOT_PASSWORD_FORM)).to_be_visible()
    expect(
        user.locate(login_page.FORGOT_PASSWORD_FORM).locator(
            'input[name="reset-email"]'
        )
    ).to_be_visible()

    forgot_form = user.locate(login_page.FORGOT_PASSWORD_FORM)
    forgot_form.locator("button[data-role='reset-password-email']").click()

    expect(forgot_form.locator("[data-role='success']")).to_have_text(
        "A password reset link has been sent to your email address."
    )
    expect(forgot_form.locator('input[name="reset-email"]')).not_to_be_visible()
    expect(
        forgot_form.locator("button[data-role='reset-password-email']")
    ).not_to_be_visible()
    assert reset_email_calls == [{"email": SETTINGS.test_config["ADMIN_EMAIL"]}]


# @features login
# @dimensions forgot-password delivery-failure recovery safe-error
def test_password_reset_delivery_failure_recovers_safely(
    get_user,
    browser_failures,
):
    """Unavailable reset delivery is safe, visible, and retryable in place."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    reset_email_calls = []
    _mock_password_reset_email_delivery(
        user.page,
        reset_email_calls,
        failures=[True],
    )
    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(SETTINGS.test_config["ADMIN_EMAIL"])
    email_form.locator(Buttons.SIGNIN).click()
    user.locate(login_page.SIGN_IN_FORGOT_PASSWORD).click()
    forgot_form = user.locate(login_page.FORGOT_PASSWORD_FORM)
    reset_button = forgot_form.locator("button[data-role='reset-password-email']")

    with browser_failures.expect_http_error(
        user,
        status=503,
        path="/users/send-password-reset-email",
    ):
        reset_button.click()
        error = forgot_form.locator(Roles.ERROR)
        expect(error).to_have_text(
            "We couldn't send the password reset email. Please try again later."
        )
        expect(error).not_to_contain_text("private provider detail")
        expect(forgot_form.locator('input[name="reset-email"]')).to_have_value(
            SETTINGS.test_config["ADMIN_EMAIL"]
        )
        expect(reset_button).to_be_visible()

    reset_button.click()
    expect(forgot_form.locator("[data-role='success']")).to_have_text(
        "A password reset link has been sent to your email address."
    )
    expect(forgot_form.locator('input[name="reset-email"]')).not_to_be_visible()
    expect(reset_button).not_to_be_visible()
    assert reset_email_calls == [
        {"email": SETTINGS.test_config["ADMIN_EMAIL"]},
        {"email": SETTINGS.test_config["ADMIN_EMAIL"]},
    ]


# @features login
# @dimensions identity-platform rate-limit
def test_login_identity_returns_rate_limit_response(get_user, browser_failures):
    """The live Identity Platform login route should propagate limiter 429 responses."""
    user = get_user(Users.ANONYMOUS)
    user.go(SitePages.LOGIN_PAGE)
    csrf_token = user.locate("#token").input_value()

    limited = None
    with browser_failures.expect_http_error(
        user,
        status=429,
        path="/users/login-identity",
    ):
        with browser_failures.expect_http_error(
            user,
            status=401,
            path="/users/login-identity",
            count=20,
        ):
            for _ in range(25):
                response = user.page.evaluate(
                    """async ({ csrfToken, authResult }) => {
                        const response = await fetch("/users/login-identity", {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json",
                                "X-CSRFToken": csrfToken,
                            },
                            body: JSON.stringify({ authResult }),
                        });
                        return {
                            status: response.status,
                            retryAfter: response.headers.get("Retry-After"),
                            json: await response.json(),
                        };
                    }""",
                    {
                        "csrfToken": csrf_token,
                        "authResult": f"invalid-token-{uuid4().hex}",
                    },
                )
                if response["status"] == 429:
                    limited = response
                    break
                assert response["status"] == 401

    assert limited is not None
    assert limited["retryAfter"] is not None
    assert limited["json"]["success"] is False


# @features login
# @dimensions remember-preference
def test_login_remember_preference_syncs_across_forms(get_user):
    """Changing remember-me in one login form updates later remember forms."""
    user = get_user(Users.ANONYMOUS)
    _mock_identity_platform(user.page)
    first_time_email = f"remember-first-time-{uuid4().hex}@example.test"
    _create_first_time_user(first_time_email)

    login_page = user.go(SitePages.LOGIN_PAGE)
    sign_in_form = _open_sign_in_form(
        user, login_page, SETTINGS.test_config["ADMIN_EMAIL"]
    )
    remember = sign_in_form.locator(REMEMBER_ME)

    expect(remember).to_be_checked()
    remember.uncheck()
    expect(remember).not_to_be_checked()
    user.page.wait_for_function(
        "() => document.cookie.includes('lagniappe_remember=0')"
    )

    user.locate(login_page.SIGN_IN_FORGOT_PASSWORD).click()
    expect(user.locate(login_page.FORGOT_PASSWORD_FORM)).to_be_visible()
    user.locate(f"{login_page.FORGOT_PASSWORD_FORM} {FORGOT_BACK}").click()

    expect(user.locate(login_page.SIGN_IN_FORM)).to_be_visible()
    expect(sign_in_form.locator(REMEMBER_ME)).not_to_be_checked()

    user.go(
        SitePages.LOGIN_PAGE,
        query_params={"mode": "verifyEmail", "oobCode": "remember-code"},
    )
    verify_form = user.locate(login_page.VERIFY_EMAIL_FORM)
    verify_remember = verify_form.locator(REMEMBER_ME)

    expect(verify_form).to_be_visible()
    expect(verify_remember).not_to_be_checked()

    verify_remember.check()
    user.page.wait_for_function(
        "() => document.cookie.includes('lagniappe_remember=1')"
    )
    user.locate(VERIFY_FORGOT_PASSWORD).click()
    expect(user.locate(login_page.FORGOT_PASSWORD_FORM)).to_be_visible()
    user.locate(f"{login_page.FORGOT_PASSWORD_FORM} {FORGOT_BACK}").click()

    expect(user.locate(login_page.SIGN_IN_FORM).locator(REMEMBER_ME)).to_be_checked()

    user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(first_time_email)
    email_form.locator(Buttons.SIGNIN).click()

    first_time_form = user.locate(login_page.FIRST_TIME_SETUP_FORM)
    expect(first_time_form).to_be_visible()
    expect(first_time_form.locator(REMEMBER_ME)).to_have_count(0)
    assert "lagniappe_remember=1" in user.page.evaluate("document.cookie")


# @features login
# @dimensions first-time-setup account-create form-state
def test_first_time_setup_form_creates_password_and_can_return_to_email_check(
    get_user,
    browser_failures,
):
    """Provisioned users can back out, then create a password for verification."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(user.page, sign_up_verified=False)
    login_identity_calls = []
    verification_email_calls = []
    email = f"first-time-password-{uuid4().hex}@example.test"
    password = "new-password-123"
    _create_first_time_user(email)
    _mock_login_identity(
        user.page,
        login_identity_calls,
        {"success": False, "requires_verification": True},
        status=403,
    )
    _mock_verification_email_delivery(user.page, verification_email_calls)

    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(email)
    email_form.locator(Buttons.SIGNIN).click()

    first_time_form = user.locate(login_page.FIRST_TIME_SETUP_FORM)
    expect(first_time_form).to_be_visible()
    selected_email = first_time_form.locator("[data-role='selected-email']")
    guidance = first_time_form.locator("[data-role='password-guidance']")
    expect(selected_email).to_have_text(email)
    expect(selected_email).to_have_class(re.compile(r".*\btext-lg\b.*"))
    expect(guidance).to_have_class(re.compile(r".*\btext-sm\b.*"))
    expect(first_time_form.locator("input[type='email']")).to_have_count(0)
    expect(first_time_form.locator(".g_id_signin")).to_have_count(0)

    first_time_form.locator(FIRST_TIME_BACK).click()
    expect(user.locate(login_page.EMAIL_CHECK_FORM)).to_be_visible()

    email_form.locator(FormElements.EMAIL).fill(email)
    email_form.locator(Buttons.SIGNIN).click()
    expect(first_time_form).to_be_visible()

    first_time_form.locator(PASSWORD).fill(password)
    with browser_failures.expect_http_error(
        user,
        status=403,
        path="/users/login-identity",
    ):
        first_time_form.locator(Buttons.SIGNIN).click()
        expect(first_time_form.locator("[data-role='success']")).to_have_text(
            f"An email verification link has been sent to {email}."
        )
        expect(first_time_form.locator(PASSWORD)).not_to_be_visible()
        expect(first_time_form.locator(Buttons.SIGNIN)).not_to_be_visible()

    assert identity_calls["sign_up"][0]["email"] == email
    assert identity_calls["sign_up"][0]["password"] == password
    assert login_identity_calls[0]["email"] == email
    assert login_identity_calls[0]["authResult"]
    assert verification_email_calls == [
        {"idToken": login_identity_calls[0]["authResult"]}
    ]
    assert not identity_calls["unexpected"]


# @features login
# @dimensions identity-platform redirect verify-email remember-preference
def test_login_identity_client_handoff_redirects_or_requires_verification(
    get_user,
    browser_failures,
):
    """Identity Platform sign-in posts the handoff payload and handles both outcomes."""
    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(user.page)
    login_identity_calls = []
    email = f"identity-success-{uuid4().hex}@example.test"

    _mock_login_identity(
        user.page,
        login_identity_calls,
        {"success": True, "redirect": "/testing-login-success"},
    )
    _mock_document(user.page, "/testing-login-success", "Login Complete")

    login_page = user.go(SitePages.LOGIN_PAGE)
    sign_in_form = _open_sign_in_form(user, login_page, email)
    sign_in_form.locator(REMEMBER_ME).uncheck()
    sign_in_form.locator(PASSWORD).fill("valid-password")
    sign_in_form.locator(Buttons.SIGNIN).click()

    expect(user.page).to_have_url(_site_url("/testing-login-success"))
    expect(user.page).to_have_title("Login Complete")

    assert identity_calls["sign_in"][0]["email"] == email
    assert identity_calls["sign_in"][0]["password"] == "valid-password"
    assert login_identity_calls[0]["email"] == email
    assert login_identity_calls[0]["remember"] is False
    assert login_identity_calls[0]["authResult"]
    assert not identity_calls["unexpected"]


    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(user.page, sign_in_verified=False)
    login_identity_calls = []
    verification_email_calls = []
    email = f"identity-verify-{uuid4().hex}@example.test"
    _mock_login_identity(
        user.page,
        login_identity_calls,
        {"success": False, "requires_verification": True},
        status=403,
    )
    _mock_verification_email_delivery(user.page, verification_email_calls)

    login_page = user.go(SitePages.LOGIN_PAGE)
    sign_in_form = _open_sign_in_form(user, login_page, email)
    sign_in_form.locator(PASSWORD).fill("valid-password")
    with browser_failures.expect_http_error(
        user,
        status=403,
        path="/users/login-identity",
    ):
        sign_in_form.locator(Buttons.SIGNIN).click()

        success = sign_in_form.locator("[data-role='success']")
        expect(success).to_be_visible()
        expect(success).to_contain_text(
            f"An email verification link has been sent to {email}."
        )
        expect(sign_in_form.locator(PASSWORD)).not_to_be_visible()
        expect(sign_in_form.locator(Buttons.SIGNIN)).not_to_be_visible()

    assert login_identity_calls[0]["email"] == email
    assert login_identity_calls[0]["remember"] is True
    assert verification_email_calls == [
        {"idToken": login_identity_calls[0]["authResult"]}
    ]
    assert not identity_calls["unexpected"]

    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(user.page)
    login_identity_calls = []
    email = f"identity-error-{uuid4().hex}@example.test"
    _mock_login_identity(
        user.page,
        login_identity_calls,
        {"success": False, "error": "Incorrect email or password."},
        status=401,
    )

    login_page = user.go(SitePages.LOGIN_PAGE)
    sign_in_form = _open_sign_in_form(user, login_page, email)
    sign_in_form.locator(PASSWORD).fill("valid-password")
    with browser_failures.expect_http_error(
        user,
        status=401,
        path="/users/login-identity",
    ):
        sign_in_form.locator(Buttons.SIGNIN).click()

        error = sign_in_form.locator(Roles.ERROR)
        expect(error).to_be_visible()
        expect(error).to_contain_text("Incorrect email or password.")

    assert login_identity_calls[0]["email"] == email
    assert identity_calls["sign_in"][0]["email"] == email
    assert not identity_calls["unexpected"]


# @features login
# @dimensions identity-platform verify-email delivery-failure recovery safe-error
def test_verification_delivery_failure_recovers_safely(
    get_user,
    browser_failures,
):
    """A failed verification email is visible and can be retried by signing in."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(
        user.page,
        sign_up_verified=False,
        sign_in_verified=False,
    )
    login_identity_calls = []
    verification_email_calls = []
    email = f"verification-delivery-{uuid4().hex}@example.test"
    password = "new-password-123"
    _create_first_time_user(email)
    _mock_login_identity(
        user.page,
        login_identity_calls,
        {"success": False, "requires_verification": True},
        status=403,
    )
    _mock_verification_email_delivery(
        user.page,
        verification_email_calls,
        failures=[True],
    )

    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(email)
    email_form.locator(Buttons.SIGNIN).click()
    first_time_form = user.locate(login_page.FIRST_TIME_SETUP_FORM)
    expect(first_time_form).to_be_visible()
    first_time_form.locator(PASSWORD).fill(password)

    with browser_failures.expect_http_error(
        user,
        status=503,
        path="/users/send-verification-email",
    ):
        with browser_failures.expect_http_error(
            user,
            status=403,
            path="/users/login-identity",
        ):
            first_time_form.locator(Buttons.SIGNIN).click()
            sign_in_form = user.locate(login_page.SIGN_IN_FORM)
            expect(sign_in_form).to_be_visible()
            error = sign_in_form.locator(Roles.ERROR)
            expect(error).to_have_text(
                "We couldn't send the verification email. "
                "Sign in again to retry delivery."
            )
            expect(error).not_to_contain_text("private provider detail")
            expect(sign_in_form.locator("input[name='email']")).to_have_value(email)

    sign_in_form.locator(PASSWORD).fill(password)
    with browser_failures.expect_http_error(
        user,
        status=403,
        path="/users/login-identity",
    ):
        sign_in_form.locator(Buttons.SIGNIN).click()
        expect(sign_in_form.locator("[data-role='success']")).to_have_text(
            f"An email verification link has been sent to {email}."
        )
        expect(sign_in_form.locator(PASSWORD)).not_to_be_visible()
        expect(sign_in_form.locator(Buttons.SIGNIN)).not_to_be_visible()

    assert identity_calls["sign_up"][0]["email"] == email
    assert identity_calls["sign_in"][0]["email"] == email
    assert len(login_identity_calls) == 2
    assert len(verification_email_calls) == 2
    assert not identity_calls["unexpected"]


# @features login
# @dimensions auth-errors first-time-setup existing-account recovery sign-in-transition
def test_login_auth_error_messages_are_user_safe(get_user, browser_failures):
    """Identity Platform error codes should render safe messages, not provider internals."""
    _ensure_owner_initialized()
    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(
        user.page,
        sign_in_errors=["EMAIL_NOT_FOUND", "INVALID_LOGIN_CREDENTIALS"],
    )

    login_page = user.go(SitePages.LOGIN_PAGE)
    sign_in_form = _open_sign_in_form(
        user,
        login_page,
        f"auth-error-{uuid4().hex}@example.test",
    )
    password = sign_in_form.locator(PASSWORD)
    error = sign_in_form.locator(Roles.ERROR)

    password.fill("bad-password")
    with browser_failures.expect_http_error(
        user,
        status=400,
        path="/v1/accounts:signInWithPassword",
    ):
        sign_in_form.locator(Buttons.SIGNIN).click()
        expect(error).to_be_visible()
        expect(error).to_contain_text("Incorrect email or password.")
        expect(error).not_to_contain_text("EMAIL_NOT_FOUND")
        expect(error).not_to_contain_text("auth/")

    password.fill("bad-password-again")
    with browser_failures.expect_http_error(
        user,
        status=400,
        path="/v1/accounts:signInWithPassword",
        count=0,
        max_count=1,
    ):
        sign_in_form.locator(Buttons.SIGNIN).click()
        expect(error).to_contain_text("Incorrect email or password.")
        expect(error).not_to_contain_text("INVALID_LOGIN_CREDENTIALS")
        expect(error).not_to_contain_text("auth/")
    assert not identity_calls["unexpected"]

    user = get_user(Users.ANONYMOUS)
    identity_calls = _mock_identity_platform(user.page, sign_up_errors=["EMAIL_EXISTS"])
    login_identity_calls = []
    email = f"existing-identity-{uuid4().hex}@example.test"
    _create_first_time_user(email)
    _mock_login_identity(
        user.page,
        login_identity_calls,
        {"success": True, "redirect": "/testing-login-success"},
    )
    _mock_document(user.page, "/testing-login-success", "Login Complete")

    login_page = user.go(SitePages.LOGIN_PAGE)
    email_form = _open_email_check_form(user, login_page)
    email_form.locator(FormElements.EMAIL).fill(email)
    email_form.locator(Buttons.SIGNIN).click()

    first_time_form = user.locate(login_page.FIRST_TIME_SETUP_FORM)
    expect(first_time_form).to_be_visible()

    first_time_form.locator(PASSWORD).fill("valid-password")
    with browser_failures.expect_http_error(
        user,
        status=400,
        path="/v1/accounts:signUp",
    ):
        first_time_form.locator(Buttons.SIGNIN).click()
        sign_in_form = user.locate(login_page.SIGN_IN_FORM)
        expect(sign_in_form).to_be_visible()
        expect(sign_in_form.locator("input[name='email']")).to_have_value(email)
        expect(sign_in_form.locator("[data-role='success']")).to_have_text(
            "Your password is already set. Sign in to continue."
        )

    sign_in_form.locator(PASSWORD).fill("valid-password")
    sign_in_form.locator(Buttons.SIGNIN).click()
    expect(user.page).to_have_url(_site_url("/testing-login-success"))
    expect(user.page).to_have_title("Login Complete")

    assert identity_calls["sign_up"][0]["email"] == email
    assert identity_calls["sign_in"][0]["email"] == email
    assert login_identity_calls[0]["email"] == email
    assert not identity_calls["unexpected"]
