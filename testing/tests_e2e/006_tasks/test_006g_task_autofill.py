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
from testing.utility.live_ai import run_hosted_autofill


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


# @source lagniappe/web/deferred_autofill.py::form_state
# @source lagniappe/web/deferred_autofill.py::form_fingerprint
# @source lagniappe/web/routes/tools/main.py::cancel_generation
# @source lagniappe/core/tools/deferred_jobs/autofill.py::start_autofill_job
# @template pages/tasks.html::task_form
# @matrix ai tasks : autofill cancellation current-answers reload attachment
def test_autofill_start_saves_current_draft_and_file_and_cancel_keeps_them(get_user):
    user = get_user(Users.OWNER)
    page, task = _create_autofill_fixture(user)
    user.go(page, query_params={"tab": "tasks"})
    form = task.task_form
    field = form.locator(f"[name='{FIELD_ID}']")
    field.fill("Current unsaved answer")
    form.locator("[data-role='show-autofill']").click()
    form.locator("input[name='autofill-file']").set_input_files({
        "name": "current-evidence.txt", "mimeType": "text/plain", "buffer": b"New original evidence, not a summary",
    })
    with user.page.expect_response("**/tasks/*/update") as started:
        form.locator("[data-role='autofill-submit']").click()
    response = started.value.json()
    assert started.value.ok, response
    job = Entities.fetch_one(response["operation"], request=Fetch.direct())
    assert job.parameters["snapshot"]["prompt"]["submission"][FIELD_ID] == "Current unsaved answer"
    stored = Entities.fetch_one(task.entity.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    assert stored.properties.submission.value[FIELD_ID] == "Current unsaved answer"
    assert job.parameters["file_key"] in [file.urlsafe_key for file in stored.files]
    expect(field).to_be_enabled()
    expect(form.locator("[data-role='submit-group']")).to_be_visible()

    with user.page.expect_response("**/pages/*/tasks") as initial_form:
        user.page.reload()
    assert response["operation"] in initial_form.value.text(), "Initial form HTML must identify running autofill"
    form = task.task_form
    expect(form.locator("[data-role='form-operation']")).to_contain_text("running")
    field = form.locator(f"[name='{FIELD_ID}']")
    form.locator(f"[id^='{FIELD_ID}'].form-element [data-role='edit']").click()
    field.fill("Edit while autofill runs")
    with user.page.expect_response("**/operations/*/cancel") as cancelled:
        form.locator("[data-role='autofill-cancel']").click()
    assert cancelled.value.ok, cancelled.value.text()
    expect(field).to_have_value("Edit while autofill runs")
    expect(field).to_be_enabled()
    assert Entities.fetch_one(job.key, request=Fetch.direct()).status == "cancelled"
    stored = Entities.fetch_one(task.entity.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    assert stored.properties.submission.value[FIELD_ID] == "Current unsaved answer"
    assert job.parameters["file_key"] in [file.urlsafe_key for file in stored.files]


# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.apply_proposal
# @source lagniappe/web/routes/tools/main.py::refine_autofill
# @source src/script/forms/revisions/modals.mjs::FormRevisionModal
# @template pages/tasks.html::task_form
# @matrix ai tasks : autofill conflicts review private-refinement
# @pair forms:submission-choice
def test_autofill_completion_reviews_open_draft_and_refinement_waits_for_save(get_user, monkeypatch):
    from lagniappe.web import app as web_app
    from lagniappe.core.tools.deferred_jobs.adapters import autofill as adapter

    user = get_user(Users.OWNER)
    page, task = _create_autofill_fixture(user)
    user.go(page, query_params={"tab": "tasks"})
    form = task.task_form
    field = form.locator(f"[name='{FIELD_ID}']")
    field.fill("Launch answer")
    form.locator("[data-role='show-autofill']").click()
    with user.page.expect_response("**/tasks/*/update") as started:
        form.locator("[data-role='autofill-submit']").click()
    response = started.value.json()
    assert started.value.ok, response
    field.fill("My later draft")
    monkeypatch.setattr(adapter.ai_autofill, "generate_autofilled_submission", lambda *args, **kwargs: {FIELD_ID: "Autofill suggestion"})
    with web_app.test_request_context("/"):
        result = DeferredJobs.run(response["operation"])
    assert result.success, result.error
    expect(form.locator("[data-role='edited-message']")).to_contain_text("Autofill is complete", timeout=25000)
    expect(field).to_have_value("My later draft")
    form.locator("[data-role='edited-reset']").click()
    modal = user.page.locator("#modal")
    modal.get_by_label("Revise these values with AI").fill("Use the selected draft and improve the wording")
    with user.page.expect_response("**/autofill/*/revise") as revised:
        modal.get_by_role("button", name="Revise suggestions", exact=True).click()
    private = revised.value.json()
    assert revised.value.ok, private
    modal.get_by_role("button", name="Close", exact=True).click()
    monkeypatch.setattr(adapter.ai_autofill, "generate_autofilled_submission", lambda *args, **kwargs: {FIELD_ID: "Private revision"})
    with web_app.test_request_context("/"):
        result = DeferredJobs.run(private["operation"])
    assert result.success, result.error
    saved = Entities.fetch_one(task.entity.key, request=Fetch.direct())
    assert saved.properties.submission.value[FIELD_ID] == "Autofill suggestion"
    expect(form.locator("[data-role='form-operation']")).to_be_hidden(timeout=25000)
    form.locator("[data-role='edited-reset']").click()
    modal = user.page.locator("#modal")
    modal.get_by_role("radio", name="Your revised suggestion for Text Field", exact=True).click()
    modal.get_by_role("button", name="Use selected values", exact=True).click()
    expect(form.locator(f"[name='{FIELD_ID}']")).to_have_value("Private revision")
    assert Entities.fetch_one(task.entity.key, request=Fetch.direct()).properties.submission.value[FIELD_ID] == "Autofill suggestion"
    with user.page.expect_response("**/tasks/*/update") as saved_response:
        form.locator("[data-role='submit-group'] button[type='submit']").click()
    assert saved_response.value.ok, saved_response.value.text()
    assert Entities.fetch_one(task.entity.key, request=Fetch.direct()).properties.submission.value[FIELD_ID] == "Private revision"


# @matrix ai : attached-files autofill completion-refresh deferred
# @matrix deferred-jobs : cloud-tasks hosted-e2e oidc process-route provider-delivery
# @matrix notifications tasks : autofill deferred
# @template pages/tasks.html::task_form
@pytest.mark.ai
@pytest.mark.parametrize("live_ai_job_quota", [False, True], indirect=True, ids=["live", "quota-fallback"])
def test_task_autofill_runs_deferred_with_page_file_context(get_user, monkeypatch, results, live_ai_job_quota):
    user = get_user(Users.OWNER)
    page, task = _create_autofill_fixture(user)
    evidence_file = _attach_task_evidence(task)
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
    progress = form.locator("[data-role='form-operation']")
    expect(progress).to_be_visible()
    expect(progress).to_contain_text("running")
    expect(form.locator("[data-role='submit-group']")).to_be_visible()
    expect(form).to_have_attribute("data-autofill-probe", "mounted")
    expect(form.locator(f"[name='{FIELD_ID}']")).to_be_enabled()

    if CONFIG.hosted_e2e_runner or live_ai_job_quota:
        def verify_submission():
            evidence = Entities.fetch_one(evidence_file.key, request=Fetch.direct())
            assert EXPECTED_VALUE in evidence.summary
            results.record("independent_workspace_verification", {"file": evidence.urlsafe_key, "summary": evidence.summary})
            return {FIELD_ID: EXPECTED_VALUE}
        completed = run_hosted_autofill(user, job, results=results, verify_submission=verify_submission)
        assert completed.status == DeferredJobStatus.SUCCEEDED.value
        user.page.reload()
        form = task.task_form
    else:
        from lagniappe.web import app as web_app
        from lagniappe.core.tools.deferred_jobs.adapters import (
            autofill as autofill_adapter,
        )

        monkeypatch.setattr(
            autofill_adapter.ai_autofill,
            "generate_autofilled_submission",
            lambda prompt, **kwargs: {FIELD_ID: EXPECTED_VALUE},
        )
        with user.page.expect_response("**/tasks/*/replace"):
            with web_app.test_request_context("/"):
                result = DeferredJobs.run(job.urlsafe_key)
        assert result.success is True

    expect(form.locator("[data-role='edited-message']")).to_contain_text("Autofill is complete")
    form.locator("[data-role='edited-reset']").click()
    user.page.get_by_role("button", name="Use selected values", exact=True).click()
    expect(form.locator(f"[name='{FIELD_ID}']")).to_have_value(EXPECTED_VALUE)
    expect(form.locator("[data-role='form-operation']")).to_be_hidden()
    expect(form.locator("[data-role='submit-group']")).to_be_attached()
    expect(form.locator("[data-role='autofill']")).to_be_attached()
    expect(form.locator("[data-role='autofill-submit-group']")).to_be_attached()
