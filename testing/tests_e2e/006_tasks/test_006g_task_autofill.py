"""Deferred task autofill stories grounded in task-specific files."""

from dataclasses import replace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import DeferredJobStatus, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from testing.definitions import Pages, Tasks, Users
from testing.resources import Page, Task
from testing.utility.live_ai import run_hosted_autofill
from testing.utility.network import scoped_browser_route


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
def test_autofill_start_snapshots_draft_and_stages_file_without_saving_them(get_user):
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
    assert FIELD_ID not in stored.properties.submission.value
    assert not stored.files
    assert job.parameters["upload_record"]
    expect(field).to_have_value("Current unsaved answer")
    expect(field).to_be_enabled()
    expect(form.locator("[data-role='submit-group']")).to_be_visible()

    with user.page.expect_response("**/pages/*/tasks") as initial_form:
        user.page.reload()
    assert response["operation"] in initial_form.value.text(), "Initial form HTML must identify running autofill"
    form = task.task_form
    expect(form.locator("[data-role='form-operation']")).to_contain_text("running")
    field = form.locator(f"[name='{FIELD_ID}']")
    field.fill("Edit while autofill runs")
    with user.page.expect_response("**/operations/*/cancel") as cancelled:
        form.locator("[data-role='autofill-cancel']").click()
    assert cancelled.value.ok, cancelled.value.text()
    expect(field).to_have_value("Edit while autofill runs")
    expect(field).to_be_enabled()
    assert Entities.fetch_one(job.key, request=Fetch.direct()).status == "cancelled"
    stored = Entities.fetch_one(task.entity.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    assert FIELD_ID not in stored.properties.submission.value
    assert not stored.files
    with user.page.expect_response("**/tasks/*/update") as saved_response:
        form.locator("[data-role='submit-group'] button[type='submit']").click()
    assert saved_response.value.ok, saved_response.value.text()
    stored = Entities.fetch_one(task.entity.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    assert stored.properties.submission.value[FIELD_ID] == "Edit while autofill runs"
    assert not stored.files


# @source lagniappe/web/deferred_autofill.py::start_deferred_autofill
# @source lagniappe/core/tools/deferred_jobs/autofill.py::autofill_job_spec
# @template pages/tasks.html::task_form
# @matrix ai tasks : autofill retry original-prompt staged-upload current-answers
def test_cancelled_autofill_retry_reuses_prompt_and_file_with_current_draft(get_user):
    user = get_user(Users.OWNER)
    page, task = _create_autofill_fixture(user)
    user.go(page, query_params={"tab": "tasks"})
    form = task.task_form
    field = form.locator(f"[name='{FIELD_ID}']")
    field.fill("First draft")
    form.locator("[data-role='show-autofill']").click()
    prompt = "Use the original staged evidence and leave unsupported fields unchanged."
    form.locator("textarea[name='autofill-description']").fill(prompt)
    form.locator("input[name='autofill-file']").set_input_files({
        "name": "retry-evidence.txt", "mimeType": "text/plain", "buffer": b"Original retry evidence",
    })
    with user.page.expect_response("**/tasks/*/update") as started:
        form.locator("[data-role='autofill-submit']").click()
    first_response = started.value.json()
    assert started.value.ok, first_response
    first = Entities.fetch_one(first_response["operation"], request=Fetch.direct())
    assert first.parameters["user_context"] == prompt
    assert first.parameters["snapshot"]["prompt"]["user_context"] == prompt
    upload_record = first.parameters["upload_record"]
    assert upload_record

    with user.page.expect_response("**/operations/*/cancel") as cancelled:
        form.locator("[data-role='autofill-cancel']").click()
    assert cancelled.value.ok, cancelled.value.text()
    field.fill("Current retry draft")
    retry = form.locator("[data-role='autofill-retry']")
    expect(retry).to_be_visible()
    with user.page.expect_response("**/tasks/*/update") as restarted:
        retry.click()
    retry_response = restarted.value.json()
    assert restarted.value.ok, retry_response
    assert retry_response["operation"] != first_response["operation"]
    second = Entities.fetch_one(retry_response["operation"], request=Fetch.direct())
    assert second.parameters["user_context"] == prompt
    assert second.parameters["snapshot"]["prompt"]["user_context"] == prompt
    assert second.parameters["upload_record"] == upload_record
    assert second.parameters["snapshot"]["prompt"]["submission"][FIELD_ID] == "Current retry draft"


# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.apply_proposal
# @source lagniappe/web/routes/tools/main.py::refine_autofill
# @source src/script/forms/revisions/modals.mjs::FormRevisionModal
# @source lagniappe/web/deferred_autofill.py::form_state
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
        modal.get_by_role("button", name="Revise suggestions with AI", exact=True).click()
    private = revised.value.json()
    assert revised.value.ok, private
    expect(modal).not_to_be_attached()
    expect(form.locator("[data-role='form-operation']")).to_contain_text("running")
    expect(form.get_by_role("button", name="Cancel autofill", exact=True)).to_be_visible()
    monkeypatch.setattr(adapter.ai_autofill, "generate_autofilled_submission", lambda *args, **kwargs: {FIELD_ID: "Private revision"})
    with web_app.test_request_context("/"):
        result = DeferredJobs.run(private["operation"])
    assert result.success, result.error
    saved = Entities.fetch_one(task.entity.key, request=Fetch.direct())
    assert FIELD_ID not in saved.properties.submission.value
    expect(form.locator("[data-role='form-operation']")).to_be_hidden(timeout=25000)
    form.locator("[data-role='edited-reset']").click()
    modal = user.page.locator("#modal")
    modal.get_by_role("radio", name="Revised suggestion for Text Field", exact=True).click()
    modal.get_by_role("button", name="Use selected values", exact=True).click()
    expect(form.locator(f"[name='{FIELD_ID}']")).to_have_value("Private revision")
    expect(form.locator("[data-role='form-operation']")).to_be_hidden()
    expect(form.locator("[lp-edited-marker]")).to_have_attribute("data-visible", "false")
    assert FIELD_ID not in Entities.fetch_one(task.entity.key, request=Fetch.direct()).properties.submission.value
    with user.page.expect_response("**/tasks/*/update") as saved_response:
        form.locator("[data-role='submit-group'] button[type='submit']").click()
    assert saved_response.value.ok, saved_response.value.text()
    assert Entities.fetch_one(task.entity.key, request=Fetch.direct()).properties.submission.value[FIELD_ID] == "Private revision"
    expect(form.locator("[data-role='form-operation']")).to_be_hidden()
    user.page.reload()
    form = task.task_form
    expect(form.locator("[data-role='form-operation']")).to_be_hidden()
    expect(form.locator("[lp-edited-marker]")).to_have_attribute("data-visible", "false")


# @source src/script/forms/revisions/modals.mjs::FormRevisionModal
# @source src/script/widgets/base/formWidget.mjs::FormWidget.prepareLocalRevision
# @template pages/tasks.html::task_form
# @pair forms:autofill-review
def test_autofill_collection_review_applies_to_open_form_without_saving(get_user, monkeypatch):
    from lagniappe.web import app as web_app
    from lagniappe.core.tools.deferred_jobs.adapters import autofill as adapter

    user = get_user(Users.OWNER)
    page = Page(
        user=user,
        definition=replace(
            Pages.test_page_autofill.value.definition,
            name=f"Collection Autofill Page {uuid4().hex}",
        ),
    ).create()
    form_entity = Entities.FORM.create(
        {"name": f"Collection Autofill Form {uuid4().hex}", "form-type": "task"}
    )
    form_entity.schema = [
        {"id": "table-items", "title": "Line items", "type": "table", "columns": [
            {"id": "row-item", "title": "Item", "type": "input", "input": "text"},
            {"id": "row-count", "title": "Count", "type": "input", "input": "number"},
        ]},
        {"id": "todo-list", "title": "Checklist", "type": "todo"},
    ]
    form_entity.save()
    original = {
        "table-items": {"rows": [{"row-item": "Keeper kit", "row-count": 1}]},
        "todo-list": {"items": [
            {"text": "Existing signed-off item", "checked": True},
            {"text": "Existing pending item", "checked": False},
        ]},
    }
    proposal = {
        "table-items": {"rows": [
            {"row-item": "Keeper kit", "row-count": 1},
            {"row-item": "Cable pack", "row-count": 2},
            {"row-item": "Adapter", "row-count": 1},
        ]},
        "todo-list": {"items": [
            {"text": "Existing signed-off item", "checked": True},
            {"text": "Existing pending item", "checked": False},
            {"text": "Pack cable labels", "checked": False},
            {"text": "Photograph the adapter", "checked": False},
        ]},
    }
    task_entity = Entities.TASK.create(
        {"name": f"Collection Autofill Task {uuid4().hex}", "page": page.entity, "form": form_entity}
    )
    task_entity = Entities.fetch_one(
        task_entity,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    task_entity.submission = original
    task_entity.save()
    task = Task(user=user)
    task.entity = task_entity

    user.go(page, query_params={"tab": "tasks"})
    task_form = task.task_form
    task_form.locator("[data-role='show-autofill']").click()
    with user.page.expect_response("**/tasks/*/update") as started:
        task_form.locator("[data-role='autofill-submit']").click()
    response = started.value.json()
    assert started.value.ok, response
    monkeypatch.setattr(adapter.ai_autofill, "generate_autofilled_submission", lambda *args, **kwargs: proposal)
    with web_app.test_request_context("/"):
        result = DeferredJobs.run(response["operation"])
    assert result.success, result.error

    expect(task_form.locator("[data-role='edited-message']")).to_contain_text(
        "Autofill is complete", timeout=25000
    )
    task_form.locator("[data-role='edited-reset']").click()
    modal = user.page.locator("#modal")
    expect(modal.get_by_role("radio", name="Autofill suggestion for Line items")).to_have_attribute(
        "aria-checked", "true"
    )
    expect(modal.get_by_role("radio", name="Autofill suggestion for Checklist")).to_have_attribute(
        "aria-checked", "true"
    )
    modal.get_by_role("button", name="Use selected values", exact=True).click()
    expect(modal).to_have_count(0)
    task_form = task.task_form
    expect(task_form.locator("[id^='table-items-'].form-element tbody tr[data-index]")).to_have_count(3)
    expect(task_form.locator("[id^='todo-list-'].form-element li[data-index]")).to_have_count(4)
    assert Entities.fetch_one(task.entity.key, request=Fetch.direct()).properties.submission.value == original


# @source lagniappe/web/deferred_autofill.py::staged_upload_for_update
# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.apply_proposal
# @matrix ai files tasks : autofill rejected-suggestion staged-upload-cleanup
@pytest.mark.parametrize("accept", [False, True], ids=["reject", "failed-save-then-accept"])
def test_rejecting_file_backed_suggestion_discards_staged_upload_on_update(get_user, monkeypatch, browser_failures, accept):
    from lagniappe.web import app as web_app
    from lagniappe.core.tools.deferred_jobs.adapters import autofill as adapter

    user = get_user(Users.OWNER)
    page, task = _create_autofill_fixture(user)
    user.go(page, query_params={"tab": "tasks"})
    form = task.task_form
    field = form.locator(f"[name='{FIELD_ID}']")
    field.fill("Human draft")
    form.locator("[data-role='show-autofill']").click()
    form.locator("input[name='autofill-file']").set_input_files({
        "name": "discard-me.txt", "mimeType": "text/plain", "buffer": b"Unselected autofill evidence",
    })
    with user.page.expect_response("**/tasks/*/update") as started:
        form.locator("[data-role='autofill-submit']").click()
    response = started.value.json()
    assert started.value.ok, response
    job = Entities.fetch_one(response["operation"], request=Fetch.direct())
    record = job.parameters["upload_record"]
    monkeypatch.setattr(adapter.ai_autofill, "generate_autofilled_submission", lambda *args, **kwargs: {FIELD_ID: "AI suggestion"})
    with web_app.test_request_context("/"):
        result = DeferredJobs.run(job.urlsafe_key)
    assert result.success, result.error
    expect(form.locator("[data-role='edited-message']")).to_contain_text("Autofill is complete", timeout=25000)
    form.locator("[data-role='edited-reset']").click()
    modal = user.page.locator("#modal")
    modal.get_by_role("radio", name=f"{'Autofill suggestion' if accept else 'Value in this tab'} for Text Field", exact=True).click()
    modal.get_by_role("button", name="Use selected values", exact=True).click()
    if accept:
        from flask_login import login_user
        from lagniappe.core.exceptions import ValidationError
        original_save = Entities.save
        attempted_assets = []
        def fail_update(*entities):
            if any(entity.key == task.entity.key for entity in entities):
                attempted_assets.extend(entity.assets["file"] for entity in entities if isinstance(entity, Entities.FILE))
                raise ValidationError("The test interrupted this Update. Try again.")
            return original_save(*entities)
        def interrupted_update(route):
            # Run the browser's actual command through the route in the process
            # that owns the failing storage boundary, then let the UI retry it.
            with web_app.test_request_context(
                f"/tasks/{task.key}/update", method="PUT",
                data=route.request.post_data_buffer,
                content_type=route.request.headers["content-type"],
            ):
                login_user(user.entity)
                result = web_app.make_response(web_app.view_functions["tasks.update"](key=task.key))
                route.fulfill(status=result.status_code, content_type=result.content_type, body=result.get_data(as_text=True))
        with monkeypatch.context() as failed_save:
            failed_save.setattr(Entities, "save", fail_update)
            # The service worker sends mutations, so intercept its context.
            with scoped_browser_route(user.page.context, f"**/tasks/{task.key}/update", interrupted_update), browser_failures.expect_http_error(user, status=422, path=f"/tasks/{task.key}/update"):
                with user.page.expect_console_message(predicate=lambda message: "status of 422 " in message.text), user.page.expect_response("**/tasks/*/update") as failure:
                    form.locator("[data-role='submit-group'] button[type='submit']").click()
                assert failure.value.status == 422
        assert storage_assets.verify_direct_upload(record, max_age=None)
        assert len(attempted_assets) == 1
        assert storage_assets.file_size(attempted_assets[0]["path"], attempted_assets[0].get("visibility", "private")) is None
        unchanged = Entities.fetch_one(task.entity.key, request=Fetch.direct())
        assert unchanged.db.get("autofill_reviews"), "Failed Update must preserve the review for retry"
        assert not unchanged.files
    with user.page.expect_response("**/tasks/*/update") as saved_response:
        form.locator("[data-role='submit-group'] button[type='submit']").click()
    assert saved_response.value.ok, saved_response.value.text()
    stored = Entities.fetch_one(task.entity.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    assert stored.properties.submission.value[FIELD_ID] == ("AI suggestion" if accept else "Human draft")
    assert len(stored.files) == (1 if accept else 0)
    with pytest.raises(storage_assets.DirectUploadError):
        storage_assets.verify_direct_upload(record, max_age=None)
    with user.page.expect_response("**/tasks/*/update") as repeated_update:
        form.locator("[data-role='submit-group'] button[type='submit']").click()
    assert repeated_update.value.ok, repeated_update.value.text()


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
