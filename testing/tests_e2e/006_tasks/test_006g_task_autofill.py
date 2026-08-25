"""Deferred task autofill stories grounded in task-specific files."""

from dataclasses import replace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import DeferredJobStatus, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from testing.definitions import Pages, Tasks, Users
from testing.resources import Page, Task
from testing.utility.hosted_deferred_jobs import dispatch_hosted_deferred_job


pytestmark = pytest.mark.e2e
FIELD_ID = "input-textab12"
FILE_SUMMARY = "The annual property tax shown in the task evidence is $2,450."
EXPECTED_VALUE = "$2,450"


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


def _create_autofill_fixture(user):
    page = Page(
        user=user,
        definition=replace(
            Pages.test_page_autofill.value.definition,
            name=f"Task Autofill Page {uuid4().hex}",
        ),
    ).create()
    definition = replace(
        Tasks.test_task_autofill.value.definition,
        name=f"Autofill Evidence Task {uuid4().hex}",
    )
    form = definition.form.get(user).entity
    entity = Entities.TASK.create(
        {
            "name": definition.name,
            "description": definition.description,
            "page": page.entity,
            "form": form,
        }
    )
    entity = Entities.fetch_one(
        entity,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    entity.save()
    task = Task(user=user, definition=definition)
    task.entity = entity
    return page, task


# @matrix ai : attached-files autofill completion-refresh deferred
# @matrix deferred-jobs : cloud-tasks hosted-e2e oidc process-route provider-delivery
# @matrix notifications tasks : autofill deferred
# @template pages/tasks.html::task_form
@pytest.mark.ai
def test_task_autofill_runs_deferred_with_page_file_context(get_user, monkeypatch):
    user = get_user(Users.OWNER)
    page, task = _create_autofill_fixture(user)
    _attach_task_evidence(task)
    user.go(page, query_params={"tab": "tasks"})

    form = task.task_form
    expect(form).to_have_attribute("lp-deferred", "")
    expect(form).to_have_attribute(
        "data-destination", f"{task.entity.hash}:TaskForm"
    )
    form.locator("[data-role='show-autofill']").click()
    form.locator("textarea[name='autofill-description']").fill(
        "Read the attached property tax evidence and set Text Field to exactly "
        "the annual property tax, including the dollar sign and comma."
    )

    submit = form.locator("button[data-role='autofill-submit']")
    form.evaluate("node => node.dataset.autofillProbe = 'mounted'")
    with user.page.expect_response("**/tasks/*/update") as response_info:
        submit.click()
    payload = response_info.value.json()
    job = Entities.fetch_one(payload["operation"], request=Fetch.direct())
    assert job.status == DeferredJobStatus.QUEUED.value
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

    if CONFIG.hosted_e2e_runner:
        completed, attempts = dispatch_hosted_deferred_job(user.page, job)
        assert completed.status == DeferredJobStatus.SUCCEEDED.value, attempts
        user.page.reload()
        form = task.task_form
    else:
        from lagniappe.web import app as web_app
        from lagniappe.core.tools.deferred_jobs.adapters import (
            autofill as autofill_adapter,
        )

        monkeypatch.setattr(
            autofill_adapter.ai,
            "generate_autofilled_submission",
            lambda prompt: {FIELD_ID: EXPECTED_VALUE},
        )
        with user.page.expect_response("**/tasks/*/replace"):
            with web_app.test_request_context("/"):
                result = DeferredJobs.run(job.urlsafe_key)
        assert result.success is True

    refreshed = user.page.get_by_text(EXPECTED_VALUE, exact=True).last
    expect(refreshed).to_be_visible()
    expect(form).not_to_have_attribute("data-autofill-probe", "mounted")
    expect(form.locator("[data-role='deferred-progress']")).not_to_be_attached()
    expect(form.locator("[data-role='submit-group']")).to_be_attached()
    expect(form.locator("[data-role='autofill']")).to_be_attached()
    expect(form.locator("[data-role='autofill-submit-group']")).to_be_attached()
