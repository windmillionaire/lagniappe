"""
Tests for directory navigation component on home page.

Tests directory list and navigation links.

Related Files:
    Application:
        - lagniappe/web/templates/home/home.html: Directory component container
        - lagniappe/web/templates/home/directory.html: Directory list macro (links)
    Test Framework:
        - testing/resources/home.py: HomePage.directory (List helper)
"""

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from config import SETTINGS, constants
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database.core import DATA, KINDS
from testing.definitions import SitePages, Users


def _save_analytics_event(label, created):
    key = DATA.datastore.allocate_ids(DATA.datastore.key(KINDS.analytics.value), 1)[0]
    event = DATA.datastore.entity(key=key)
    event.update(
        {
            "urlsafe_key": key.to_legacy_urlsafe().decode(),
            "created": created,
            "action": "view",
            "route_prefix": "manual",
            "path": f"/manual/{label.lower().replace(' ', '-')}",
            "query": "",
            "page_title": label,
            "view_kind": "manual",
            "entity_key": "",
            "entity_hash": "",
            "index": "",
            "user_key": "",
            "user_hash": "",
            "user_name": "Analytics Retention",
            "user_email": "analytics-retention@test.com",
            "public_id": "",
            "referrer": "",
            "navigation_type": "test",
        }
    )
    DATA.datastore.put(event)
    return key


def _save_ai_record(telemetry_id, created):
    key = DATA.datastore.allocate_ids(
        DATA.datastore.key(KINDS.ai_observability.value), 1
    )[0]
    record = DATA.datastore.entity(key=key)
    record.update(
        {
            "correlation_id": f"correlation-{telemetry_id}",
            "telemetry_id": telemetry_id,
            "created": created,
            "updated": created,
            "workflow": "organize",
            "stage": "planning",
            "prompt_contract_id": "organize-report",
            "prompt_contract_version": 1,
            "state": "complete",
            "active_provider_stage": "structured_final",
            "resolved_model": "managed-test-model",
            "success": True,
            "provider_requests": 1,
            "private_payload": "must not be exported",
        }
    )
    DATA.datastore.put(record)
    return key


def _analytics_request(user, path, method="GET"):
    return user.page.evaluate(
        """async ({path, method}) => {
            const response = await fetch(path, {
                method,
                credentials: "include",
                headers: {
                    "X-CSRFToken": document.getElementById("token")?.value || "",
                    "X-Lagniappe-Request": "true",
                },
            });
            const text = await response.text();
            let data = text;
            try { data = JSON.parse(text); } catch {}
            return {status: response.status, data};
        }""",
        {"path": path, "method": method},
    )


# @pair home:directory-list
@pytest.mark.e2e
def test_directory_links_present(get_user):
    """Test that all directory links are present."""
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    directory = home.directory
    list_root = directory.list

    for link in ["Active Tasks", "Forms", "Users", "Admin"]:
        link_element = list_root.locator(f"a:has-text('{link}')")
        expect(link_element).to_be_visible()
    expect(user.locate(home.MANUAL_BUTTON)).to_be_visible()

    user.locate(home.DIRECTORY_LIST_TOGGLE).click()
    expect(list_root).not_to_be_visible()


# @pair manual:page-load
# @template manual/content/overview.html::open_source
@pytest.mark.e2e
def test_navigate_to_manual_from_home_button(get_user):
    """Test navigating to manual from the standalone home button."""
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    user.locate(home.MANUAL_BUTTON).click()

    expect(user.page).to_have_title("Manual")
    source_link = user.locate(f"a[href='{constants.DEFAULT_SOURCE_URL}']")
    expect(source_link).to_be_visible()
    expect(source_link).to_contain_text("Source for this installation")


# @matrix admin : page-load site-settings
@pytest.mark.e2e
def test_admin_directory_link_opens_admin_settings(get_user):
    """The owner can open the Admin settings view from the home directory."""
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    admin_link = home.directory.list.locator("a:has-text('Admin')")
    expect(admin_link).to_be_visible()
    admin_link.click()

    expect(user.page).to_have_title("Admin")
    expect(user.locate("[lp-view][data-kind='admin']")).to_have_attribute(
        "initialized", ""
    )
    settings = user.locate("[data-widget='SiteSettings']")
    expect(settings).to_have_attribute("initialized", "")
    expect(settings).to_be_visible()


# @matrix analytics : accordion dashboard owner-filter page-load period-controls retention-clear
@pytest.mark.e2e
def test_analytics_dashboard_owner_filter_and_retention_clear(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    visitor = get_user(Users.admin, creator=owner)
    old_key = _save_analytics_event(
        "Retention Old", datetime.now(timezone.utc) - timedelta(days=8)
    )
    recent_key = _save_analytics_event(
        "Retention Recent", datetime.now(timezone.utc) - timedelta(days=1)
    )

    # Activity details intentionally show only the four most active visitors.
    # Establish this visitor as a visible member of that bounded summary even
    # after the earlier full-suite home stories have produced their own events.
    for _visit in range(5):
        with visitor.page.expect_response("**/analytics/track"):
            visitor.go(SitePages.HOME)
    analytics_url = f"{SETTINGS.test_config['BASE_URL']}/analytics/"
    with browser_failures.expect_http_error(
        visitor,
        status=403,
        path=analytics_url,
    ):
        denied = visitor.page.goto(analytics_url)
    assert denied.status == 403

    with owner.page.expect_response("**/analytics/track"):
        home = owner.go(SitePages.HOME)

    analytics_link = home.directory.list.locator("a:has-text('Analytics')")
    expect(analytics_link).to_be_visible()
    with owner.page.expect_response("**/analytics/") as analytics_response:
        analytics_link.click()
    assert analytics_response.value.headers["cache-control"] == "no-store"

    expect(owner.page).to_have_title("Analytics")
    expect(owner.locate("[lp-view][data-kind='analytics']")).to_have_attribute(
        "initialized", ""
    )

    summary = owner.locate("[data-role='analytics-summary']")
    expect(summary).to_contain_text("Page Views")
    expect(summary).to_contain_text("Logins")
    expect(summary).to_contain_text("Public Views")
    expect(owner.locate("[aria-label='Analytics period']")).to_contain_text("Today")
    activity_retention = owner.locate(
        "[data-role='analytics-retention'][data-dataset='activity']"
    )
    expect(activity_retention).to_contain_text("Delete Activity Records")

    home_group = owner.locate("[data-role='analytics-prefix'][data-prefix='home']")
    expect(home_group).to_be_visible()
    with owner.page.expect_response("**/analytics/events/home*"):
        home_group.locator("[data-role='expand']").click()

    events = home_group.locator("[data-role='analytics-events']")
    expect(events).to_contain_text("Home")
    expect(events).to_contain_text("View")
    expect(events).to_contain_text(visitor.name)
    expect(events).not_to_contain_text(owner.name)

    retention_toggle = activity_retention.locator(
        "[data-role='analytics-retention-toggle']"
    )
    retention_toggle.click()
    retention_panel = activity_retention.locator(
        "[data-role='analytics-retention-panel']"
    )
    expect(retention_panel).to_be_visible()
    expect(
        retention_panel.locator("[data-role='analytics-clear'][data-retention='7d']")
    ).to_have_text("Delete Records Older Than 7 Days")

    with owner.page.expect_response("**/analytics/clear/7d") as old_clear:
        retention_panel.locator(
            "[data-role='analytics-clear'][data-retention='7d']"
        ).click()
    assert old_clear.value.ok
    assert old_clear.value.json()["deleted"] >= 1
    expect(
        activity_retention.locator("[data-role='analytics-clear-status']")
    ).to_contain_text("Deleted")
    assert DATA.datastore.get(old_key) is None
    assert DATA.datastore.get(recent_key) is not None

    retention_panel = activity_retention.locator(
        "[data-role='analytics-retention-panel']"
    )
    with owner.page.expect_response("**/analytics/clear/all") as all_clear:
        retention_panel.locator(
            "[data-role='analytics-clear'][data-retention='all']"
        ).click()
    assert all_clear.value.ok
    assert all_clear.value.json()["deleted"] >= 1
    expect(
        activity_retention.locator("[data-role='analytics-clear-status']")
    ).to_contain_text("Deleted")
    expect(owner.locate("[data-role='analytics-route-groups']")).to_contain_text(
        "No activity in this period."
    )
    assert DATA.datastore.get(recent_key) is None


# @matrix ai-observability : ai-only independent-clear independent-flags job-correlation
# @pairs analytics:page-tracking deferred-jobs:diagnostics
# @template analytics/index.html::ai_observability
@pytest.mark.e2e
def test_ai_dashboard_diagnostics_and_clear_use_real_routes(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    telemetry_id = f"analytics-{uuid4().hex}"
    activity_key = _save_analytics_event("AI Clear Control", datetime.now(timezone.utc))
    ai_key = _save_ai_record(telemetry_id, datetime.now(timezone.utc))
    job = Entities.DEFERRED_JOB.create(
        {
            "actor": owner.entity,
            "job_type": "report-organize",
            "status": "succeeded",
            "idempotency_key": telemetry_id,
            "dispatch_state": "complete",
            "telemetry_id": telemetry_id,
            "inputs": {"report": {"kind": "report", "id": "opaque-report-key"}},
            "progress": {"phase": "finalizing"},
        }
    )
    Entities.save(job)

    owner.go(SitePages.HOME)
    response = owner.page.goto(f"{SETTINGS.test_config['BASE_URL']}/analytics/")
    assert response.ok
    expect(owner.locate("[data-role='ai-observability']")).to_be_visible()
    expect(owner.locate("[data-role='analytics-summary']")).to_be_visible()
    expect(owner.page.locator("body")).to_contain_text(job.urlsafe_key)
    expect(owner.page.locator("body")).to_contain_text("Delete AI Generation Records")

    diagnostic_path = f"/analytics/ai/operations/{job.urlsafe_key}.json"
    diagnostic = _analytics_request(owner, diagnostic_path)
    assert diagnostic["status"] == 200
    assert diagnostic["data"]["job_id"] == job.urlsafe_key
    assert diagnostic["data"]["operation"]["input_refs"]["report"]["id"] == (
        "opaque-report-key"
    )
    assert len(diagnostic["data"]["ai_generations"]) == 1
    assert "must not be exported" not in str(diagnostic["data"])

    missing_path = "/analytics/ai/operations/missing-job.json"
    with browser_failures.expect_http_error(owner, status=404, path=missing_path):
        missing = _analytics_request(owner, missing_path)
    assert missing["status"] == 404

    cleared = _analytics_request(owner, "/analytics/ai/clear/all", method="DELETE")
    assert cleared["status"] == 200
    assert cleared["data"]["dataset"] == "ai"
    assert cleared["data"]["deleted"] >= 1
    assert cleared["data"]["jobs_deleted"] >= 1
    assert DATA.datastore.get(ai_key) is None
    assert DATA.datastore.get(activity_key) is not None
    assert DATA.datastore.get(job.key) is None


# @matrix manual : popstate section-navigation
@pytest.mark.e2e
def test_manual_ajax_section_navigation_and_popstate(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    user.locate(home.MANUAL_BUTTON).click()
    expect(user.page).to_have_title("Manual")
    expect(user.locate("[lp-view]")).to_have_attribute("initialized", "")

    user.page.evaluate("window.__manualNavigationToken = 'preserved'")
    content = user.page.locator("[data-role='manual-content']")

    with user.page.expect_response("**/manual/section/forms"):
        user.page.locator("button[data-section='forms']").first.click()
    expect(user.page).to_have_url(re.compile(r".*/manual/forms$"))
    expect(content).to_contain_text("What Forms Are For")
    assert user.page.evaluate("window.__manualNavigationToken") == "preserved"

    with user.page.expect_response("**/manual/section/tasks"):
        user.page.locator("button[data-section='tasks']").first.click()
    expect(user.page).to_have_url(re.compile(r".*/manual/tasks$"))
    expect(content).to_contain_text("Tasks Live on Pages")
    assert user.page.evaluate("window.__manualNavigationToken") == "preserved"

    with user.page.expect_response("**/manual/section/forms"):
        user.page.go_back()
    expect(user.page).to_have_url(re.compile(r".*/manual/forms$"))
    expect(content).to_contain_text("What Forms Are For")

    with user.page.expect_response("**/manual/section/tasks"):
        user.page.go_forward()
    expect(user.page).to_have_url(re.compile(r".*/manual/tasks$"))
    expect(content).to_contain_text("Tasks Live on Pages")


# @pair manual:section-navigation
@pytest.mark.e2e
def test_manual_security_section_loads(get_user):
    user = get_user(Users.OWNER)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")

    response = user.page.goto(
        f"{base_url}/manual/security",
        wait_until="domcontentloaded",
    )
    assert response.ok

    content = user.page.locator("[data-role='manual-content']")
    expect(content).to_contain_text("Security Model")
    expect(content).to_contain_text("Redis Cloud Boundary")
    expect(content).to_contain_text("App Engine alone does not automatically")
    expect(content).to_contain_text("Free Essentials plans cannot")
    expect(content).to_contain_text("HTTPS for the server-to-server connection")
    expect(content).to_contain_text("password is still required")
    expect(content).to_contain_text("./setup.sh security")
    expect(content).to_contain_text(".\\setup.cmd security")
    expect(content).to_contain_text("unzip it")
    expect(content).to_contain_text("config/files/redis_ca.pem")


# @template manual/macros.html::code
# @template manual/macros.html::card
# @style manual.code
# @style manual.codeShell
# @style manual.codeToolbar
# @style manual.copyButton
# @pair manual:command-copy
@pytest.mark.e2e
def test_manual_installation_commands_are_copyable_and_scroll_on_mobile(
    get_user,
):
    anonymous = get_user(Users.ANONYMOUS)
    anonymous.page.set_viewport_size({"width": 360, "height": 740})
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")

    response = anonymous.page.goto(
        f"{base_url}/manual/installation",
        wait_until="load",
    )

    assert response.ok
    expect(anonymous.locate("[lp-view]")).to_have_attribute("initialized", "")
    commands = anonymous.locate("[data-role='manual-command']")
    clone_commands = commands.filter(
        has_text="https://github.com/windmillionaire/lagniappe.git"
    )
    expect(clone_commands).to_have_count(2)
    expect(clone_commands.nth(0)).to_have_text(
        '$lagniappePath = Join-Path $env:USERPROFILE "Lagniappe"\n'
        "git clone https://github.com/windmillionaire/lagniappe.git "
        "$lagniappePath\n"
        "Set-Location $lagniappePath"
    )
    expect(clone_commands.nth(1)).to_have_text(
        "git clone https://github.com/windmillionaire/lagniappe.git lagniappe\n"
        "cd lagniappe"
    )
    copy_buttons = anonymous.locate("[data-role='manual-command-copy']")
    expect(copy_buttons).to_have_count(commands.count())
    auth_command = commands.filter(has_text=re.compile(r"^gcloud auth login$"))
    expect(auth_command).to_have_count(1)
    copy_button = auth_command.locator(
        "xpath=ancestor::*[@data-role='manual-command-shell']"
    ).locator("[data-role='manual-command-copy']")
    copy_button.click()
    expect(copy_button).to_have_text("Copied!")
    assert (
        anonymous.page.evaluate("() => navigator.clipboard.readText()")
        == "gcloud auth login"
    )

    command = clone_commands.first
    expect(command).to_have_css("overflow-x", "auto")
    expect(command).to_have_css("white-space", "pre")
    dimensions = command.evaluate(
        "element => ({clientWidth: element.clientWidth, "
        "scrollWidth: element.scrollWidth})"
    )
    assert dimensions["scrollWidth"] > dimensions["clientWidth"]

    command_shells = anonymous.locate("[data-role='manual-command-shell']")
    shell_bounds = command_shells.evaluate_all(
        """elements => elements.map((element) => {
                const shell = element.getBoundingClientRect();
                const card = element.closest("[data-role='manual-card']");
                const cardBounds = card.getBoundingClientRect();
                const cardStyle = getComputedStyle(card);
                return {
                    shellLeft: shell.left,
                    shellRight: shell.right,
                    contentLeft:
                        cardBounds.left + parseFloat(cardStyle.paddingLeft),
                    contentRight:
                        cardBounds.right - parseFloat(cardStyle.paddingRight),
                };
            })"""
    )
    for bounds in shell_bounds:
        assert bounds["shellLeft"] >= bounds["contentLeft"] - 0.5
        assert bounds["shellRight"] <= bounds["contentRight"] + 0.5


# @matrix manual : anonymous-access no-auth-bootstrap
@pytest.mark.e2e
def test_public_manual_loads_without_login_or_auth_bootstrap(get_user):
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")
    auth_bootstrap_paths = []

    def track_auth_bootstrap(request):
        path = urlparse(request.url).path
        if path in {"/l/update-session", "/l/poll", "/l/sync"}:
            auth_bootstrap_paths.append(path)

    anonymous.page.on("request", track_auth_bootstrap)
    response = anonymous.page.goto(
        f"{base_url}/manual/security",
        wait_until="load",
    )

    assert response.ok
    expect(anonymous.page).to_have_title("Manual")
    expect(anonymous.locate("meta[name='mode']")).to_have_attribute("content", "public")
    expect(anonymous.locate("[lp-view][data-kind='manual']")).to_have_attribute(
        "initialized", ""
    )
    expect(anonymous.locate("[lp-view][data-kind='manual']")).to_have_attribute(
        "data-readonly", "true"
    )
    expect(anonymous.locate("[data-role='manual-content']")).to_contain_text(
        "Security Model"
    )
    assert "/users/login" not in anonymous.page.url
    assert auth_bootstrap_paths == []


# @matrix manual : address-redaction ai-email ajax-section anonymous-access direct-section no-auth-bootstrap
@pytest.mark.e2e
def test_ai_manual_keeps_account_addresses_authenticated(get_user):
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")
    auth_bootstrap_paths = []

    def track_auth_bootstrap(request):
        path = urlparse(request.url).path
        if path in {"/l/update-session", "/l/poll", "/l/sync"}:
            auth_bootstrap_paths.append(path)

    anonymous.page.on("request", track_auth_bootstrap)
    response = anonymous.page.goto(
        f"{base_url}/manual/ai",
        wait_until="load",
    )

    assert response.ok
    content = anonymous.locate("[data-role='manual-content']")
    expect(content).to_contain_text("AI Reports by Email")
    public_description = content.locator("[data-role='public-ai-email-description']")
    expect(public_description).to_be_visible()
    expect(public_description).to_contain_text(
        "Registered users can email questions, requests, or attachments"
    )
    expect(content.locator("[data-role='ai-email-account-details']")).to_have_count(0)
    expect(public_description).not_to_contain_text("@")

    ajax = anonymous.page.evaluate(
        """async () => {
            const response = await fetch("/manual/section/ai");
            return {
                ok: response.ok,
                status: response.status,
                text: await response.text(),
            };
        }"""
    )
    assert ajax["ok"] is True
    assert ajax["status"] == 200
    assert 'data-role="public-ai-email-description"' in ajax["text"]
    assert 'data-role="ai-email-account-details"' not in ajax["text"]
    assert "@" not in ajax["text"]
    assert auth_bootstrap_paths == []

    owner = get_user(Users.OWNER)
    response = owner.page.goto(
        f"{base_url}/manual/ai",
        wait_until="load",
    )

    assert response.ok
    content = owner.locate("[data-role='manual-content']")
    account_details = content.locator("[data-role='ai-email-account-details']")
    expect(account_details).to_be_visible()
    expect(account_details).to_contain_text("AI (recommended)")
    expect(account_details).to_contain_text("Create")
    expect(account_details).to_contain_text("Organize")
    expect(content.locator("[data-role='public-ai-email-description']")).to_have_count(
        0
    )
    expect(account_details).to_contain_text("@")
