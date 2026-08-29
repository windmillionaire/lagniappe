from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from testing.definitions import Pages, Tasks, Users
from testing.resources import Page, Task
from testing.utility.network import expect_successful_response
from testing.utility.polling import expect_poll_result


pytestmark = pytest.mark.e2e


def _fill_form_field(form, field_prefix, value):
    field = form.locator(f"[id^='{field_prefix}-']")
    field.locator("[data-role='label']").click()
    field.locator("input, textarea").first.fill(value)


def _create_reconciliation_page(user):
    template = Pages.test_offline_sync_form_page.get(user)
    name = f"Schema Reconciliation Page {uuid4().hex}"
    form = Entities.FORM.create(
        {
            "name": f"Schema Reconciliation Form {uuid4().hex}",
            "form-type": "page",
            "schema": deepcopy(template.entity.form.schema),
        }
    )
    form.save()
    category = Entities.CATEGORY.create(
        {
            "name": f"Schema Reconciliation Category {uuid4().hex}",
            "form": form,
            "attributes": [],
        }
    )
    category.save()
    entity = Entities.PAGE.create(
        {
            "name": name,
            "description": template.definition.description,
            "model": category,
            "form": form,
            "attributes": list(template.definition.attributes),
            "submission": deepcopy(
                template.entity.properties.submission.form_value
            ),
        }
    )
    entity.save()
    page = Page(user=user, definition=SimpleNamespace(name=name))
    page.entity = entity
    return page, form


# @matrix forms : latest-schema readonly-preview submission-choice
# @pairs edited-entity-notice:submission-choice form-schema:notice reconnect-refresh:dirty-form-preservation
# @template controls.html::edited_marker
# @template pages/info.html::info_form
def test_form_submission_reconciliation_uses_latest_schema(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    page, form = _create_reconciliation_page(owner)
    page = owner.go(page)
    first = owner.page
    info = page.info_form
    suffix = uuid4().hex[:8]
    local_value = f"Local value awaiting reconciliation {suffix}"
    server_value = f"Saved value from another tab {suffix}"
    added_value = f"Value from the new schema field {suffix}"
    added_id = f"reconcile-added-field-{suffix}"

    _fill_form_field(info, "sync-text-renderer", local_value)
    first.wait_for_function(
        "() => !document.fonts || document.fonts.status === 'loaded'"
    )
    with browser_failures.expect_offline(owner):
        owner.offline = True
        expect(owner.locate("[data-role='offline']")).to_be_visible()

    original_schema = deepcopy(form.schema)
    form.schema = [
        *original_schema,
        {
            "id": added_id,
            "type": "input",
            "input": "text",
            "title": "Reconciliation Added Field",
        },
    ]
    form.save()

    other = collaborator.page
    other.goto(first.url)
    other_info = other.locator("[data-widget='PageInfo']")
    expect(other_info).to_have_attribute("rendered", "")
    _fill_form_field(other_info, "sync-text-renderer", server_value)
    _fill_form_field(other_info, added_id, added_value)
    with expect_successful_response(
        other,
        method="PUT",
        path=f"/pages/{page.key}/update",
        entity_key=page.key,
    ):
        other_info.locator('button[type="submit"]:not([data-role])').click()

    replacement_requests = []

    def record_replacement(request):
        if request.method == "GET" and request.url.endswith(
            f"/pages/{page.key}/info/replace"
        ):
            replacement_requests.append(request)

    first.on("request", record_replacement)
    try:
        with expect_poll_result(
            first,
            subscription_id=f"view:entity:{page.key}",
        ):
            with expect_successful_response(
                first,
                method="GET",
                path=f"/pages/{page.key}/info/replace",
                entity_key=page.key,
            ):
                owner.offline = False
    finally:
        first.remove_listener("request", record_replacement)

    assert len(replacement_requests) == 1
    expect(owner.locate("[data-role='offline']")).to_be_hidden()

    info = first.locator("[data-widget='PageInfo']")
    marker = info.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(marker.locator("[data-role='edited-message']")).to_contain_text(
        "fields and saved values changed"
    )
    marker.locator("[data-role='edited-reset']").click()

    modal = first.locator("#modal")
    expect(modal).to_be_visible()
    expect(modal).to_have_attribute("data-kind", "page")
    expect(modal.get_by_text(local_value, exact=True)).to_be_visible()
    expect(modal.get_by_text(server_value, exact=True)).to_be_visible()
    expect(modal.get_by_text("Schema update:")).to_contain_text("1 added")
    expect(modal.locator("[role='radiogroup']")).to_have_count(1)
    expect(modal.get_by_text("Reconciliation Added Field", exact=True)).to_have_count(0)

    local_choice = modal.locator("[data-revision-source='local']").filter(
        has_text=local_value
    )
    saved_choice = modal.locator("[data-revision-source='server']").filter(
        has_text=server_value
    )
    expect(saved_choice).to_have_attribute("aria-checked", "true")
    expect(local_choice).to_have_attribute("aria-checked", "false")
    local_choice.click()
    expect(local_choice).to_have_attribute("aria-checked", "true")
    expect(saved_choice).to_have_attribute("aria-checked", "false")

    modal.get_by_role("button", name="Update values").click()
    expect(modal).not_to_be_attached()

    info = first.locator("[data-widget='PageInfo']")
    expect(info.locator("input[name='sync-text']")).to_have_value(local_value)
    expect(info.locator(f"input[name='{added_id}']")).to_have_value(added_value)
    expect(
        info.locator(
            "button[type='submit']:not([data-role]) [data-icon='builder.unsaved']"
        )
    ).to_be_visible()


# @pair tasks:active-form-preservation
# @template controls.html::edited_marker
# @template pages/tasks.html::task_form
def test_task_collection_refresh_preserves_active_form_for_revision_review(
    get_user,
):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    task = Task(
        user=owner,
        definition=replace(
            Tasks.test_task_revision_review.value.definition,
            name=f"Task Revision Review {uuid4().hex}",
        ),
    ).create()
    with expect_poll_result(
        owner.page,
        subscription_id=f"edit:{task.key}",
        status=None,
        timeout=25000,
    ):
        owner.go(task)
    task_form = task.task_form
    field_id = "input-textab12"
    field = task_form.locator(f"input[name='{field_id}']")
    local_value = field.input_value()
    saved_value = f"Saved task value {uuid4().hex[:8]}"

    collaborator.page.goto(task.url)
    collaborator_task = Task(
        user=collaborator,
        definition=task.definition,
    )
    collaborator_task.entity = task.entity
    collaborator_task.wait_for_load()
    collaborator_form = collaborator_task.task_form
    collaborator_field = collaborator_form.locator(f"input[name='{field_id}']")
    _fill_form_field(collaborator_form, field_id, saved_value)
    expect(collaborator_field).to_have_value(saved_value)
    with expect_poll_result(
        owner.page,
        subscription_id=f"edit:{task.key}",
        timeout=25000,
    ):
        collaborator_task.save()

    task_form = task.element.locator(task.TASK_FORM)
    marker = task_form.locator("[lp-edited-marker]")
    expect(marker).to_be_visible()
    expect(field).to_have_value(local_value)
    marker.locator("[data-role='edited-reset']").click()

    modal = owner.page.locator("#modal")
    expect(modal).to_be_visible()
    expect(
        modal.locator("[data-revision-source='local']").get_by_text(
            local_value, exact=True
        )
    ).to_be_visible()
    expect(
        modal.locator("[data-revision-source='server']").get_by_text(
            saved_value, exact=True
        )
    ).to_be_visible()
