"""Real builder draft actions and the guarded publication/asset HTTP boundaries."""

from copy import deepcopy
import json
from urllib.parse import urljoin
from uuid import uuid4

from bs4 import BeautifulSoup
import pytest
import requests
from playwright.sync_api import expect
from werkzeug.datastructures import FileStorage

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.form_definitions import rendered_html_fields
from lagniappe.core.tools.form_drafts import resolve_form_version
from testing.definitions import Pages, SitePages, Uploads, Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.schema_fields import SchemaFields
from testing.definitions.user_definitions import UserDefinition
from testing.resources.form import Builder, Form
from testing.resources.task import Task as TaskResource
from testing.utility.network import manual_mutation_headers, multipart_form_fields, scoped_browser_route

pytestmark = pytest.mark.e2e


def _form(user, title="BSU draft"):
    field = SchemaFields.TEXT_INPUT.get(_id="notes", title="Original notes")
    form = Form(user=user, definition=FormDefinition(
        name=f"{title} {uuid4().hex[:8]}", form_type="task", schema=(field,),
    )).create()
    return form, field


def _rename(builder, field, label):
    builder.select_field(field)
    title = builder.settings.locator("input[name='title']")
    title.fill(label)
    title.blur()


def _generation_reply(route, operations):
    data = dict(multipart_form_fields(route.request))
    route.fulfill(status=200, content_type="application/json", body=json.dumps({
        "operations": operations, "html_fields": {},
        "request_id": data["request_id"], "draft_revision": int(data["draft_revision"]),
    }))


def _http(user, method, path, **kwargs):
    return requests.request(
        method, urljoin(user.page.url, path), timeout=20,
        cookies={cookie["name"]: cookie["value"] for cookie in user.page.context.cookies()},
        headers=manual_mutation_headers(user.page.url, user.locate("#token").input_value()),
        allow_redirects=False, **kwargs,
    )


# @source src/script/views/builder/draft.mjs::BuilderDraft
# @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
# @matrix forms : draft-history stable-identity schema-generation builder-save builder-reload
# @template forms/builder.html::header
# @template forms/builder.html::generate
def test_generation_is_one_undoable_unsaved_command(get_user):
    user = get_user(Users.OWNER)
    form, field = _form(user)
    builder = form.builder
    before = dict(Entities.fetch_one(form.key, request=Fetch.root()).db)
    _rename(builder, field, "Manual notes")
    operations = [
        {"op": "update_field", "field_id": "notes", "changes": {"title": "Generated notes"}},
        {"op": "add_field", "field": {"id": "generated-extra", "type": "textarea", "title": "Extra notes"}},
    ]
    with scoped_browser_route(user.page.context, "**/forms/create-schema", lambda route: _generation_reply(route, operations)):
        user.locate("button[data-role='form-settings']").click()
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill("Update notes and add extra notes")
        generate.locator("button[type='submit']").click()
        expect(generate).to_be_hidden()
    expect(builder.model).to_contain_text("Generated notes")
    expect(user.locate(builder.UNSAVED)).to_be_visible()
    assert dict(Entities.fetch_one(form.key, request=Fetch.root()).db) == before

    user.locate("[data-role='undo-draft']").click()
    expect(builder.model).to_contain_text("Manual notes")
    assert builder.schema_field("generated-extra") is None
    user.locate("[data-role='redo-draft']").click()
    expect(builder.model).to_contain_text("Generated notes")
    assert builder.schema_field("generated-extra")["title"] == "Extra notes"
    builder.save()
    form.reload()
    assert Builder(user).schema_field("notes")["title"] == "Generated notes"
    assert Builder(user).schema_field("generated-extra")["title"] == "Extra notes"


# @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
# @matrix forms : draft-history schema-generation stale-response
# @template forms/builder.html::generate
def test_generation_rejects_result_after_intervening_edit(get_user):
    user = get_user(Users.OWNER)
    form, field = _form(user, "BSU stale generation")
    builder = form.builder
    def reply_after_intervening_edit(route):
        # Edit only once the service-worker-owned request has actually arrived.
        # Completing the handler also avoids leaving an unresolved route on failure.
        try:
            _rename(builder, field, "Intervening edit")
        except BaseException:
            route.abort()
            raise
        _generation_reply(route, [
            {"op": "update_field", "field_id": "notes", "changes": {"title": "Stale label"}},
        ])

    with scoped_browser_route(user.page.context, "**/forms/create-schema", reply_after_intervening_edit):
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill("Rename notes")
        generate.locator("button[type='submit']").click()
        expect(builder.model).to_contain_text("Intervening edit")
        user.locate("button[data-role='form-settings']").click()
        expect(generate.locator("[data-role='error']")).to_contain_text("draft changed")
        expect(generate.get_by_role("button", name="Regenerate", exact=True)).to_be_enabled()
        assert builder.schema_field("notes")["title"] == "Intervening edit"


# @matrix forms : builder-save stale-acknowledgement persistent-error concurrent-edit
# @template forms/builder.html::header
def test_stale_save_preserves_local_draft_after_another_editor_saves(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    form, field = _form(owner, "BSU concurrent save")
    first = form.builder
    editor = get_user(UserDefinition(
        name="BSU second editor", email=f"bsu-editor-{uuid4().hex}@example.test",
    ), creator=owner)
    editor.go(SitePages.HOME)
    editor_entity = Entities.USER.load(editor.email)
    editor_entity.permissions = {**editor_entity.permissions, "forms": Action.EDIT.name}
    editor_entity.save()
    second_form = Form(user=editor)
    second_form.entity = form.entity
    second = second_form.builder
    _rename(first, field, "First editor saved")
    first.save()
    _rename(second, field, "Second editor draft")
    path = editor.locate("#schema-form").get_attribute("data-route")
    with browser_failures.expect_http_error(editor, status=409, path=path):
        with editor.page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith(path)) as response:
            editor.locate(second.SAVE_BUTTON).click()
        assert response.value.status == 409
        expect(editor.locate("#notification")).to_contain_text("draft is preserved")
        expect(editor.locate(second.UNSAVED)).to_be_visible()
        assert second.schema_field("notes")["title"] == "Second editor draft"
    persisted = Entities.fetch_one(form.key, request=Fetch.root())
    assert persisted.schema[0]["title"] == "First editor saved"


# @matrix forms : builder-save migration-required save-receipt
def test_builder_publication_rejects_incompatible_payload_and_reuses_receipt(get_user):
    user = get_user(Users.OWNER)
    form, _ = _form(user, "BSU publication contract")
    form.builder
    bootstrap = json.loads(user.locate("#builder-draft").text_content())
    request = {**bootstrap, "save_id": uuid4().hex, "image_manifest": []}
    incompatible = deepcopy(request)
    incompatible["schema"][0]["type"] = "textarea"
    response = _http(user, "PUT", f"/forms/{form.key}/update", json=incompatible)
    assert response.status_code == 422
    assert "migration" in response.text
    assert Entities.fetch_one(form.key, request=Fetch.root()).schema[0]["type"] == "input"

    request["schema"][0]["title"] = "Accepted label"
    accepted = _http(user, "PUT", f"/forms/{form.key}/update", json=request)
    repeated = _http(user, "PUT", f"/forms/{form.key}/update", json=request)
    assert accepted.status_code == repeated.status_code == 200
    assert accepted.json()["baseline"] == repeated.json()["baseline"]
    form.reload()
    assert Builder(user).schema_field("notes")["title"] == "Accepted label"


# @matrix task-completion html-field permissions : schema-version owned-image record-scope
def test_historical_images_are_bound_to_the_authorized_completion(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_create_page_task.get(user)
    field = SchemaFields.HTML.get(_id="instructions", title="Instructions")
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU historical image {uuid4().hex[:8]}", form_type="task", schema=(field,),
    )).create()
    image = Uploads.editor_test_image.value.file
    with image.path.open("rb") as stream:
        source_url = form.entity.add_html_field_image(field.id, FileStorage(
            stream=stream, filename=image.name, content_type=image.mime_type,
        ))
    form.entity.set_html_field(field.id, f'<p>Original instructions</p><img src="{source_url}">')
    form.entity.save()
    task = Entities.TASK.create({"name": "BSU completed image", "page": page.entity, "form": form.entity})
    task.save()
    task.complete(user=user.entity)
    task.save()
    html = rendered_html_fields(task)[field.id]
    image_url = BeautifulSoup(html, "html.parser").find("img")["src"]
    user.go(page)
    response = _http(user, "GET", image_url)
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("image/")
    metadata = _http(user, "HEAD", image_url)
    assert metadata.status_code == 200
    assert int(metadata.headers["Content-Length"]) == len(response.content)
    assert metadata.content == b""
    snapshot = resolve_form_version(task.properties.form.key, task.submission_definition.version)
    image_name = next(name for name in snapshot.assets if name.startswith(f"image_{field.id}_"))
    assert _http(user, "GET", snapshot.get_asset(image_name).url).status_code == 403
    wrong_version = image_url.replace(task.schema_version, "unrelated-version")
    assert _http(user, "GET", wrong_version).status_code == 404
    outsider = get_user(UserDefinition(
        name="BSU unrelated viewer", email=f"bsu-viewer-{uuid4().hex}@example.test",
    ), creator=user)
    outsider.go(SitePages.HOME)
    assert _http(outsider, "GET", image_url).status_code == 403

    form.entity.set_html_field(field.id, "<p>New active instructions</p>")
    form.entity.save()
    assert _http(user, "GET", image_url).status_code == 200
    assert "Original instructions" in rendered_html_fields(task)[field.id]
    Entities.delete(form.entity)
    restored = Entities.fetch_one(task.key, request=Fetch.root())
    assert "Original instructions" in rendered_html_fields(restored)[field.id]
    assert _http(user, "GET", image_url).status_code == 200
    assert _http(outsider, "GET", image_url).status_code == 403


# @source src/script/views/builder/conditions/options.mjs::Options
# @source src/script/views/builder/conditions/columns.mjs::Columns
# @matrix forms : stable-identity builder-select-options builder-table-column builder-save builder-reload
# @matrix tasks forms : cache-invalidation live-metadata
# @template forms/builder.html::header
# @template pages/tasks.html::task_form
def test_saved_relabels_preserve_active_task_answers_and_conditions(get_user):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    channels = SchemaFields.SELECT.get(
        _id="channels", title="Contact channels", multiple=True,
        options=[{"value": "email-original", "label": "Email"},
                 {"value": "sms-original", "label": "SMS"}],
    )
    decision = SchemaFields.RADIO.get(
        _id="decision", title="Dispatch decision",
        options=[{"value": "approved-original", "label": "Approved"},
                 {"value": "hold-original", "label": "Hold"}],
    )
    column = SchemaFields.TEXT_INPUT.get(_id="item-original", title="Item")
    items = SchemaFields.TABLE.get(_id="items", title="Dispatch items", columns=[column])
    details = SchemaFields.TEXTAREA.get(
        _id="details", title="Email instructions", visibility=[{
            "id": channels.id, "name": channels.title, "type": "select",
            "value": "email-original", "label": "Email",
        }],
    )
    feedback = SchemaFields.STATUS.get(_id="feedback", title="Dispatch status", status=[{
        "id": decision.id, "name": decision.title, "type": "radio",
        "value": "approved-original", "label": "Approved", "text": "Ready for dispatch",
    }])
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU identity preservation {uuid4().hex[:8]}", form_type="task",
        schema=(channels, decision, items, details, feedback),
    )).create()
    answers = {
        channels.id: ["email-original", "sms-original"],
        decision.id: "approved-original",
        items.id: {"rows": [{column.id: "Router"}, {column.id: "Spare cable"}]},
        details.id: "Use the saved delivery address",
    }
    task_entity = Entities.TASK.create({
        "name": "BSU active dispatch", "page": parent.entity, "form": form.entity,
        "submission": answers,
    })
    task_entity = Entities.fetch_one(task_entity, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    task_entity.save()
    task = TaskResource(user=user)
    task.entity = task_entity

    def assert_active_answers(channel_label, decision_label, column_label):
        user.go(task)
        task_form = task.task_form
        selection = task_form.locator(f"select[name='{channels.id}']")
        expect(selection).to_have_values(answers[channels.id])
        expect(selection.locator("option:checked")).to_have_text([channel_label, "SMS"])
        selected_channels = task_form.locator(f"[id^='{channels.id}-'].form-element [data-role='read']")
        expect(selected_channels).to_contain_text(channel_label)
        expect(selected_channels).to_contain_text("SMS")
        radio = task_form.locator(f"[id^='{decision.id}-'].form-element")
        expect(radio.locator("[data-role='read']")).to_have_text(decision_label)
        radio.get_by_role("button", name=f"Edit {decision.title}", exact=True).click()
        expect(task_form.get_by_role("radio", name=decision_label, exact=True)).to_be_checked()
        expect(task_form.locator(f"input[name='{decision.id}'][value='approved-original']")).to_be_checked()
        table = task_form.locator(f"[id^='{items.id}-'].form-element")
        expect(table.locator("thead")).to_contain_text(column_label)
        expect(table.locator("tbody tr[data-index]")).to_have_count(2)
        expect(table.locator("tbody")).to_contain_text("Router")
        expect(table.locator("tbody")).to_contain_text("Spare cable")
        assert json.loads(table.locator(f"input[name='{items.id}']").input_value()) == answers[items.id]["rows"]
        visible_details = task_form.locator(f"[id^='{details.id}-'].form-element")
        expect(visible_details).to_have_attribute("data-visible", "true")
        expect(visible_details).to_be_visible()
        expect(task_form.locator(f"textarea[name='{details.id}']")).to_have_value(answers[details.id])
        status = task_form.locator("[data-kind='status']")
        expect(status).to_have_attribute("data-visible", "true")
        expect(status).to_contain_text("Ready for dispatch")

    assert_active_answers("Email", "Approved", "Item")
    builder = form.builder
    original_visibility = deepcopy(builder.schema_field(details.id)["visibility"])
    original_status = deepcopy(builder.schema_field(feedback.id)["status"])
    for field, old_label, new_label in (
        (channels, "Email", "Email delivery"),
        (decision, "Approved", "Cleared for dispatch"),
    ):
        builder.select_field(field)
        builder.settings.locator("[data-setting='options'] li").filter(has_text=old_label).locator("[data-role='open']").click()
        expect(builder.condition).to_be_visible()
        builder.condition.locator("input[name='option-name']").fill(new_label)
        builder.save_condition()
        builder.condition.locator("button[data-role='close']").click()
        expect(builder.condition).to_be_hidden()
    builder.select_field(items)
    builder.open_condition("columns", role="open")
    builder.condition.locator("input[name='column-name']").fill("Equipment")
    builder.save_condition()
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).to_be_hidden()
    builder.save()
    form.reload()
    reloaded = Builder(user)
    assert [option["value"] for option in reloaded.schema_field(channels.id)["options"]] == answers[channels.id]
    assert reloaded.schema_field(channels.id)["options"][0]["label"] == "Email delivery"
    assert reloaded.schema_field(decision.id)["options"][0]["value"] == answers[decision.id]
    assert reloaded.schema_field(decision.id)["options"][0]["label"] == "Cleared for dispatch"
    assert reloaded.schema_field(items.id)["columns"][0]["id"] == column.id
    assert reloaded.schema_field(items.id)["columns"][0]["title"] == "Equipment"
    assert reloaded.schema_field(details.id)["visibility"] == original_visibility
    assert reloaded.schema_field(feedback.id)["status"] == original_status
    persisted_task = Entities.fetch_one(task.key, request=Fetch.direct())
    assert not persisted_task.completed
    for field_id, value in answers.items():
        assert persisted_task.submission[field_id] == value
    assert_active_answers("Email delivery", "Cleared for dispatch", "Equipment")
