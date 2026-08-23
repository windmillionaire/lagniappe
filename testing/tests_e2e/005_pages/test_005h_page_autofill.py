from dataclasses import replace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import DeferredJobStatus, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from testing.definitions import Pages, Users
from testing.resources import Page
from testing.utility import expect_poll_result
from testing.utility.hosted_deferred_jobs import dispatch_hosted_deferred_job


pytestmark = pytest.mark.e2e
FIELD_ID = "input-textab12"
FILE_SUMMARY = "Parcel 123 is assessed at $245,000 from the attached report."
EXPECTED_VALUE = "$245,000"


def _attach_evidence(page):
    file = Entities.FILE.create(
        page=page.entity,
        data={"name": "Assessment Evidence", "summary": FILE_SUMMARY},
    )
    file.filename = "assessment.pdf"
    file.mimetype = "application/pdf"
    file.save()
    return file


# @pairs ai:autofill ai:deferred ai:attached-files ai:completion-refresh
# @pairs pages:autofill pages:deferred
# @pairs notifications:autofill notifications:deferred
# @pairs deferred-jobs:form-lock deferred-jobs:conflict deferred-jobs:reload
# @pairs deferred-jobs:refresh deferred-jobs:form-schema
# @pairs deferred-jobs:process-route deferred-jobs:cloud-tasks deferred-jobs:oidc
# @pairs deferred-jobs:provider-delivery deferred-jobs:hosted-e2e
# @pairs pages:refresh pages:form-schema
# @template pages/info.html::info_form
@pytest.mark.ai
def test_page_autofill_runs_deferred_with_attached_file_context(
    get_user, monkeypatch, browser_failures
):
    user = get_user(Users.OWNER)
    page = Page(
        user=user,
        definition=replace(
            Pages.test_page_autofill.value.definition,
            name=f"Autofill Evidence Page {uuid4().hex}",
        ),
    ).create()
    _attach_evidence(page)
    user.go(page)

    form = page.info_form
    expect(form).to_have_attribute("lp-deferred", "")
    expect(form).to_have_attribute("data-destination", "info:PageInfo")
    form.locator("[data-role='show-autofill']").click()
    form.locator("input[name='autofill-file']").set_input_files(
        {
            "name": "autofill-context.txt",
            "mimeType": "text/plain",
            "buffer": b"Assessment context uploaded for autofill.",
        }
    )
    form.locator("textarea[name='autofill-description']").fill(
        "Read the attached assessment evidence and set Text Field to exactly "
        "the assessed value, including the dollar sign and comma."
    )

    submit = form.locator("button[data-role='autofill-submit']")
    with user.page.expect_response("**/pages/*/update") as response_info:
        submit.click()
    payload = response_info.value.json()
    job = Entities.fetch_one(payload["operation"], request=Fetch.direct())
    assert job.status == DeferredJobStatus.QUEUED.value
    progress = form.locator("[data-role='deferred-progress']")
    expect(progress).to_be_visible()
    expect(progress.locator("[data-role='deferred-phase']")).not_to_have_text("")
    expect(form.locator(f"[name='{FIELD_ID}']")).to_be_disabled()

    with expect_poll_result(
        user.page,
        subscription_id=f"lock:{page.key}",
        timeout=25_000,
    ):
        user.page.reload()
    form = user.page.locator("[data-widget='PageInfo']")
    expect(form).to_have_attribute("initialized", "")
    expect(form).to_have_attribute("data-operation", payload["operation"])
    expect(form.locator("[data-role='deferred-progress']")).to_be_visible()
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
                return response.status;
            }""",
            {"path": update_path, "name": "Blocked while autofill owns the form"},
        )
    assert locked_update == 409
    expect(form.locator("input[name='name']")).to_have_value(original_name)

    if CONFIG.hosted_e2e_runner:
        completed, attempts = dispatch_hosted_deferred_job(user.page, job)
        assert completed.status == DeferredJobStatus.SUCCEEDED.value, attempts
        user.page.reload()
        form = user.page.locator("[data-widget='PageInfo']")
        expect(form).to_have_attribute("initialized", "")
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
        with user.page.expect_response("**/pages/*/info/replace"):
            with web_app.test_request_context("/"):
                result = DeferredJobs.run(job.urlsafe_key)
        assert result.success is True

    expect(form.locator(f"[name='{FIELD_ID}']")).to_have_value(EXPECTED_VALUE)
    expect(form.locator("[data-role='deferred-progress']")).not_to_be_attached()
    expect(form.locator("[data-role='submit-group']")).to_be_attached()
    expect(form.locator("[data-role='autofill']")).to_be_attached()
