"""Deferred task autofill stories grounded in task-specific files."""

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
from testing.definitions import Pages, Tasks, Users


pytestmark = pytest.mark.e2e
FIELD_ID = "input-textab12"
FILE_SUMMARY = "The annual property tax shown in the task evidence is $2,450."


def _attach_task_evidence(task):
    file = Entities.FILE.create(
        data={"name": "Tax Bill Evidence", "summary": FILE_SUMMARY},
    )
    file.filename = "tax-bill.pdf"
    file.mimetype = "application/pdf"
    file.save()
    task.entity.properties.files.add(file)
    task.entity.save()
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
# @pairs tasks:autofill tasks:deferred
# @pairs notifications:autofill notifications:deferred
# @template pages/tasks.html::task_form
def test_task_autofill_runs_deferred_with_page_file_context(get_user, monkeypatch):
    user = get_user(Users.OWNER)
    page = Pages.test_page_autofill.get(user)
    task = Tasks.test_task_autofill.get(user)
    _attach_task_evidence(task)
    user.go(page, query_params={"tab": "tasks"})

    form = task.task_form
    expect(form).to_have_attribute("lp-deferred", "")
    expect(form).to_have_attribute(
        "data-destination", f"{task.entity.hash}:TaskForm"
    )
    form.locator("[data-role='show-autofill']").click()
    form.locator("textarea[name='autofill-description']").fill(
        "Use the property tax evidence attached to this page."
    )

    submit = form.locator("button[data-role='autofill-submit']")
    form.evaluate("node => node.dataset.autofillProbe = 'mounted'")
    with user.page.expect_response("**/tasks/*/update") as response_info:
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
    expect(
        form.locator("textarea[name='autofill-description']")
    ).not_to_be_attached()
    expect(form).to_have_attribute("data-autofill-probe", "mounted")
    expect(form.locator(f"[name='{FIELD_ID}']")).to_be_disabled()

    from lagniappe.web import app as web_app
    from lagniappe.core.tools import deferred_job_adapters

    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        return {FIELD_ID: "Tax evidence applied"}

    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_autofilled_submission",
        generate,
    )
    with user.page.expect_response("**/tasks/*/replace") as response_info:
        with web_app.test_request_context("/"):
            result = _run_notification_job(notification)

    assert result.success is True
    assert FILE_SUMMARY in json.dumps(prompts[0].context_blocks)
    assert prompts[0].tools == ["get_file"]
    assert prompts[0].max_tool_iterations == 2

    response = response_info.value
    assert response.ok, response.text()
    replacement = response.json()
    assert replacement["submission"][FIELD_ID] == "Tax evidence applied"
    assert any(field["id"] == FIELD_ID for field in replacement["schema"])
    assert 'data-widget="TaskForm"' in replacement["html"]
    revisions = json.loads(
        response.headers["x-lagniappe-entity-revisions"]
    )
    assert {revision["key"] for revision in revisions} >= {task.key, page.key}

    refreshed = user.page.get_by_text("Tax evidence applied", exact=True).last
    expect(refreshed).to_be_visible()
    expect(form).not_to_have_attribute("data-autofill-probe", "mounted")
    expect(form.locator("[data-role='deferred-progress']")).not_to_be_attached()
    expect(form.locator("[data-role='submit-group']")).to_be_attached()
    expect(form.locator("[data-role='autofill']")).to_be_attached()
    expect(form.locator("[data-role='autofill-submit-group']")).to_be_attached()
