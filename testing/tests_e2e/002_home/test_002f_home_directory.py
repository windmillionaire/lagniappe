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

import pytest
from flask import Flask
from playwright.sync_api import expect
from werkzeug.exceptions import NotFound

from config import SETTINGS, constants
from lagniappe.core.tools.database.core import DATA, KINDS
from lagniappe.web import app as lagniappe_app
from lagniappe.web import auth as web_auth
from lagniappe.web.routes.analytics import main as analytics_main
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


# @features home
# @dimensions directory-list
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


# @features manual
# @dimensions page-load
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


# @features admin
# @dimensions page-load site-settings
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


# @features analytics
# @dimensions dashboard page-load accordion period-controls owner-filter retention-clear
@pytest.mark.e2e
def test_analytics_dashboard_owner_filter_and_retention_clear(get_user):
    owner = get_user(Users.OWNER)
    visitor = get_user(Users.admin, creator=owner)
    old_key = _save_analytics_event(
        "Retention Old", datetime.now(timezone.utc) - timedelta(days=8)
    )
    recent_key = _save_analytics_event(
        "Retention Recent", datetime.now(timezone.utc) - timedelta(days=1)
    )

    with visitor.page.expect_response("**/analytics/track"):
        visitor.go(SitePages.HOME)
    denied = visitor.page.goto(f"{SETTINGS.test_config['BASE_URL']}/analytics/")
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


# @pair ai-observability:independent-flags
# @pair ai-observability:ai-only
# @pair ai-observability:independent-clear
# @pair analytics:page-tracking
@pytest.mark.e2e
def test_ai_observability_dashboard_flags_and_clears_are_independent(monkeypatch):
    app = Flask(__name__)
    captured = []
    real_render_template = analytics_main.render_template
    ai_records = [
        {
            "workflow": "ask",
            "stage": "answer",
            "prompt_contract_id": "ask-report",
            "prompt_contract_version": 1,
            "success": True,
        }
    ]
    monkeypatch.setattr(
        analytics_main,
        "render_template",
        lambda template, **context: captured.append((template, context)) or context,
    )
    monkeypatch.setattr(
        analytics_main,
        "CONFIG",
        type("AIOnlyConfig", (), {"ANALYTICS": False, "AI_OBSERVABILITY": True})(),
    )
    monkeypatch.setattr(
        analytics_main,
        "_events",
        lambda *args, **kwargs: pytest.fail("AI-only page queried activity records"),
    )
    monkeypatch.setattr(analytics_main, "_ai_records", lambda period: ai_records)

    with app.test_request_context("/analytics/?period=30d"):
        body, status = analytics_main.index.__wrapped__()
    assert status == 200
    assert captured[-1][0] == "analytics/index.html"
    assert body["analytics_enabled"] is False
    assert body["dashboard"] is None
    assert body["ai_observability_enabled"] is True
    assert body["ai_dashboard"]["generation_count"] == 1
    with lagniappe_app.test_request_context("/analytics/?period=30d"):
        rendered = real_render_template("analytics/index.html", **body)
    assert 'data-role="ai-observability"' in rendered
    assert 'data-role="analytics-summary"' not in rendered
    assert "Delete AI Generation Records" in rendered
    assert "Delete Activity Records" not in rendered

    with app.test_request_context("/analytics/track", method="POST"):
        with pytest.raises(NotFound):
            analytics_main.track()

    deleted = []
    monkeypatch.setattr(
        analytics_main,
        "CONFIG",
        type("BothConfig", (), {"ANALYTICS": True, "AI_OBSERVABILITY": True})(),
    )
    monkeypatch.setattr(
        analytics_main,
        "_delete_events",
        lambda retention: deleted.append(("activity", retention)) or 2,
    )
    monkeypatch.setattr(
        analytics_main,
        "_delete_ai_records",
        lambda retention: deleted.append(("ai", retention)) or 3,
    )
    monkeypatch.setattr(
        analytics_main.DeferredJobs,
        "delete_terminal",
        lambda *, before: deleted.append(("jobs", before)) or 4,
    )

    with app.test_request_context("/analytics/clear/all", method="DELETE"):
        analytics_main.clear_records.__wrapped__("all")
    assert deleted == [("activity", "all")]

    with app.test_request_context("/analytics/ai/clear/all", method="DELETE"):
        response, status = analytics_main.clear_ai_records.__wrapped__("all")
    assert status == 200
    assert response.get_json() == {
        "dataset": "ai",
        "deleted": 3,
        "jobs_deleted": 4,
        "retention": "all",
        "label": "Delete All Records",
    }
    assert deleted == [("activity", "all"), ("ai", "all"), ("jobs", None)]


# @pair ai-observability:job-correlation
# @pair deferred-jobs:diagnostics
# @template analytics/index.html::ai_observability
@pytest.mark.e2e
def test_ai_operation_ids_and_json_diagnostics_are_correlated(monkeypatch):
    job_id = "opaque-report-organize-job"
    telemetry_id = "opaque-job-telemetry"
    operation = {
        "key": job_id,
        "type": "report-organize",
        "actor": "Analytics Owner",
        "status": "running",
        "phase_label": "Checking context",
        "attempt": 1,
        "elapsed_seconds": 6788,
        "recovering": True,
        "telemetry_id": telemetry_id,
        "input_refs": {"report": {"kind": "report", "id": "opaque-report-key"}},
    }
    matching_generation = {
        "correlation_id": "matching-generation",
        "telemetry_id": telemetry_id,
        "workflow": "organize",
        "stage": "planning",
        "state": "running",
        "active_provider_stage": "tool",
        "resolved_model": "gemini-test",
        "provider_requests": 5,
        "created": datetime(2026, 7, 19, 10, tzinfo=timezone.utc),
        "private_payload": "must not be exported",
    }
    unrelated_generation = {
        **matching_generation,
        "correlation_id": "unrelated-generation",
        "telemetry_id": "different-telemetry",
    }
    records = [matching_generation, unrelated_generation]

    monkeypatch.setattr(
        analytics_main,
        "CONFIG",
        type(
            "AIOnlyConfig",
            (),
            {"ANALYTICS": False, "AI_OBSERVABILITY": True},
        )(),
    )
    monkeypatch.setattr(
        analytics_main.DeferredJobs,
        "recent",
        lambda **_kwargs: [operation],
    )
    monkeypatch.setattr(analytics_main, "_ai_records", lambda _period: records)

    with lagniappe_app.test_request_context("/analytics/?period=30d"):
        rendered, status = analytics_main.index.__wrapped__()

    assert status == 200
    assert rendered.count(job_id) >= 2
    assert 'data-role="deferred-operation-id"' in rendered
    assert 'data-role="deferred-operation-json"' in rendered
    assert 'data-role="ai-generation-job-id"' in rendered
    assert "…organize-job" in rendered
    assert f"/analytics/ai/operations/{job_id}.json" in rendered
    assert "Delete AI Generation Records" in rendered
    assert "Delete Records Older Than 7 Days" in rendered

    with lagniappe_app.test_request_context(f"/analytics/ai/operations/{job_id}.json"):
        response, status = analytics_main.operation_diagnostic.__wrapped__(job_id)

    payload = response.get_json()
    assert status == 200
    assert payload["job_id"] == job_id
    assert payload["operation"]["input_refs"]["report"]["id"] == ("opaque-report-key")
    assert [record["correlation_id"] for record in payload["ai_generations"]] == [
        "matching-generation"
    ]
    serialized = response.get_data(as_text=True)
    assert "must not be exported" not in serialized
    assert "unrelated-generation" not in serialized

    class Owner:
        is_authenticated = True
        permissions_fingerprint = "analytics-owner"

        @staticmethod
        def has_permission(_resource, _requested):
            return True

    loaded_entity_ids = []

    def load_owner(entity_id=None):
        loaded_entity_ids.append(entity_id)
        return Owner(), None

    monkeypatch.setattr(web_auth, "_load_request_context", load_owner)
    monkeypatch.setattr(
        web_auth.database,
        "site_fingerprint",
        lambda _path: "analytics-diagnostics",
    )
    with lagniappe_app.test_request_context(f"/analytics/ai/operations/{job_id}.json"):
        wrapped_response, wrapped_status = analytics_main.operation_diagnostic(
            job_id=job_id
        )

    assert wrapped_status == 200
    assert wrapped_response.get_json()["job_id"] == job_id
    assert loaded_entity_ids == [None]

    with lagniappe_app.test_request_context(
        "/analytics/ai/operations/missing-job.json"
    ):
        with pytest.raises(NotFound):
            analytics_main.operation_diagnostic.__wrapped__("missing-job")


# @features manual
# @dimensions section-navigation popstate
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


# @features manual
# @dimensions section-navigation
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
# @style manual.code
# @style manual.codeShell
# @style manual.codeToolbar
# @style manual.copyButton
# @features manual
# @dimensions command-copy mobile-overflow
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
        '$lagniappePath = Join-Path $env:LOCALAPPDATA "Lagniappe"\n'
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
    assert anonymous.page.evaluate(
        "() => navigator.clipboard.readText()"
    ) == "gcloud auth login"

    command = clone_commands.first
    expect(command).to_have_css("overflow-x", "auto")
    expect(command).to_have_css("white-space", "pre")
    dimensions = command.evaluate(
        "element => ({clientWidth: element.clientWidth, "
        "scrollWidth: element.scrollWidth})"
    )
    assert dimensions["scrollWidth"] > dimensions["clientWidth"]


# @features manual
# @dimensions anonymous-access no-auth-bootstrap
@pytest.mark.e2e
def test_public_manual_loads_without_login_or_auth_bootstrap(get_user):
    anonymous = get_user(Users.ANONYMOUS)
    base_url = SETTINGS.test_config["BASE_URL"].rstrip("/")
    auth_bootstrap_paths = []

    def track_auth_bootstrap(request):
        path = urlparse(request.url).path
        if path in {"/update-session", "/poll", "/sync"}:
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
