"""Deferred page autofill stories grounded in attached-file summaries."""

import json
import re

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.database.filter import Filter, Query
from lagniappe.core.tools.deferred_jobs import DeferredJobs
from testing.definitions import Pages, Users


pytestmark = pytest.mark.e2e
FIELD_ID = "input-textab12"
FILE_SUMMARY = "Parcel 123 is assessed at $245,000 from the attached report."


def _attach_evidence(page):
    file = Entities.FILE.create(
        page=page.entity,
        data={"name": "Assessment Evidence", "summary": FILE_SUMMARY},
    )
    file.filename = "assessment.pdf"
    file.mimetype = "application/pdf"
    file.save()
    return file


def _notification_from_response(response):
    payload = response.json()
    assert payload["deferred"] is True
    match = re.search(r'data-key="([^"]+)"', payload["notification"])
    assert match, "Deferred response did not include a notification key"
    return Entities.fetch_one(match.group(1), request=Fetch.direct())


def _run_notification_job(notification):
    raw = (
        Query(KINDS.jobs)
        .filter(Filter().eq("notification", notification.key))
        .fetch_one()
    )
    assert raw, "Deferred response did not create a durable job"
    return DeferredJobs.run(database.get.urlsafe_key(raw.key))


# @pairs ai:autofill ai:deferred ai:attached-files ai:completion-refresh
# @pairs pages:autofill pages:deferred
# @pairs notifications:autofill notifications:deferred
# @pairs deferred-jobs:form-lock deferred-jobs:conflict deferred-jobs:reload
# @pairs deferred-jobs:refresh deferred-jobs:form-schema
# @pairs pages:refresh pages:form-schema
# @template pages/info.html::info_form
def test_page_autofill_runs_deferred_with_attached_file_context(
    get_user, monkeypatch, browser_failures
):
    user = get_user(Users.OWNER)
    page = Pages.test_page_autofill.get(user)
    _attach_evidence(page)
    user.go(page)

    form = page.info_form
    expect(form).to_have_attribute("lp-deferred", "")
    expect(form).to_have_attribute("data-destination", "info:PageInfo")
    form.locator("[data-role='show-autofill']").click()
    form.locator("textarea[name='autofill-description']").fill(
        "Use the attached assessment evidence."
    )

    submit = form.locator("button[data-role='autofill-submit']")
    form.evaluate("node => node.dataset.autofillProbe = 'mounted'")
    with user.page.expect_response("**/pages/*/update") as response_info:
        submit.click()
    notification = _notification_from_response(response_info.value)
    assert notification.pending is True
    progress = form.locator("[data-role='deferred-progress']")
    expect(progress).to_be_visible()
    expect(progress.locator("[data-role='deferred-phase']")).not_to_have_text("")
    expect(progress.locator("[data-icon='spinner']")).to_be_visible()
    expect(form.locator("[data-role='submit-group']")).not_to_be_attached()
    expect(form.locator("[data-role='autofill']")).not_to_be_attached()
    expect(form.locator("[data-role='autofill-submit-group']")).not_to_be_attached()
    expect(form.locator("textarea[name='autofill-description']")).not_to_be_attached()
    expect(form).to_have_attribute("data-autofill-probe", "mounted")
    expect(form.locator(f"[name='{FIELD_ID}']")).to_be_disabled()

    def form_lock_poll(response):
        if not response.url.endswith("/poll"):
            return False
        payload = response.request.post_data_json or {}
        return any(
            descriptor.get("type") == "form-lock" and descriptor.get("key") == page.key
            for descriptor in payload.get("subscriptions", [])
        )

    with user.page.expect_response(form_lock_poll) as poll_response:
        user.page.reload()
    assert poll_response.value.ok
    operation = next(
        result["payload"]
        for result in poll_response.value.json()["results"]
        if result.get("type") == "form-lock"
        and result.get("payload", {}).get("key") == page.key
    )
    assert operation["locked"] is True
    form = user.page.locator("[data-widget='PageInfo']")
    expect(form).to_have_attribute("initialized", "")
    expect(form).to_have_attribute("data-operation", re.compile(r".+"))
    expect(form.locator("[data-role='deferred-progress']")).to_be_visible()
    expect(form.locator("[data-role='submit-group']")).not_to_be_attached()
    expect(form.locator("[data-role='autofill']")).not_to_be_attached()
    expect(form.locator(f"[name='{FIELD_ID}']")).to_be_disabled()

    update_path = f"/pages/{page.entity.urlsafe_key}/update"
    original_name = page.entity.name
    with browser_failures.expect_http_error(user, status=409, path=update_path):
        locked_update = user.page.evaluate(
            """async ({path, name}) => {
                const body = new FormData();
                body.set("name", name);
                const response = await fetch(path, {
                    method: "PUT",
                    credentials: "include",
                    headers: {
                        "X-CSRFToken": document.getElementById("token")?.value,
                        "X-Lagniappe-Request": "true",
                    },
                    body,
                });
                return {status: response.status, data: await response.json()};
            }""",
            {"path": update_path, "name": "Blocked while autofill owns the form"},
        )
    assert locked_update["status"] == 409
    assert locked_update["data"]["locked"] is True
    assert locked_update["data"]["scope"] == "form-autofill"
    assert "changes were not saved" in locked_update["data"]["message"]
    unchanged = Entities.fetch_one(page.entity.urlsafe_key, request=Fetch.direct())
    assert unchanged.name == original_name

    from lagniappe.web import app as web_app
    from lagniappe.core.tools import deferred_job_adapters

    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return {FIELD_ID: "Assessment evidence applied"}

    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_autofilled_submission",
        generate,
    )
    with user.page.expect_response("**/pages/*/info/replace"):
        with web_app.test_request_context("/"):
            result = _run_notification_job(notification)

    assert result.success is True
    assert FILE_SUMMARY in json.dumps(prompts[0].context_blocks)
    assert prompts[0].tools == ["get_file"]
    assert prompts[0].max_tool_iterations == 2

    refreshed = user.page.get_by_text("Assessment evidence applied", exact=True).last
    expect(refreshed).to_be_visible()
    expect(form).not_to_have_attribute("data-autofill-probe", "mounted")
    expect(form.locator("[data-role='deferred-progress']")).not_to_be_attached()
    expect(form.locator("[data-role='submit-group']")).to_be_attached()
    expect(form.locator("[data-role='autofill']")).to_be_attached()
    expect(form.locator("[data-role='autofill-submit-group']")).to_be_attached()
