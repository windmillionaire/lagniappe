"""Optional monitoring must never gate usable Page or login controls."""

from contextlib import ExitStack

import pytest
from playwright.sync_api import expect

from config import SETTINGS, Environment
from lagniappe import CONFIG
from lagniappe.web import app
from testing.definitions import Pages, Users
from testing.utility.network import scoped_browser_route


pytestmark = pytest.mark.e2e


# @source lagniappe/web/routes/pages/main.py::view
# @source lagniappe/web/routes/users/login.py::login
# @matrix pages : load
# @matrix login : page-load
@pytest.mark.parametrize("layout", ["page", "login"])
@pytest.mark.parametrize("monitoring", ["pending", "blocked", "disabled", "missing-dsn"])
def test_optional_monitoring_does_not_gate_controls(
    get_user, monkeypatch, browser_failures, layout, monitoring,
):
    owner = get_user(Users.OWNER)
    user = owner if layout == "page" else get_user(Users.ANONYMOUS)
    path = (
        f"/pages/{Pages.test_create_page.get(owner).key}"
        if layout == "page" else "/users/login"
    )
    client = app.test_client()
    for cookie in user.page.context.cookies():
        client.set_cookie(cookie["name"], cookie["value"])
    # Render real production layouts; ordinary test-server responses deliberately
    # disable reporting. All application modules and subsequent routes stay real.
    with monkeypatch.context() as production:
        production.setattr(CONFIG, "ENV", Environment.PRODUCTION)
        production.setattr(CONFIG, "CAPTURE_ERRORS", monitoring != "disabled")
        production.setattr(
            CONFIG, "SENTRY_JS_DSN",
            "" if monitoring == "missing-dsn" else "https://public@errors.example.test/1",
        )
        production.setattr(CONFIG, "GOOGLE_SIGNIN_ENABLED", False)
        response = client.get(path)
    assert response.status_code == 200

    pending = []

    def monitor_request(route):
        pending.append(route)
        if monitoring == "blocked":
            route.abort("blockedbyclient")

    with ExitStack() as stack:
        if monitoring == "blocked":
            stack.enter_context(browser_failures.expect(
                user, kind="requestfailed", method="GET", path="/sentry.js",
                failure="net::ERR_BLOCKED_BY_CLIENT.Inspector",
            ))
            stack.enter_context(browser_failures.expect(
                user, kind="console", console_type="error",
                source_path="/sentry.js",
                text_contains="Failed to load resource: net::ERR_BLOCKED_BY_CLIENT",
            ))
        stack.enter_context(scoped_browser_route(
            user.page, f"**{path}",
            lambda route: route.fulfill(
                status=200, headers=dict(response.headers),
                body=response.get_data(as_text=True),
            ),
        ))
        stack.enter_context(scoped_browser_route(
            user.page, "**/sentry.js?*", monitor_request,
        ))
        try:
            # Async scripts still delay window.load; that event is deliberately
            # not the readiness boundary while the monitoring request is held.
            user.page.goto(
                f"{SETTINGS.test_config['BASE_URL']}{path}",
                wait_until="domcontentloaded",
            )
            if layout == "page":
                user.page.get_by_role("button", name="Edit Name", exact=True).click()
                name = user.page.locator("#name input[name='name']")
                expect(name).to_be_visible()
                name.fill("Unsaved monitoring probe")
                expect(name).to_have_value("Unsaved monitoring probe")
            else:
                user.page.get_by_role("button", name="Sign in with email", exact=True).click()
                expect(user.page.locator("#emailCheck")).to_be_visible()
            assert len(pending) == (1 if monitoring in {"pending", "blocked"} else 0)
        finally:
            if monitoring == "pending":
                for route in pending:
                    route.fulfill(content_type="text/javascript", body="/* unavailable SDK */")
            user.page.wait_for_load_state("load")
