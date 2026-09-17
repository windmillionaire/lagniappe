"""Deterministic form changes through the actual builder Save and deferred runner."""

import json
from uuid import uuid4

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.schema_fields import SchemaField, SchemaFields
from testing.elements.combobox import Select
from testing.resources.form import Form
from testing.resources.task import Task as TaskResource
from testing.utility.network import assert_lagniappe_error_response, expect_successful_response, manual_mutation_headers
from testing.utility.polling import expect_poll_result
from testing.utility.offline import wait_for_offline_mutations

pytestmark = pytest.mark.e2e


# @source lagniappe/core/tools/deferred_jobs/adapters/form_change.py::FormChangeAdapter
# @source lagniappe/core/tools/form_changes.py::apply_target
# @matrix form-migration : preflight batch-job publication recovery partial-read generation removed-link
def test_three_submission_migration_resumes_durable_cursors_and_replayed_batch(get_user, monkeypatch):
    from flask_login import login_user
    from lagniappe.web import app as web_app
    from lagniappe.core.tools import form_changes, form_drafts
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
    from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext
    from lagniappe.core.tools.deferred_jobs.adapters.form_change import FormChangeAdapter
    from lagniappe.core.tools.deferred_jobs.errors import DeferredJobInfrastructureError
    from lagniappe.core.tools.deferred_jobs.locks import deferred_job_lock_key

    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    quantity = SchemaFields.TEXT_INPUT.get(_id="quantity", title="Quantity")
    link = SchemaFields.LINK.get(_id="reference", title="Reference", location="in")
    referenced = Pages.acl_lab_visible.get(user)
    form = Form(user=user, definition=FormDefinition(
        name=f"Cursor recovery {uuid4().hex[:8]}", form_type="task", schema=(quantity, link),
    )).create()
    tasks = []
    for index, value in enumerate(("007", "008", "009")):
        task = Entities.TASK.create({
            "name": f"Cursor target {index}", "page": parent.entity, "form": form.entity,
            "submission": {"quantity": value, "reference": referenced.entity.details},
        })
        task = Entities.fetch_one(task, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
        task.save_submission()
        if index == 1:
            task.complete(user=user.entity)
        task.save()
        assert referenced.entity.key in task.derived_page_keys
        assert referenced.entity.key in task.properties.linked_pages.keys
        tasks.append(task)
    original_completion = tasks[1].db["completed_submission"]
    draft = form_drafts.builder_draft(form.entity)
    draft["schema"][0]["input"] = "number"
    draft["schema"] = draft["schema"][:1]
    draft["migration"] = {"version": 1, "clear_invalid": True}
    monkeypatch.setattr(form_changes, "BATCH_SIZE", 2)
    with monkeypatch.context() as held:
        held.setattr(DeferredJobs, "dispatch", lambda *args, **kwargs: "held")
        with web_app.test_request_context("/"):
            login_user(user.entity)
            change = form_changes.start_change(form.entity, draft, str(uuid4()), user.entity)
    operation = change["pending_change"]["operation"]
    checkpoint_stage = DeferredJobContext.checkpoint_stage
    batches = []
    target_batch = form_changes.target_batch

    def track_batch(form, cursor=None):
        batch = target_batch(form, cursor)
        batches.append((cursor, batch.next_cursor, [row.key for row in batch]))
        return batch

    monkeypatch.setattr(form_changes, "target_batch", track_batch)

    def interrupt_check(context, stage, payload=None, **progress):
        result = checkpoint_stage(context, stage, payload, **progress)
        if stage == "checking" and payload.get("check_cursor"):
            raise DeferredJobInfrastructureError("Test worker interrupted after checking checkpoint")
        return result

    def run():
        with web_app.test_request_context("/"):
            login_user(user.entity)
            return DeferredJobs.run(operation)

    with monkeypatch.context() as stopped:
        stopped.setattr(DeferredJobContext, "checkpoint_stage", interrupt_check)
        with pytest.raises(DeferredJobInfrastructureError, match="after checking"):
            run()
    saved_job = Entities.fetch_one(operation, request=Fetch.root())
    check_cursor = saved_job.checkpoint["check_cursor"]
    assert check_cursor and saved_job.checkpoint["checked"] == 2
    assert all(Entities.fetch_one(task.key, request=Fetch.root()).generation == 0 for task in tasks)

    def interrupt_apply(context, stage, payload=None, **progress):
        if stage == "applying" and payload.get("apply_cursor"):
            raise DeferredJobInfrastructureError("Test worker interrupted before applying checkpoint")
        return checkpoint_stage(context, stage, payload, **progress)

    with monkeypatch.context() as stopped:
        stopped.setattr(DeferredJobContext, "checkpoint_stage", interrupt_apply)
        with pytest.raises(DeferredJobInfrastructureError, match="before applying"):
            run()
    assert batches[1][0] == check_cursor
    saved_job = Entities.fetch_one(operation, request=Fetch.root())
    assert saved_job.checkpoint["validated"] is True
    assert not saved_job.checkpoint.get("apply_cursor")
    partial = [Entities.fetch_one(task.key, request=Fetch.direct()) for task in tasks]
    assert sorted(task.generation for task in partial) == [0, 1, 1]
    for task in partial:
        field = task.properties.submission.fields["quantity"]
        assert field.schema["input"] == ("number" if task.generation else "text")
        assert isinstance(field.value, (int, float) if task.generation else str)
    pending = Entities.fetch_one(form.key, request=Fetch.root())
    assert pending.generation == 0 and pending.db[form_changes.PENDING]
    first_notices = {task.key: task.db[form_changes.NOTICE] for task in partial if task.generation}
    published = []
    publish = FormChangeAdapter.publish

    def track_publish(adapter, context):
        publish(adapter, context)
        published.append(context.parameters["change_id"])

    monkeypatch.setattr(FormChangeAdapter, "publish", track_publish)
    assert run().success is True
    assert run().success is True  # A duplicate delivery must not publish twice.
    assert len(published) == 1
    assert max(len(keys) for _, _, keys in batches) == 2
    assert any(cursor for cursor, _, _ in batches[2:])
    for task, value in zip(tasks, (7, 8, 9)):
        stored = Entities.fetch_one(task.key, request=Fetch.direct())
        assert stored.generation == 1
        assert stored.properties.submission.value == {"quantity": value}
        assert referenced.entity.key not in stored.derived_page_keys
        assert referenced.entity.key not in stored.properties.linked_pages.keys
        assert json.loads(stored.db[form_changes.NOTICE])["quantity"]["value"] == f"00{value}"
        if task.key in first_notices:
            assert stored.db[form_changes.NOTICE] == first_notices[task.key]
        if task.completed:
            assert stored.completed
            assert stored.db["completed_submission"] == original_completion
    published_form = Entities.fetch_one(form.key, request=Fetch.root())
    assert published_form.generation == 1 and not published_form.db.get(form_changes.PENDING)
    assert Entities.fetch_one(deferred_job_lock_key(published_form, "form-change"), request=Fetch.root()) is None


# @source lagniappe/core/mixins/submitter.py::SubmitterMixin.form_submission
# @source lagniappe/web/routes/tasks/main.py::update
# @matrix form-migration : stale-generation direct-write
def test_direct_stale_generation_write_is_rejected_after_migration(get_user, monkeypatch):
    from flask_login import login_user
    from lagniappe.web import app as web_app
    from lagniappe.core.tools import form_changes, form_drafts
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    quantity = SchemaFields.TEXT_INPUT.get(_id="quantity", title="Quantity")
    form = Form(user=user, definition=FormDefinition(
        name=f"Direct stale write {uuid4().hex[:8]}", form_type="task", schema=(quantity,),
    )).create()
    task = Entities.TASK.create({
        "name": "Stale request target", "page": parent.entity, "form": form.entity,
        "submission": {"quantity": "009"},
    })
    task.save()
    draft = form_drafts.builder_draft(form.entity)
    draft["schema"][0]["input"] = "number"
    draft["migration"] = {"version": 1, "clear_invalid": True}
    with monkeypatch.context() as held:
        held.setattr(DeferredJobs, "dispatch", lambda *args, **kwargs: "held")
        with web_app.test_request_context("/"):
            login_user(user.entity)
            change = form_changes.start_change(form.entity, draft, str(uuid4()), user.entity)
    with web_app.test_request_context("/"):
        login_user(user.entity)
        assert DeferredJobs.run(change["pending_change"]["operation"]).success
    resource = TaskResource(user=user)
    resource.entity = task
    user.go(resource)
    before = dict(Entities.fetch_one(task.key, request=Fetch.root()).db)
    headers = manual_mutation_headers(user.page.url, user.locate("#token").input_value())
    cookies = {cookie["name"]: cookie["value"] for cookie in user.page.context.cookies()}
    url = f"{SETTINGS.test_config['BASE_URL']}/tasks/{task.urlsafe_key}/update"
    response = requests.put(url, headers=headers, cookies=cookies, timeout=20, data={
        "active": "TaskForm", "form-generation": "0", "quantity": "666",
    })
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/plain")
    assert "The form fields changed. Your answers were not saved." in response.text
    assert dict(Entities.fetch_one(task.key, request=Fetch.root()).db) == before
    response = requests.put(url, headers=headers, cookies=cookies, timeout=20, data={
        "active": "TaskForm", "form-generation": "1", "quantity": "12",
    })
    assert response.status_code == 200
    stored = Entities.fetch_one(task.key, request=Fetch.root())
    assert stored.properties.submission.value == {"quantity": 12}
    assert not stored.db.get(form_changes.NOTICE)
    user.go(resource)
    expect(resource.task_form.get_by_text("12", exact=True)).to_be_visible()


# @matrix form-migration : form-authority restricted-submissions
@pytest.mark.parametrize("form_type", ["page", "task"])
def test_form_editor_migrates_restricted_submissions(get_user, form_type):
    owner = get_user(Users.OWNER)
    field = SchemaFields.TEXT_INPUT.get(_id="quantity", title="Quantity")
    form = Form(user=owner, definition=FormDefinition(
        name=f"Restricted submission migration {uuid4().hex[:8]}",
        form_type=form_type, schema=(field,),
    )).create()
    page = Entities.PAGE.create({
        "name": f"Private migration page {uuid4().hex[:8]}",
        **({"form": form.entity, "submission": {"quantity": "007"}}
           if form_type == "page" else {}),
    })
    page.properties.restricted_to.materialize(admin_only=True)
    page.save()
    target = page
    if form_type == "task":
        target = Entities.TASK.create({
            "name": "Private migration task", "page": page,
            "form": form.entity, "submission": {"quantity": "007"},
        })
        target.save()
    target = Entities.fetch_one(
        target.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    editor = get_user(Users.admin)
    assert not editor.entity.is_admin
    assert form.entity.allowed(Action.EDIT, user=editor.entity)
    assert not target.allowed(Action.VIEW, user=editor.entity)
    assert not target.allowed(Action.EDIT, user=editor.entity)
    original_requires = target.db["requires"]
    form.user = editor
    builder = form.builder
    builder.select_field(field)
    builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
    Select(builder.condition.locator("[data-combobox-id]")).select_by_name("Number")
    builder.condition.get_by_role("button", name="Convert", exact=True).click()
    with expect_successful_response(
        editor.page, method="PUT", path=f"/forms/{form.key}/update", timeout=60000,
    ):
        editor.locate(builder.SAVE_BUTTON).click()
    expect(editor.locate("[data-role='form-change-status']")).to_be_hidden(timeout=30000)
    current_form = Entities.fetch_one(form.key, request=Fetch.root())
    assert current_form.generation == 1
    assert not current_form.db.get("pending_form_change")
    converted = Entities.fetch_one(
        target.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    assert converted.properties.submission.value == {"quantity": 7}
    assert json.loads(converted.db["pre_migration"])["quantity"]["value"] == "007"
    assert converted.db["requires"] == original_requires
    assert not converted.allowed(Action.VIEW, user=editor.entity)
    cookies = {cookie["name"]: cookie["value"] for cookie in editor.page.context.cookies()}
    response = requests.get(
        f"{SETTINGS.test_config['BASE_URL']}/{form_type}s/{target.urlsafe_key}",
        cookies=cookies, allow_redirects=False, timeout=10,
    )
    assert response.status_code == 403
    expect(editor.locate(builder.FORM_NAME)).to_be_visible()


# @matrix task-completion : deleted-form generation raw-values
# @matrix form-migration : completed-task
# @template forms/builder.html::main
# @template pages/tasks.html::task_form
# @template tasks/history.html::completion_history
def test_deleted_migrated_form_retains_completed_submissions_and_history(get_user):
    user = get_user(Users.OWNER)
    parent = Pages.acl_lab_visible.get(user)
    quantity = SchemaFields.TEXT_INPUT.get(_id="quantity", title="Quantity")
    notes = SchemaFields.TEXTAREA.get(_id="notes", title="Notes")
    form = Form(user=user, definition=FormDefinition(
        name=f"Deleted completion form {uuid4().hex[:8]}", form_type="task",
        schema=(quantity, notes),
    )).create()
    before = Entities.TASK.create({
        "name": f"Completed before migration {uuid4().hex[:8]}",
        "page": parent.entity, "form": form.entity,
        "submission": {"quantity": "009", "notes": "Keep original notes"},
    })
    before = Entities.fetch_one(before, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    before.complete(user=user.entity)
    before.save()
    original_history = before.create_history_entry()
    before.save()

    builder = form.builder
    builder.select_field(quantity)
    builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
    Select(builder.condition.locator("[data-combobox-id]")).select_by_name("Number")
    builder.condition.get_by_role("button", name="Convert", exact=True).click()
    with expect_successful_response(
        user.page, method="PUT", path=f"/forms/{form.key}/update", timeout=60000,
    ):
        user.locate(builder.SAVE_BUTTON).click()
    expect(user.locate("[data-role='form-change-status']")).to_be_hidden(timeout=30000)
    current_form = Entities.fetch_one(form.key, request=Fetch.root())
    assert current_form.generation == 1
    before = Entities.fetch_one(before.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    modified_history = before.create_history_entry(submission_source="modified")
    before.save()
    after = Entities.TASK.create({
        "name": f"Completed after migration {uuid4().hex[:8]}",
        "page": parent.entity, "form": current_form,
        "submission": {"quantity": 12, "notes": "Keep newer notes"},
    })
    after = Entities.fetch_one(after, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    after.save()
    after.complete(user=user.entity)
    after.save()
    snapshots = {
        entity.key: {name: entity.db.get(name) for name in (
            "form", "submission", "generation", "completed_submission", "completed_on",
        )}
        for entity in (before, after, original_history, modified_history)
    }

    user.page.get_by_role("button", name="Form actions", exact=True).click()
    user.page.get_by_role("menuitem", name="Delete Form", exact=True).click()
    modal = user.page.locator("#modal")
    with expect_successful_response(
        user.page, method="DELETE", path=f"/forms/{form.key}/delete", timeout=60000,
    ):
        modal.get_by_role("button", name=f"Delete {form.definition.name}", exact=True).click()
    expect(modal).not_to_be_attached()
    assert Entities.fetch_one(form.key, request=Fetch.root()) is None

    # Ordinary reads show a warning; only the explicit link requests an archive.
    tasks = []
    archive_requests = []
    def track_archive(request):
        if request.url.endswith("/archived-submission"):
            archive_requests.append(request.url)

    user.page.on("request", track_archive)
    for entity, value, text in ((before, 9, "Keep original notes"), (after, 12, "Keep newer notes")):
        resource = TaskResource(user=user)
        resource.entity = entity
        user.go(resource)
        rendered = resource.task_form
        expect(rendered).to_have_attribute("data-completed", "true")
        warning = rendered.locator("[data-role='archived-submission-controls']")
        expect(warning).to_contain_text("This submission's form has been deleted.")
        expect(rendered.locator("input[name='quantity']")).to_have_count(0)
        assert len(archive_requests) == len(tasks)
        with expect_successful_response(
            user.page, method="GET", path=f"/tasks/{entity.urlsafe_key}/archived-submission",
        ) as loaded:
            warning.get_by_role("button", name="Load the archived version", exact=True).click()
        assert loaded.value.headers["cache-control"] == "no-store"
        assert loaded.value.json()["generation"] == 1
        assert loaded.value.json()["submission"]["quantity"] == value
        archived = warning.locator("[data-role='archived-submission-detail']")
        expect(archived.get_by_text(str(value), exact=True)).to_be_visible()
        expect(archived.get_by_text(text, exact=True)).to_be_visible()
        expect(rendered.locator("button[type='submit']")).to_have_count(0)
        tasks.append(resource)
    user.page.remove_listener("request", track_archive)
    user.go(tasks[0])
    rendered = tasks[0].task_form
    rendered.get_by_role("button", name="Load the archived version", exact=True).click()
    with expect_successful_response(
        user.page, method="GET", path=f"/tasks/{before.urlsafe_key}/completion-details",
    ):
        rendered.get_by_role("button", name="View Original Submission", exact=True).click()
    original = rendered.locator("[data-role='original-completion-detail']")
    expect(original.get_by_text("009", exact=True)).to_be_visible()
    expect(original.get_by_text("Keep original notes", exact=True)).to_be_visible()

    tasks[0]._close_task()
    with expect_successful_response(
        user.page, method="GET", path=f"/tasks/{before.urlsafe_key}/history",
    ):
        tasks[0].element.locator(TaskResource.TASK_HISTORY_TOGGLE).click()
    history = tasks[0].element.locator(TaskResource.TASK_HISTORY)
    for generation, value in ((0, "009"), (1, "9.00")):
        group = history.locator(f"[data-role='history-group'][data-generation='{generation}']")
        group.locator("[data-role='embedded-table-visibility']").click()
        columns = group.locator("[data-widget='TableVisibility']")
        columns.locator("input[name='quantity']").check()
        columns.locator("input[name='notes']").check()
        expect(group.locator("td[data-column='quantity']")).to_have_text(value)
        expect(group.locator("td[data-column='notes']")).to_have_text("Keep original notes")
    for key, snapshot in snapshots.items():
        stored = Entities.fetch_one(key, request=Fetch.root())
        assert {name: stored.db.get(name) for name in snapshot} == snapshot

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(tasks[1])
    readonly = tasks[1].task_form
    with expect_successful_response(
        viewer.page, method="GET", path=f"/tasks/{after.urlsafe_key}/archived-submission",
    ):
        readonly.get_by_role("button", name="Load the archived version", exact=True).click()
    expect(readonly.get_by_text("Keep newer notes", exact=True)).to_be_visible()
    expect(readonly.get_by_role("button", name="View Original Submission", exact=True)).to_have_count(0)
    expect(readonly.locator("button[type='submit']")).to_have_count(0)


# @matrix form-migration : stale-input queued-conflict explicit-review
# @template controls.html::edited_marker
# @template pages/tasks.html::task_form
@pytest.mark.parametrize("change", ["convert", "remove"])
def test_offline_submission_survives_schema_migration_until_review(
    get_user, browser_failures, change,
):
    owner = get_user(Users.OWNER)
    editor = get_user(Users.admin, creator=owner)
    parent = Pages.test_create_page_task.get(owner)
    quantity = SchemaFields.TEXT_INPUT.get(_id="quantity", title="Quantity")
    notes = SchemaFields.TEXTAREA.get(_id="notes", title="Notes")
    form = Form(user=owner, definition=FormDefinition(
        name=f"Offline migration {uuid4().hex[:8]}", form_type="task",
        schema=(quantity, notes),
    )).create()
    entity = Entities.TASK.create({
        "name": f"Queued migration {uuid4().hex[:8]}", "page": parent.entity,
        "form": form.entity, "submission": {"quantity": "009", "notes": "Keep this too"},
    })
    entity.save()
    task = TaskResource(user=owner)
    task.entity = entity
    owner.go(parent, query_params={"tab": "tasks"})
    task_form = task.task_form
    field = task_form.locator(".form-element:has(input[name='quantity'])")
    if not field.locator("input").is_visible():
        field.locator("[data-role='label']").click()
    field.locator("input").fill("unfinished")
    submit = task_form.locator("button[type='submit']:not([data-role])")
    mutation_id = f"update:task:{task.key}"
    try:
        # Reconnect probes keep pinging while the other browser saves the form.
        with browser_failures.expect_offline(owner, max_ping_count=12):
            owner.offline = True
            expect(owner.locate("[data-role='offline']")).to_be_visible()
            submit.click()
            expect(submit).to_contain_text("Queued Sync")
            wait_for_offline_mutations(owner, record_id=mutation_id, exact=1)

            form.user = editor
            builder = form.builder
            builder.select_field(quantity)
            builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
            if change == "convert":
                Select(builder.condition.locator("[data-combobox-id]")).select_by_name("Number")
                builder.condition.get_by_role("button", name="Convert", exact=True).click()
            else:
                builder.condition.get_by_role("button", name="Delete", exact=True).click()
            with expect_successful_response(
                editor.page, method="PUT", path=f"/forms/{form.key}/update", timeout=60000,
            ):
                editor.locate(builder.SAVE_BUTTON).click()
            expect(editor.locate("[data-role='form-change-status']")).to_be_hidden(timeout=30000)
            expected = {"notes": "Keep this too"}
            if change == "convert":
                expected["quantity"] = 9
            assert Entities.fetch_one(task.key, request=Fetch.root()).properties.submission.value == expected

            with expect_successful_response(
                owner.page, method="PUT", path=f"/tasks/{task.key}/update", timeout=30000,
            ) as replay:
                owner.offline = False
        assert replay.value.json()["conflict"] is True
        marker = task_form.locator("[lp-edited-marker]")
        expect(marker).to_be_visible()
        wait_for_offline_mutations(owner, record_id=mutation_id, exact=1)
        expect(field.locator("input")).to_have_value("unfinished")
        marker.get_by_role("button", name="Review values", exact=True).click()
        modal = owner.page.locator("#modal")
        expect(modal.get_by_text("unfinished", exact=True)).to_be_visible()
        local = modal.locator("[data-revision-source='local']")
        expect(local).to_be_disabled()
        modal.get_by_role("button", name="Update values", exact=True).click()
        expect(modal).not_to_be_attached()
        wait_for_offline_mutations(owner, record_id=mutation_id, exact=0)
        expect(submit).not_to_contain_text("Queued Sync")
        owner.page.reload()
        current_form = task.task_form
        if change == "convert":
            expect(current_form.locator("input[name='quantity']")).to_have_value("9")
        else:
            expect(current_form.locator("input[name='quantity']")).to_have_count(0)
        assert Entities.fetch_one(task.key, request=Fetch.root()).properties.submission.value == expected
    finally:
        owner.offline = False


# @matrix form-migration : progress reload saved-job
# @template forms/builder.html::main
def test_builder_observes_migration_completion_without_leaving(get_user, monkeypatch):
    from flask_login import login_user
    from lagniappe.web import app as web_app
    from lagniappe.core.tools import form_changes, form_drafts
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    notes = SchemaFields.TEXTAREA.get(_id="notes", title="Notes")
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Visible migration {uuid4().hex[:8]}", form_type="task",
            schema=(notes,),
        ),
    ).create()
    task = Entities.TASK.create({
        "name": "Delete notes", "page": parent.entity, "form": form.entity,
        "submission": {"notes": "Keep until the migration runs"},
    })
    task.save()
    draft = form_drafts.builder_draft(form.entity)
    draft["schema"] = []
    draft["migration"] = {"version": 1, "clear_invalid": True}
    with monkeypatch.context() as held_dispatch:
        held_dispatch.setattr(DeferredJobs, "dispatch", lambda *args, **kwargs: "held")
        with web_app.test_request_context("/"):
            login_user(user.entity)
            change = form_changes.start_change(form.entity, draft, str(uuid4()), user.entity)

    operation = change["pending_change"]["operation"]
    subscription = f"builder-change:{operation}"
    user.page.bring_to_front()
    with expect_poll_result(user.page, subscription_id=subscription):
        user.go(form)
    original_url = user.page.url
    status = user.locate("#notification [data-role='form-change-status']")
    expect(status).to_contain_text("Schema migration in progress")
    expect(user.locate("[data-role='save-form']")).to_be_disabled()
    # A quiet scheduled poll must keep checking while this page stays focused.
    with expect_poll_result(user.page, subscription_id=subscription, status="unchanged"):
        pass
    with expect_poll_result(user.page, subscription_id=subscription, status=None):
        with web_app.test_request_context("/"):
            login_user(user.entity)
            result = DeferredJobs.run(operation)
    assert result.success is True
    expect(status).to_be_hidden(timeout=30000)
    expect(user.locate("#notification")).to_have_text("Form update finished.")
    assert user.page.url == original_url
    assert not user.page.evaluate("document.hidden")
    assert user.page.evaluate("document.hasFocus()")
    assert Entities.fetch_one(task.key, request=Fetch.root()).properties.submission.value == {}


# @matrix tasks : active-widget complete uncomplete update-state
# @matrix form-migration : writer-fence completion-race
# @template pages/tasks.html::task
def test_completion_during_migration_returns_inline_error_without_saving(
    get_user, monkeypatch, browser_failures,
):
    from flask_login import login_user
    from lagniappe.web import app as web_app
    from lagniappe.core.tools import form_changes, form_drafts
    from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    field = SchemaFields.TEXT_INPUT.get(_id="quantity", title="Quantity")
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Locked completion {uuid4().hex[:8]}", form_type="task",
            schema=(field,),
        ),
    ).create()
    tasks = []
    for completed in (False, True):
        entity = Entities.TASK.create({
            "name": f"Locked {'completed' if completed else 'active'} task",
            "page": parent.entity, "form": form.entity,
            "submission": {"quantity": "7"},
        })
        entity = Entities.fetch_one(
            entity, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
        )
        if completed:
            entity.complete(user=user.entity)
        entity.save()
        task = TaskResource(user=user)
        task.entity = entity
        tasks.append(task)

    user.go(parent, query_params={"tab": "tasks"})
    parent.completed_task_list
    expect(tasks[1].task_form).to_be_visible()
    tasks[1]._close_task()
    original_url = user.page.url
    original_completion = tasks[1].entity.db["completed_submission"]

    # Keep a real saved migration pending while the browser sends both actions.
    draft = form_drafts.builder_draft(form.entity)
    draft["schema"][0]["input"] = "number"
    draft["migration"] = {"version": 1, "clear_invalid": True}
    with monkeypatch.context() as held_dispatch:
        held_dispatch.setattr(DeferredJobs, "dispatch", lambda *args, **kwargs: "held")
        with web_app.test_request_context("/"):
            login_user(user.entity)
            change = form_changes.start_change(form.entity, draft, str(uuid4()), user.entity)

    message = "This Form is being updated. These changes were not saved; try again when the update finishes."
    for task, completed in zip(tasks, (False, True)):
        row = task.element
        expect(row).to_have_attribute("data-open", "false")
        path = f"/tasks/{task.key}/update"
        with browser_failures.expect_http_error(user, status=422, path=path):
            with user.page.expect_response(
                lambda response: response.request.method == "PUT"
                and response.url.endswith(path)
            ) as rejected:
                row.locator("[data-role='complete-toggle']").click()
            assert rejected.value.status == 422
            assert rejected.value.headers["content-type"].startswith("text/plain")
            assert rejected.value.text() == message
            expect(row.locator("[lp-nav] [data-role='error']")).to_have_text(message)
            expect(row.locator("[lp-nav] [data-role='error']")).to_be_visible()
        assert user.page.url == original_url
        expect(row).to_have_attribute("data-completed", str(completed).lower())
        expect(row).to_have_attribute("data-open", "false")
        stored = Entities.fetch_one(task.key, request=Fetch.root())
        assert stored.completed is completed
        assert stored.properties.submission.value == {"quantity": "7"}
        assert not stored.db.get("history")
        if completed:
            assert stored.db["completed_submission"] == original_completion

    with web_app.test_request_context("/"):
        login_user(user.entity)
        result = DeferredJobs.run(change["pending_change"]["operation"])
    assert result.success is True
    parent.uncomplete_task(tasks[1])
    expect(tasks[1].element).to_have_attribute("data-open", "false")
    expect(tasks[1].element.locator("[lp-nav] [data-role='error']")).to_be_empty()
    expect(tasks[1].element.locator("[lp-nav] [data-role='error']")).to_be_hidden()
    stored = Entities.fetch_one(tasks[1].key, request=Fetch.root())
    assert stored.completed is False
    assert stored.db.get("history") is True
    assert stored.properties.submission.value == {}


# @matrix forms : builder-save stable-identity
# @matrix form-migration : modify-panel
# @template forms/builder.html::main
def test_saved_inputs_use_replacement_panel_after_first_save(get_user):
    user = get_user(Users.OWNER)
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Input replacement {uuid4().hex[:8]}",
            form_type="task",
            schema=(),
        ),
    ).create()
    builder = form.builder
    field = SchemaFields.TEXT_INPUT.get(_id="quantity", title="Quantity")
    builder.add_field(field)
    type_controls = builder.settings.locator("[data-setting='input']")
    expect(type_controls.locator("input[name='input']")).to_have_count(6)
    type_controls.get_by_role("radio", name="Number", exact=True).check()
    assert builder.schema_field(field.id)["input"] == "number"
    with expect_successful_response(
        user.page, method="PUT", path=f"/forms/{form.key}/update"
    ):
        user.locate(builder.SAVE_BUTTON).click()
    notice = builder.settings.locator("[data-role='saved-input-type']")
    expect(notice).to_have_text(
        "Click Replace or Delete in order to change this input's type."
    )
    expect(notice.locator("strong")).to_have_text("Replace or Delete")
    expect(type_controls.locator("input[name='input']")).to_have_count(0)

    form.reload(wait_until="domcontentloaded")
    builder.select_field(field)
    expect(notice).to_be_visible()
    builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
    expect(builder.condition).to_be_visible()
    select = Select(builder.condition.locator("[data-combobox-id]"))
    panel = select.open()
    expect(panel.get_by_role("option")).to_have_count(2)
    expect(panel.get_by_role("option", name="Text", exact=True)).to_be_visible()
    select.select_by_name("Textarea")
    builder.condition.get_by_role("button", name="Convert", exact=True).click()
    expect(builder.condition).to_be_hidden()
    assert builder.schema_field(field.id)["type"] == "textarea"
    user.locate("[data-role='undo-draft']").click()
    builder.select_field(field)
    expect(notice).to_be_visible()
    expect(type_controls.locator("input[name='input']")).to_have_count(0)
    assert builder.schema_field(field.id)["input"] == "number"


# @matrix form-migration : modify-panel
# @template forms/builder.html::main
def test_replacement_choices_and_explanations_match_component_types(get_user):
    user = get_user(Users.OWNER)
    options = [{"value": "first", "label": "First"}, {"value": "second", "label": "Second"}]
    fields = {
        "external": SchemaFields.LINK.get(location="out", title="External link"),
        "internal": SchemaFields.LINK.get(location="in", title="Internal link"),
        "location": SchemaFields.LOCATION.get(title="Address"),
        "text": SchemaFields.TEXTAREA.get(title="Long text"),
        "radio": SchemaFields.RADIO.get(title="Radio choice", options=options),
        "select": SchemaFields.SELECT.get(title="Single choice", options=options),
        "multiple": SchemaFields.SELECT.get(title="Multiple choices", options=options, multiple=True),
        "table": SchemaFields.TABLE.get(title="Items"),
        "todo": SchemaField(type="todo", component="[data-type='todo']", title="Checklist"),
        "signature": SchemaFields.SIGNATURE.get(title="Sign here"),
        "document": SchemaFields.HTML.get(title="Instructions"),
        "status": SchemaFields.STATUS.get(title="Status"),
    }
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Replacement rules {uuid4().hex[:8]}",
            form_type="task",
            schema=tuple(fields.values()),
        ),
    ).create()
    builder = form.builder
    scenarios = {
        "external": ({
            "Text": "Values will be converted to a plain-text url",
            "Bookmark": "Values will not change",
        }, []),
        "location": ({"Text": "Values will be converted to plain-text addresses"}, []),
        "text": ({"Text": "Values will be converted to text; newlines will be lost"}, [
            "Table (requires AI)",
            "Todo list (requires AI)",
        ]),
        "radio": ({
            "Text": "Values will be converted to the plain-text label of the option selected",
            "Select": "Component will be converted into a Select component with the same options",
        }, []),
        "select": ({
            "Text": "Values will be converted to the plain-text label of the option selected",
            "Radio": "Component will be converted into a Radio component with the same options",
        }, []),
        "multiple": ({
            "Text": "Values will be converted to the plain-text label of the option selected",
            "Radio": "Component will be converted into a Radio component with the same options",
        }, []),
        "table": ({"Textarea": "Values will be converted to a table with Markdown formatting"}, [
            "Todo list (requires AI)",
        ]),
        "todo": ({"Textarea": "Values will be converted to a todo list with Markdown formatting"}, [
            "Table (requires AI)",
        ]),
        "internal": ({}, []),
        "signature": ({}, []),
        "document": ({}, []),
        "status": ({}, []),
    }
    for name, (messages, ai_choices) in scenarios.items():
        builder.select_field(fields[name])
        builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
        expect(builder.condition).to_be_visible()
        if not messages and not ai_choices:
            notice = builder.condition.locator("[data-role='conversion-unavailable']")
            expect(notice).to_have_text("This component type cannot be converted")
            expect(notice).to_have_attribute("data-kind", "error")
            expect(builder.condition.locator("[data-combobox-id]")).to_have_count(0)
            expect(builder.condition.get_by_text("If you replace", exact=False)).to_have_count(0)
            expect(builder.condition.get_by_role("button", name="Convert", exact=True)).to_have_count(0)
            expect(builder.condition.get_by_role("button", name="Delete", exact=True)).to_be_enabled()
        else:
            select = Select(builder.condition.locator("[data-combobox-id]"))
            panel = select.open()
            expect(panel.get_by_role("option")).to_have_count(len(messages) + len(ai_choices))
            for label in ai_choices:
                expect(panel.get_by_role("option", name=label, exact=True)).to_be_enabled()
            for label, message in messages.items():
                select.select_by_name(label)
                description = builder.condition.locator("[data-role='conversion-description']")
                expect(description).to_have_text(message)
                expect(description).to_have_attribute("data-kind", "success")
        builder.condition.locator("button[data-role='close']").click()
        expect(builder.condition).to_be_hidden()


# @matrix form-migration : modify-panel
# @template forms/builder.html::main
def test_checkbox_replacement_explains_and_preserves_boolean_choices(get_user):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    decision = SchemaFields.CHECKBOX.get(_id="decision", title="Decision")
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Checkbox replacement {uuid4().hex[:8]}",
            form_type="task",
            schema=(decision,),
        ),
    ).create()
    tasks = []
    for value in (True, False):
        task = Entities.TASK.create(
            {
                "name": f"Checkbox {value} {uuid4().hex[:8]}",
                "page": parent.entity,
                "form": form.entity,
                "submission": {"decision": value},
            }
        )
        task = Entities.fetch_one(
            task, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)
        )
        task.save()
        tasks.append(task)

    builder = form.builder
    builder.select_field(decision)
    builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
    description = builder.condition.locator("[data-role='conversion-description']")
    expect(description).to_be_hidden()
    select = Select(builder.condition.locator("[data-combobox-id]"))
    panel = select.open()
    expect(panel.get_by_role("option", name="Time", exact=True)).to_have_count(0)
    expect(panel.get_by_role("option")).to_have_count(2)
    expect(panel.get_by_role("option", name="Multiple select", exact=True)).to_have_count(0)
    select.select_by_name("Text")
    expect(description).to_have_text("Values will be converted to 'True' or 'False'.")
    select.select_by_name("Radio")
    expect(description).to_have_text(
        "Component will be converted to a Radio with 'True' and 'False' values."
    )
    builder.condition.get_by_role("button", name="Convert", exact=True).click()
    expect(builder.model.get_by_role("radio", name="True", exact=True)).to_be_visible()
    expect(builder.model.get_by_role("radio", name="False", exact=True)).to_be_visible()
    assert builder.schema_field("decision")["options"] == [
        {"value": "true", "label": "True"},
        {"value": "false", "label": "False"},
    ]
    with expect_successful_response(
        user.page, method="PUT", path=f"/forms/{form.key}/update", timeout=60000
    ):
        user.locate(builder.SAVE_BUTTON).click()
    expect(user.locate("[data-role='form-change-status']")).to_be_hidden(timeout=30000)
    assert [
        Entities.fetch_one(task.key, request=Fetch.root()).properties.submission.value
        for task in tasks
    ] == [{"decision": "true"}, {"decision": "false"}]


# @matrix form-migration : modify-panel no-submission-read draft-undo saved-job progress reload recovery informational-notice readonly-modal
# @matrix task-completion : original-view readonly permission-gates
# @style radio.fieldset.column
# @style radio.label
# @style radio.default
# @template forms/builder.html::main
# @template pages/tasks.html::task_form
# @template pages/tasks.html::settings_form
# @template reference/macros.html::modal
def test_saved_conversion_runs_after_save_and_preserves_originals(get_user, tmp_path):
    user = get_user(Users.OWNER)
    parent = Pages.acl_lab_visible.get(user)
    notes = SchemaFields.TEXT_INPUT.get(_id="notes", title="Quantity")
    details = SchemaFields.TEXTAREA.get(_id="details", title="Details")
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Convert values {uuid4().hex[:8]}",
            form_type="task",
            schema=(notes, details),
        ),
    ).create()
    tasks = []
    for name, value, completed in [
        ("Valid", "42", False),
        ("Invalid", "unknown", False),
        ("Completed", "7", True),
    ]:
        task = Entities.TASK.create(
            {
                "name": f"BSU {name}",
                "page": parent.entity,
                "form": form.entity,
                "submission": {"notes": value},
            }
        )
        task = Entities.fetch_one(
            task, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)
        )
        task.save()
        if completed:
            task.complete(user=user.entity)
            task.save()
        tasks.append(task)
    completion = tasks[-1].db["completed_submission"]
    builder = form.builder
    builder.select_field(details)
    builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
    expect(builder.condition.locator("[data-role='title']")).to_have_text(
        "Replace or Delete"
    )
    builder.condition.get_by_role(
        "button", name="Help with converting or deleting form elements", exact=True
    ).click()
    help_modal = user.locate("#modal")
    expect(
        help_modal.get_by_role("heading", name="Converting and deleting form elements")
    ).to_be_visible()
    expect(help_modal).to_contain_text("Values that do not fit the destination type are cleared.")
    help_modal.get_by_role("button", name="Close", exact=True).click()
    expect(help_modal).not_to_be_attached()
    type_select = Select(builder.condition.locator("[data-combobox-id]"))
    panel = type_select.open()
    expect(panel.get_by_role("option")).to_have_count(3)
    expect(panel.get_by_role("option", name="Todo list (requires AI)", exact=True)).to_be_enabled()
    expect(panel.get_by_role("option", name="Multiple select", exact=True)).to_have_count(0)
    ai_option = panel.get_by_role(
        "option", name="Table (requires AI)", exact=True
    )
    expect(ai_option).to_be_enabled()
    type_select._choose_option(panel, ai_option)
    instructions = builder.condition.locator("textarea[name='conversion-instructions']")
    expect(instructions).to_be_visible()
    instructions.fill("One row per item; preserve quantities.")
    expect(builder.condition.get_by_role("button", name="Convert", exact=True)).to_be_enabled()
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).to_be_hidden()
    builder.select_field(notes)
    expect(builder.settings.locator("[data-role='saved-input-type']")).to_be_visible()
    expect(builder.settings.locator("input[name='input']")).to_have_count(0)
    builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
    expect(builder.condition).to_be_visible()
    type_select = Select(builder.condition.locator("[data-combobox-id]"))
    panel = type_select.open()
    expect(panel.get_by_role("option")).to_have_count(6)
    expect(
        panel.get_by_role("option", name="Phone Number", exact=True).locator(
            "[data-icon='tel']"
        )
    ).to_be_visible()
    expect(
        panel.get_by_role("option", name="Number", exact=True).locator(
            "[data-icon='number']"
        )
    ).to_be_visible()
    type_select.select_by_name("Number")
    convert = builder.condition.get_by_role("button", name="Convert", exact=True)
    delete = builder.condition.get_by_role("button", name="Delete", exact=True)
    expect(convert).to_be_enabled()
    expect(delete).to_be_visible()
    # Measure in one frame while the combobox's focus scroll settles.
    convert_box, delete_box = convert.locator("..").get_by_role("button").evaluate_all(
        "buttons => buttons.map(button => button.getBoundingClientRect().toJSON())"
    )
    assert abs(convert_box["y"] - delete_box["y"]) <= 1
    assert convert_box["x"] + convert_box["width"] <= delete_box["x"]
    convert.click()
    assert (
        Entities.fetch_one(
            tasks[0].key, request=Fetch.root()
        ).properties.submission.value["notes"]
        == "42"
    )
    assert not Entities.fetch_one(form.entity.key, request=Fetch.root()).db.get(
        "pending_form_change"
    )
    user.locate("[data-role='undo-draft']").click()
    assert builder.schema_field("notes")["input"] == "text"
    user.locate("[data-role='redo-draft']").click()
    with expect_successful_response(
        user.page, method="PUT", path=f"/forms/{form.key}/update", timeout=60000
    ) as saved:
        user.locate(builder.SAVE_BUTTON).click()
    assert saved.value.json().get("error") is None, saved.value.json()
    expect(user.locate("[data-role='form-change-status']")).to_be_hidden(timeout=30000)
    current = Entities.fetch_one(form.entity.key, request=Fetch.root())
    assert current.generation == 1
    assert current.schema[0]["input"] == "number"
    assert not current.db.get("pending_form_change")
    converted = [Entities.fetch_one(task.key, request=Fetch.root()) for task in tasks]
    assert converted[0].properties.submission.value == {"notes": 42}
    assert converted[1].properties.submission.value == {}
    assert converted[2].properties.submission.value == {"notes": 7}
    assert converted[2].db["completed_submission"] == completion
    assert all(task.generation == 1 for task in converted)
    assert json.loads(converted[1].db["pre_migration"])["notes"]["value"] == "unknown"
    task_resource = TaskResource(user=user)
    task_resource.entity = converted[1]
    user.go(task_resource)
    task_form = task_resource.task_form
    task_form.get_by_role("button", name="View changes", exact=True).click()
    modal = user.locate("#modal")
    expect(modal).to_contain_text("unknown")
    invalid = modal.get_by_text("Value not able to be converted", exact=True)
    expect(invalid).to_be_visible()
    expect(invalid).to_have_attribute("data-kind", "error")
    expect(invalid).to_have_css("font-style", "italic")
    expect(modal).not_to_contain_text("Not provided")
    expect(modal.get_by_role("radio")).to_have_count(0)
    expect(modal.locator("header").get_by_role("button", name="Close", exact=True)).to_be_visible()
    before = modal.get_by_role("heading", name="Before", exact=True)
    after = modal.get_by_role("heading", name="After", exact=True)
    assert abs(before.bounding_box()["y"] - after.bounding_box()["y"]) < 2
    user.page.screenshot(path=tmp_path / "migration-modal-desktop.png")
    viewport = user.page.viewport_size
    try:
        user.page.set_viewport_size({"width": 390, "height": 844})
        expect(invalid).to_be_visible()
        assert after.bounding_box()["y"] > before.bounding_box()["y"]
        assert modal.locator("#modal-content").evaluate(
            "node => node.scrollWidth <= node.clientWidth"
        )
        user.page.screenshot(path=tmp_path / "migration-modal-narrow.png")
    finally:
        user.page.set_viewport_size(viewport)
    before_settings = modal.locator("#modal-content").inner_text()
    modal.get_by_role("button", name="Close", exact=True).click()
    saved_notice = Entities.fetch_one(tasks[1].key, request=Fetch.root()).db.get(
        "pre_migration"
    )
    assert saved_notice

    # Updating settings refreshes the loaded form without dismissing its notice.
    settings_form = task_resource.settings_form
    description = settings_form.locator("[name='description']")
    if not description.is_visible():
        settings_form.locator("#description [data-role='label']").click()
    description.fill("Settings updated after migration")
    task_resource.save()
    saved = Entities.fetch_one(tasks[1].key, request=Fetch.root())
    assert saved.description == "Settings updated after migration"
    assert saved.db.get("pre_migration") == saved_notice
    task_form = task_resource.task_form
    expect(task_form.locator("[data-role='migration-notice']")).to_have_count(1)
    task_form.get_by_role("button", name="View changes", exact=True).click()
    expect(modal.locator("#modal-content")).to_have_text(before_settings, use_inner_text=True)
    modal.get_by_role("button", name="Close", exact=True).click()

    task_form.locator("input[name='notes']").fill("8")
    with expect_successful_response(
        user.page, method="PUT", path=f"/tasks/{task_resource.key}/update"
    ):
        task_form.get_by_role("button", name="Update", exact=True).click()
    updated = Entities.fetch_one(tasks[1].key, request=Fetch.root())
    assert updated.properties.submission.value == {"notes": 8}
    assert not updated.db.get("pre_migration")
    expect(task_resource.task_form.locator("[data-role='migration-notice']")).to_have_count(0)

    # Fresh tasks must adopt the newly published generation too.
    fresh = Entities.TASK.create(
        {"name": "After conversion", "page": parent.entity, "form": current}
    )
    fresh.save()
    assert Entities.fetch_one(fresh.key, request=Fetch.root()).generation == 1

    # Completed tasks have one editor-only notice and reveal the archive choices
    # inline. The active task's before/after modal must not be installed here.
    completed = TaskResource(user=user)
    completed.entity = converted[2]
    user.go(completed)
    completed_form = completed.task_form
    expect(completed_form).to_have_attribute("data-completed", "true")
    expect(completed_form.locator("[data-role='migration-notice']")).to_have_count(0)
    warning = completed_form.locator("[data-role='submission-changed-warning']")
    expect(warning).to_contain_text("This form was modified after this task was completed.")
    original = warning.get_by_role("button", name="View Original Submission", exact=True)
    expect(original).to_be_visible()
    expect(original).to_have_css("font-weight", "600")
    choices = warning.get_by_role("group", name="When Reopened", include_hidden=True)
    expect(choices).to_be_hidden()
    user.page.screenshot(path=tmp_path / "completed-migration-notice.png")
    completion_path = f"/tasks/{completed.key}/completion-details"
    with expect_successful_response(user.page, method="GET", path=completion_path):
        original.click()
    expect(warning).to_be_visible()
    expect(original).to_be_visible()
    expect(user.page.get_by_role("dialog", name="Form changes")).to_have_count(0)
    expect(choices).to_be_visible()
    archive_original = choices.get_by_role("radio", name="Archive original submission", exact=True)
    archive_modified = choices.get_by_role("radio", name="Archive modified submission", exact=True)
    expect(archive_original).to_be_checked()
    expect(archive_modified).not_to_be_checked()
    expect(archive_original).to_have_css("appearance", "none")
    expect(archive_original.locator("..")).to_have_css("font-weight", "600")
    assert archive_modified.bounding_box()["y"] > archive_original.bounding_box()["y"]
    expect(completed_form.locator("[data-role='original-completion-detail']")).to_be_visible()
    user.page.screenshot(path=tmp_path / "completed-archive-choices.png")
    try:
        user.page.set_viewport_size({"width": 390, "height": 844})
        expect(archive_original).to_be_visible()
        expect(archive_modified).to_be_visible()
        assert archive_modified.bounding_box()["y"] > archive_original.bounding_box()["y"]
        assert choices.evaluate("node => node.scrollWidth <= node.clientWidth")
        user.page.screenshot(path=tmp_path / "completed-archive-choices-narrow.png")
    finally:
        user.page.set_viewport_size(viewport)

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(completed)
    readonly = completed.task_form
    expect(readonly).to_be_visible()
    expect(readonly).to_have_attribute("data-completed", "true")
    expect(readonly.locator("[data-role='migration-notice'], [data-role='original-completion-controls']")).to_have_count(0)
    expect(readonly.get_by_role("radio")).to_have_count(0)
    response = requests.get(
        f"{SETTINGS.test_config['BASE_URL']}{completion_path}",
        cookies={cookie["name"]: cookie["value"] for cookie in viewer.page.context.cookies()},
        allow_redirects=False,
        timeout=10,
    )
    assert_lagniappe_error_response(response, status=403)


# @matrix html-field : generated-document-undo retained-editor
# @template forms/builder.html::generate
def test_generated_document_uses_editor_undo_before_first_open(get_user):
    from testing.utility.network import multipart_form_fields, scoped_browser_route

    user = get_user(Users.OWNER)
    instructions = SchemaFields.HTML.get(_id="instructions", title="Instructions")
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Document undo {uuid4().hex[:8]}",
            form_type="task",
            schema=(instructions,),
        ),
    ).create()
    form.entity.set_html_field("instructions", "<p>Original instructions.</p>")
    form.entity.save()
    builder = form.builder

    def generated(route):
        data = dict(multipart_form_fields(route.request))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "operations": [],
                    "html_fields": {"instructions": "<p>Generated instructions.</p>"},
                    "request_id": data["request_id"],
                    "draft_revision": int(data["draft_revision"]),
                }
            ),
        )

    with scoped_browser_route(user.page.context, "**/forms/create-schema", generated):
        user.locate("button[data-role='form-settings']").click()
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill(
            "Replace the instructions"
        )
        generate.locator("button[type='submit']").click()
        expect(
            generate.get_by_role("button", name="Generated", exact=True)
        ).to_be_visible()
    builder.select_field(instructions)
    builder.open_condition("html", role="edit")
    editor = builder.condition.locator(".ProseMirror")
    expect(editor).to_have_text("Generated instructions.")
    editor.press("Control+z")
    expect(editor).to_have_text("Original instructions.")
    editor.press("Control+Shift+z")
    expect(editor).to_have_text("Generated instructions.")
    assert (
        Entities.fetch_one(form.entity.key, request=Fetch.root()).get_html_field(
            "instructions"
        )
        == "<p>Original instructions.</p>"
    )


# @matrix form-migration : status recovery retry reload saved-job
# @template forms/builder.html::main
def test_failed_preflight_recovers_after_reload(get_user):
    from lagniappe.core.tools.database.utility import save_mutations

    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    notes = SchemaFields.TEXT_INPUT.get(_id="notes", title="Notes")
    form = Form(
        user=user,
        definition=FormDefinition(
            name=f"Retry conversion {uuid4().hex[:8]}",
            form_type="task",
            schema=(notes,),
        ),
    ).create()
    task = Entities.TASK.create(
        {
            "name": "Unexpected generation",
            "page": parent.entity,
            "form": form.entity,
            "submission": {"notes": "Keep this value"},
        }
    )
    task.save()
    # A deliberately inconsistent legacy fixture exercises preflight failure,
    # before any conversion has permission to write a submission.
    task.db["generation"] = 99
    save_mutations([(task, ("generation",))])
    builder = form.builder
    builder.select_field(notes)
    builder.settings.get_by_role("button", name="Replace or Delete", exact=True).click()
    builder.condition.get_by_role("button", name="Delete", exact=True).click()
    with expect_successful_response(
        user.page, method="PUT", path=f"/forms/{form.key}/update", timeout=60000
    ):
        user.locate(builder.SAVE_BUTTON).click()
    status = user.locate("[data-role='form-change-status']")
    expect(status).to_contain_text("needs attention", timeout=30000)
    expect(user.locate("#notification [data-role='form-change-status']")).to_be_visible()
    expect(user.locate(builder.SAVE_BUTTON)).to_be_disabled()
    expect(user.locate("[lp-view] > section")).to_have_count(3)
    expect(user.page.get_by_role("button", name="Cancel update", exact=True)).to_have_count(0)
    assert (
        Entities.fetch_one(task.key, request=Fetch.root()).properties.submission.value[
            "notes"
        ]
        == "Keep this value"
    )
    form.reload()
    status = user.locate("[data-role='form-change-status']")
    expect(status.get_by_role("button", name="Retry", exact=True)).to_be_visible()
    expect(user.locate("#notification [data-role='form-change-status']")).to_be_visible()
    expect(user.locate(builder.SAVE_BUTTON)).to_be_disabled()
    expect(user.page.get_by_role("button", name="Cancel update", exact=True)).to_have_count(0)
    task.db["generation"] = 0
    save_mutations([(task, ("generation",))])
    with expect_successful_response(
        user.page, method="POST", path=f"/forms/{form.key}/change", timeout=60000
    ):
        status.get_by_role("button", name="Retry", exact=True).click()
    expect(status).to_be_hidden(timeout=30000)
    current = Entities.fetch_one(form.entity.key, request=Fetch.root())
    assert not current.db.get("pending_form_change")
    assert current.generation == 1
    assert current.schema == []
    changed = Entities.fetch_one(task.key, request=Fetch.root())
    assert changed.properties.submission.value == {}
    assert changed.generation == 1
    assert (
        json.loads(changed.db["pre_migration"])["notes"]["value"]
        == "Keep this value"
    )
