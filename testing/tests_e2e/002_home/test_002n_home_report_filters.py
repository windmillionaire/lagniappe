"""Homepage report filtering and creator-scoped bulk history cleanup."""

from io import BytesIO
import json
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from werkzeug.datastructures import FileStorage

from lagniappe.core.definitions import AI, Fetch
from lagniappe.core.entities import Entities
from testing.definitions import SitePages, Users
from testing.definitions.user_definitions import UserDefinition
from testing.resources import Report
from testing.utility.polling import expect_poll_result

pytestmark = pytest.mark.e2e


def _reader(get_user):
    suffix = uuid4().hex
    return get_user(
        UserDefinition(
            name=f"Report filters {suffix}",
            email=f"report-filters-{suffix}@example.test",
            ai_access=AI.NONE,
        ),
        creator=get_user(Users.OWNER),
    )


def _report(user, tool="create", status="ready", **data):
    owner = Entities.USER.load(user.email)
    report = Entities.REPORT.create(
        {
            "user": owner,
            "tool": tool,
            "status": status,
            "pending": False,
            "name": f"{tool.title()} {status} {uuid4().hex[:8]}",
            "summary": "Saved report for filter review.",
            **data,
        }
    )
    Entities.save(report)
    return report


def _open_reports(user):
    home = user.go(SitePages.HOME)
    user.locate(home.TOOL_REPORT_LIST_TOGGLE).click()
    panel = user.locate(home.TOOL_REPORT_LIST)
    expect(panel).to_have_attribute("loaded", "")
    return panel


def _filter(panel, value):
    return panel.locator(f"[data-role='report-filter'][data-filter='{value}']")


def _executed_only(panel):
    for value in ("active", "ask", "executed"):
        button = _filter(panel, value)
        desired = value == "executed"
        if (button.get_attribute("aria-pressed") == "true") != desired:
            button.click()
        expect(button).to_have_attribute("aria-pressed", str(desired).lower())


# @matrix ai-report : filter-categories filter-counts filter-empty filter-persistence
# @template home/tools.html::report_list
# @template home/tools.html::report_item
@pytest.mark.parametrize("mobile", [False, True])
def test_report_filters_persist_and_follow_live_status(
    get_user, mobile, tmp_path, browser_failures
):
    user = _reader(get_user)
    ready = _report(user)
    done = _report(user, "organize", "complete")
    answer = _report(user, "ask", "complete")
    panel = _open_reports(user)
    if mobile:
        user.page.set_viewport_size({"width": 360, "height": 800})

    expect(panel.get_by_role("link", name=ready.name)).to_be_visible()
    expect(panel.get_by_role("link", name=answer.name)).to_be_visible()
    expect(panel.get_by_role("link", name=done.name)).to_be_hidden()
    for value in ("active", "executed", "ask"):
        expect(
            _filter(panel, value).locator("[data-role='report-count']")
        ).to_have_text("1")

    _filter(panel, "active").click()
    _filter(panel, "ask").focus()
    user.page.keyboard.press("Space")
    expect(panel.locator("[data-role='report-empty']")).to_have_text(
        "Select a report type to show."
    )
    expect(panel).to_be_visible()
    _filter(panel, "executed").click()
    expect(panel.locator("[data-role='delete-executed-reports']")).to_be_visible()
    expect(panel.get_by_role("link", name=done.name)).to_be_visible()
    panel.screenshot(path=str(tmp_path / "report-filters.png"))
    assert panel.bounding_box()["width"] <= user.page.viewport_size["width"]

    panel = _open_reports(user)
    expect(_filter(panel, "executed")).to_have_attribute("aria-pressed", "true")
    expect(_filter(panel, "active")).to_have_attribute("aria-pressed", "false")
    expect(_filter(panel, "ask")).to_have_attribute("aria-pressed", "false")
    # Home collection subscriptions refresh on foreground/reconnect events;
    # reconnect through the real browser network lifecycle after a remote save.
    with browser_failures.expect_offline(user):
        user.offline = True
    ready.status = "complete"
    Entities.save(ready)
    with expect_poll_result(user.page, subscription_id="home:channel:tool-reports"):
        user.offline = False
    expect(
        _filter(panel, "executed").locator("[data-role='report-count']")
    ).to_have_text("2")
    expect(panel.get_by_role("link", name=ready.name)).to_be_visible()
    expect(panel.get_by_role("link", name=answer.name)).to_be_hidden()


# @matrix ai-report : bulk-delete confirmation delete-snapshot delete-failure loading-indicator
# @template home/tools.html::report_list
# @template layouts/delete.html::delete_action
def test_delete_executed_reports_confirms_snapshot_and_preserves_workspace(
    get_user, tmp_path
):
    user = _reader(get_user)
    owner = Entities.USER.load(user.email)
    owner_page = Entities.fetch_one(owner.page, request=Fetch.direct())
    task_name = f"Task retained after report deletion {uuid4().hex[:8]}"
    report = _report(
        user,
        proposal={
            "summary": "Create a personal task.",
            "actions": [
                {
                    "id": "task",
                    "type": "create_task",
                    "data": {
                        "name": task_name,
                        "page": owner.page.urlsafe_key,
                    },
                }
            ],
        },
    )
    page = user.go(Report.for_entity(user, report))
    page.execute()
    expect(user.page.get_by_text("Work done.")).to_be_visible()
    report = Entities.fetch_one(report.key, request=Fetch.direct())
    task_key = next(
        action["entity"]["id"]
        for action in report.result["actions"]
        if action.get("entity", {}).get("kind") == "task"
    )
    files = []
    for name, attached in (("report-only.txt", False), ("retained.txt", True)):
        file = Entities.FILE.create(
            page=owner_page if attached else None,
            upload=FileStorage(stream=BytesIO(b"Report evidence"), filename=name),
            data={"filename": name, "mimetype": "text/plain"},
            report_user=owner,
        )
        files.append(file)
    report.input_files = files
    Entities.save(*files, report)
    answer = _report(user, "ask", "complete")
    unfinished = _report(user)
    panel = _open_reports(user)
    _executed_only(panel)
    clear = panel.locator("[data-role='delete-executed-reports']")
    clear.click()
    dialog = user.page.get_by_role("dialog", name="Delete executed proposals")
    expect(dialog).to_contain_text("Delete 1 executed proposal?")
    expect(dialog).to_contain_text(
        "Pages, tasks, and other workspace changes will remain."
    )
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).not_to_be_attached()
    assert Entities.fetch_one(report.key, request=Fetch.root()) is not None

    clear.click()
    expect(dialog).to_be_visible()
    arrival = _report(user, status="complete")
    confirm = dialog.get_by_role("button", name="Delete 1 proposal", exact=True)
    spinner = confirm.locator("#spinner[data-role='icon']")
    expect(confirm).to_be_focused()
    expect(spinner).to_be_hidden()
    pending_deletes = []
    # Include service-worker-owned requests when holding the server response.
    user.page.context.route(
        "**/tools/reports/executed", lambda route: pending_deletes.append(route)
    )
    with user.page.context.expect_event(
        "request", predicate=lambda request: request.url.endswith("/tools/reports/executed")
    ):
        confirm.click()
    expect(confirm).to_be_disabled()
    expect(spinner).to_be_visible()
    dialog.screenshot(path=str(tmp_path / "report-delete-loading.png"))
    assert len(pending_deletes) == 1
    assert pending_deletes[0].request.post_data_json == {"keys": [report.urlsafe_key]}
    with user.page.context.expect_event(
        "response", predicate=lambda response: response.url.endswith("/tools/reports/executed")
    ) as response:
        pending_deletes.pop().continue_()
    user.page.context.unroute("**/tools/reports/executed")
    assert response.value.status == 200
    expect(dialog).not_to_be_attached()
    expect(panel.get_by_role("link", name=report.name)).not_to_be_attached()
    expect(panel.get_by_role("link", name=arrival.name)).to_be_visible()
    assert Entities.fetch_one(report.key, request=Fetch.root()) is None
    assert Entities.fetch_one(files[0].key, request=Fetch.root()) is None
    assert Entities.fetch_one(files[1].key, request=Fetch.root()) is not None
    assert Entities.fetch_one(task_key, request=Fetch.root()).name == task_name
    for survivor in (answer, unfinished, arrival):
        assert Entities.fetch_one(survivor.key, request=Fetch.root()) is not None

    clear.click()
    with user.page.expect_response("**/tools/reports/executed"):
        dialog.get_by_role("button", name="Delete 1 proposal", exact=True).click()
    expect(panel.locator("[data-role='report-empty']")).to_have_text(
        "No executed proposals."
    )
    expect(panel).to_be_visible()
    expect(clear).to_be_hidden()
    expect(_filter(panel, "executed")).to_have_attribute("aria-pressed", "true")
    _filter(panel, "ask").click()
    expect(panel.get_by_role("link", name=answer.name)).to_be_visible()


# @matrix ai-report : bulk-delete ownership validation
def test_bulk_report_delete_rechecks_ownership_and_validates_input(
    get_user, browser_failures
):
    user = _reader(get_user)
    foreign_user = _reader(get_user)
    own = _report(user, status="complete")
    foreign = _report(foreign_user, status="complete")
    ask = _report(user, "ask", "complete")
    active = _report(user)
    user.go(SitePages.HOME)

    def delete(data):
        return user.page.evaluate(
            """async (data) => {
                const token = await (await fetch('/l/token', {
                    credentials: 'include', headers: {'X-Lagniappe-Request': 'true'}
                })).text();
                const response = await fetch('/tools/reports/executed', {
                    method: 'DELETE', credentials: 'include',
                    headers: {'X-CSRFToken': token, 'X-Lagniappe-Request': 'true', 'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                return {status: response.status, text: await response.text()};
            }""",
            data,
        )

    for data in ({}, {"keys": "all"}, {"keys": [1]}, {"keys": [""]}):
        with browser_failures.expect_http_error(
            user, status=422, path="/tools/reports/executed"
        ):
            response = delete(data)
        assert response["status"] == 422, response
    response = delete(
        {
            "keys": [
                foreign.urlsafe_key,
                ask.urlsafe_key,
                active.urlsafe_key,
                own.urlsafe_key,
            ]
        }
    )
    assert response["status"] == 200, response
    assert json.loads(response["text"]) == {
        "deleted": [own.urlsafe_key],
        "skipped": [foreign.urlsafe_key, ask.urlsafe_key, active.urlsafe_key],
        "failed": [],
    }
    for survivor in (foreign, ask, active):
        assert Entities.fetch_one(survivor.key, request=Fetch.root()) is not None
