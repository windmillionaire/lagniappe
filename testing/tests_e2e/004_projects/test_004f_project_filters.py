"""
Tests for project filter tab UI and integration with the filter cache.

Covers:
    - Static filter conditions: Task Name (string), Due Date (timestamp),
      In Categories / Assigned To (list/entity-valued)
    - Dynamic filter conditions: Model Task (entity-valued per project)
    - Attached form field conditions: string, number, checkbox, select
    - Save, reset, compound filters, and empty-result edge cases

Application:
    - Entity: lagniappe/core/entities/condition.py (Condition / FilterDefinition)
    - Properties: lagniappe/core/properties/project.py (ProjectFilters)
    - Properties: lagniappe/core/properties/base_filters.py (Filters base)
    - Routes: lagniappe/web/routes/filters/main.py (condition, options, test, save)
    - Templates: lagniappe/web/templates/filters.html (condition macros by type)
    - Templates: lagniappe/web/templates/projects/filters.html (project wiring)
    - Frontend: src/script/widgets/filters.mjs (Filters widget)
    - Frontend: src/script/widgets/tables.mjs (FilterResults widget)
    - Cache: lagniappe/core/tools/filters/cache.py (FilterCache)

Test Framework:
    - Elements: testing/elements/filters.py (Filters, ProjectFilterConditions)
    - Definitions: testing/definitions/task_definitions.py (filter task defs)
    - Definitions: testing/definitions/tasks.py (Tasks enum)
    - Resources: testing/resources/task.py (Task.create, mark_completed)
    - Resources: testing/resources/project.py (Project.filter_section)
"""

from dataclasses import replace
from contextlib import nullcontext
from datetime import datetime
import json
import re
from uuid import uuid4

import pytest
import requests
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Forms, ModelTasks, Projects, Tasks, Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.project_definitions import ProjectDefinition
from testing.definitions.page_definitions import PageDefinition
from testing.definitions.model_task_definitions import ModelTaskDefinition
from testing.elements import (
    Badges,
    Buttons,
    Dropdown,
    Filters,
    Modal,
    ProjectFilterConditions,
    FormElements,
    FormSelect,
    ProjectSelect,
    SpinnerButtons,
    Tabs,
)
from testing.resources import Form, ModelTask, Page, Project, Task
from testing.utility.network import expect_successful_response
from testing.utility.polling import expect_poll_result
from testing.utility.reconnect import expect_reconnect_refresh

pytestmark = pytest.mark.e2e


# @pair filters:tab-open
def test_filters_tab_opens(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)

    filters = Filters(user, project)
    expect(filters.save_button).to_be_visible()
    expect(filters.run_button).to_be_visible()
    expect(filters.reset_button).to_be_visible()
    expect(filters.conditions).to_be_visible()


# @matrix filters : completed conditions
def test_project_filter_conditions_include_task_fields(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_filter_project.get(user)
    user.go(project)

    filters = Filters(user, project)
    panel = Dropdown(filters.conditions).open()

    expect(panel.get_by_role("option", name="Task Name", exact=True)).to_be_visible()
    expect(panel.get_by_role("option", name="Has Status", exact=True)).to_be_visible()
    expect(panel.get_by_role("option", name="Completed", exact=True)).to_be_visible()


# @matrix filters : malformed-contract unavailable-source
# @pairs permissions:unavailable-source request-errors:stable-status
def test_filter_preview_rejects_malformed_and_forged_contracts(
    get_user,
    browser_failures,
):
    user = get_user(Users.OWNER)
    project = Projects.test_filter_project.get(user)
    user.go(project)
    endpoint = f"{project.url.rsplit('/projects/', 1)[0]}/filters/{project.key}/test"
    path = f"/filters/{project.key}/test"

    def request_contract(value):
        return user.page.evaluate(
            """async ({endpoint, contract}) => {
                const query = new URLSearchParams({contract});
                const response = await fetch(`${endpoint}?${query}`, {
                    headers: {"X-Lagniappe-Request": "true"},
                });
                return {status: response.status, text: await response.text()};
            }""",
            {"endpoint": endpoint, "contract": value},
        )

    with browser_failures.expect_http_error(user, status=400, path=path):
        malformed = request_contract("{not-json")
    assert malformed == {
        "status": 400,
        "text": "Filter contract contains malformed JSON.",
    }

    forged_contract = json.dumps(
        {
            "version": 1,
            "conditions": [
                {
                    "source_id": "unrelated-source",
                    "field": "name",
                    "comparator": "substring",
                    "values": ["Filter"],
                }
            ],
        }
    )
    with browser_failures.expect_http_error(user, status=422, path=path):
        forged = request_contract(forged_contract)
    assert forged["status"] == 422
    assert "unavailable field" in forged["text"]


# --- String conditions (Task Name) ---


# @matrix filters : results-layout run-results string-condition
# @template projects/filters.html::task_filters
def test_filter_by_task_name(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)

    badges = filters.name_contains("Filter").add_filter()
    expect(badges).to_be_visible()
    badge = Badges.TASK.contains(badges, "Filter")
    expect(badge).to_contain_text(ProjectFilterConditions.NAME.value)

    results = filters.run()
    expect(results).to_be_visible()
    row = results.locator("tr").filter(has_text=task.definition.name)
    expect(row).to_be_visible()
    table_frame = results.locator("[data-role='results-table']")
    expect(table_frame).to_have_css("border-top-width", "1px")
    expect(table_frame).to_have_css("outline-style", "none")
    expect(table_frame.locator("[data-role='table']")).to_have_css("border-top-width", "0px")
    form_box = filters.form.bounding_box()
    table_box = table_frame.bounding_box()
    assert table_box["x"] == pytest.approx(form_box["x"], abs=1)
    assert table_box["width"] == pytest.approx(form_box["width"], abs=1)


# @matrix filters : exact-match run-results string-condition
def test_filter_by_task_name_exact(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)

    badges = filters.name_equals(task.definition.name).add_filter()
    expect(badges).to_be_visible()
    definition = json.loads(
        badges.locator("input[name='definition']").input_value()
    )
    assert definition["values"] == [task.definition.name]

    results = filters.run()
    expect(results).to_be_visible()
    row = results.locator("tr").filter(has_text=task.definition.name)
    expect(row).to_be_visible()


# --- Timestamp conditions (Due Date) ---


# @matrix filters : date-condition run-results
def test_filter_by_due_date(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_due_date.get(user)
    project = user.go(task.project)

    today = datetime.now().date().isoformat()

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.DUE_DATE)

    badges = filters.due_date("is on or after", today).add_filter()
    expect(badges).to_be_visible()

    results = filters.run()
    expect(results).to_be_visible()
    row = results.locator("tr").filter(has_text=task.definition.name)
    expect(row).to_be_visible()


# --- List / entity-valued conditions (Categories) ---


def _expect_only_matching_task(results, matching_task, excluded_task):
    matching_row = results.locator("tr").filter(
        has_text=matching_task.definition.name
    )
    excluded_row = results.locator("tr").filter(has_text=excluded_task.definition.name)

    expect(matching_row).to_be_visible()
    expect(excluded_row).not_to_be_visible()


def _attached_form_filter_context(user):
    matching_task = Tasks.test_filter_by_attached_form_match.get(user)
    excluded_task = Tasks.test_filter_by_attached_form_nonmatch.get(user)
    attached_form = Forms.test_project_filter_task_form.get(user)
    project = user.go(matching_task.project)
    filters = Filters(user, project)

    filters.set_condition(attached_form)
    expect(filters.badges).to_contain_text(attached_form.definition.name)
    expect(filters.form_conditions).to_be_visible()

    return filters, matching_task, excluded_task


# @matrix filters : run-results string-condition view-access
# @pair cache:permission-revalidation
# @matrix filters polling : saved-filter permissions revision
# @pair permissions:etag
# @pair permissions:authorization
# @template tasks/index.html::view
# @template forms/restrictions.html::restrict_access
@pytest.mark.parametrize("mode", ["preview", "saved"])
@pytest.mark.parametrize("permission_source", ["task_form", "model_form", "page", "page_form"])
def test_project_filter_results_respect_task_permissions(get_user, mode, permission_source):
    owner = get_user(Users.OWNER)
    token = f"Permission Filter {uuid4().hex}"
    project = Project(
        user=owner, definition=ProjectDefinition(name=f"{token} Project")
    ).create()
    form = Form(
        user=owner,
        definition=FormDefinition(name=f"{token} Form", form_type="page" if permission_source == "page_form" else "task"),
    ).create()
    category = Entities.CATEGORY.create({"name": f"{token} Category"})
    category.save()
    page = Entities.PAGE.create({
        "name": f"{token} Page", "model": category,
        "form": form.entity if permission_source == "page_form" else None,
    })
    page.save()
    visible_page = Entities.PAGE.create({"name": f"{token} Visible Page"})
    visible_page.save()
    visible_task = Entities.TASK.create({
        "name": f"{token} Visible", "page": visible_page, "project": project.entity,
    })
    visible_task.save()
    model = None
    if permission_source == "model_form":
        model = ModelTask(user=owner, definition=ModelTaskDefinition(name=f"{token} Model", project=None))
        model.entity = Entities.MODEL_TASK.create(project.entity, {"name": model.definition.name, "form": form.entity})
        model.entity.save()
    page_resource = Page(user=owner, definition=PageDefinition(name=page.name, category=None))
    page_resource.entity = page
    owner.go(page_resource)
    create_form = page_resource.create_task_form
    task_name = f"{token} Restricted"
    create_form.locator(FormElements.NAME).fill(task_name)
    project_select = ProjectSelect(create_form)
    if model:
        project_select.panel(fill=project.definition.name)
        project_select.select_by_key(model)
        assert FormSelect(create_form).contains(form)
    else:
        project_select.select(project)
        if permission_source == "task_form":
            FormSelect(create_form).select(form)
    with expect_successful_response(owner.page, method="POST", path=f"/tasks/{page_resource.key}/create",
                                    request_payload_contains=task_name):
        SpinnerButtons.CREATE.click(create_form)
    expect(create_form).not_to_be_visible()
    task_key = page_resource.active_task_list.new_item(task_name).get_attribute("data-key")
    restricted_task = Entities.fetch_one(task_key, request=Fetch.root())
    assert restricted_task.properties.project.key == project.entity.key
    assert restricted_task.properties.model.key == (model.entity.key if model else None)
    if permission_source in {"task_form", "model_form"}:
        assert restricted_task.properties.form.key == form.entity.key

    if mode == "saved":
        owner.go(project)
        owner_filters = Filters(owner, project)
        owner_filters.set_condition(ProjectFilterConditions.NAME)
        owner_filters.name_contains(token).add_filter()
        saved_filter = owner_filters.save_filter()
        saved_key = saved_filter.get_attribute("data-key")

    viewer = get_user(Users.general_models_view_only)
    project = viewer.go(project)
    filters = Filters(viewer, project)
    if mode == "preview":
        filters.set_condition(ProjectFilterConditions.NAME)
        expect(filters.name_contains(token).add_filter()).to_be_visible()
        with expect_successful_response(viewer.page, method="GET", path=f"/filters/{project.key}/test") as response_info:
            results = filters.run()
        initial_response = response_info.value
    else:
        saved_row = filters.section.locator(f"{Filters.SAVED_FILTERS} li[data-key='{saved_key}']")
        with viewer.page.expect_navigation(url=f"**/filters/{saved_key}") as response_info:
            saved_row.get_by_role("link", name="Run saved filter").click()
        initial_response = response_info.value
        results = viewer.locate("[lp-view][data-kind='task'] #table")

    etag = initial_response.headers["etag"]
    assert "no-store" not in initial_response.headers["cache-control"]

    def conditional_get(revision):
        # Check the server's conditional response directly; the service worker
        # turns a 304 into the cached 200 response for browser consumers.
        response = requests.get(
            initial_response.url,
            cookies={cookie["name"]: cookie["value"] for cookie in viewer.page.context.cookies()},
            headers={"If-None-Match": revision, "User-Agent": viewer.page.evaluate("navigator.userAgent")},
            allow_redirects=False,
            timeout=10,
        )
        return {"status": response.status_code, "etag": response.headers.get("etag")}

    assert conditional_get(etag)["status"] == 304

    # Both records must match before the form's real save changes access.
    visible_row = results.locator(f"tr[data-key='{visible_task.urlsafe_key}']")
    restricted_row = results.locator(f"tr[data-key='{restricted_task.urlsafe_key}']")
    expect(visible_row).to_be_visible()
    expect(restricted_row).to_be_visible()

    if permission_source == "page":
        owner.go(page_resource)
        Tabs(owner).info
        owner.locate(Page.PAGE_PERMISSIONS_TOGGLE).click()
        restriction = owner.locate(Page.PAGE_PERMISSIONS_FORM).locator(Page.PAGE_RESTRICT_OWNER)
    else:
        builder = form.builder
        restriction = builder.restrictions().locator(builder.SPECIFIC_ACCESS_OWNER)

    for restrict in (True, False):
        boundary = (
            expect_poll_result(
                viewer.page, subscription_id="view:channel:tasks", timeout=45_000,
            )
            if mode == "saved" else nullcontext()
        )
        with boundary:
            if permission_source == "page":
                restriction.set_checked(restrict)
                with expect_successful_response(owner.page, method="PUT", path=f"/pages/{page_resource.key}/view-access"):
                    owner.locate(Page.PAGE_PERMISSIONS_FORM).locator("button[type='submit']").click()
            else:
                restriction.set_checked(restrict)
                builder.save_restrictions()
            if mode == "preview":
                filters.run()
        fresh = conditional_get(etag)
        assert fresh["status"] == 200
        assert fresh["etag"] != etag
        etag = fresh["etag"]
        expect(visible_row).to_be_visible()
        if restrict:
            expect(restricted_row).to_have_count(0)
        else:
            expect(restricted_row).to_be_visible()


# @matrix filters : category entity-condition run-results
def test_filter_by_category(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    category = Categories.test_create_page_task.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.CATEGORY)

    badges = filters.category(category.definition.name).add_filter()
    expect(badges).to_be_visible()

    results = filters.run()
    expect(results).to_be_visible()
    row = results.locator("tr").filter(has_text=task.definition.name)
    expect(row).to_be_visible()


# @matrix filters : assigned-user entity-condition run-results
def test_filter_by_assigned_user(get_user):
    user = get_user(Users.OWNER)
    assignee = Users.create_user.get(user)
    task = Tasks.test_filter_by_assigned_user.get(user)
    unrelated_task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.ASSIGNED_TO)

    badges = filters.assigned_to(assignee.definition.name).add_filter()
    expect(badges).to_be_visible()
    expect(badges).to_contain_text(assignee.definition.name)

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, task, unrelated_task)


# --- Dynamic entity conditions (Model Task) ---


# @matrix filters : entity-condition model-task run-results
def test_filter_by_model_task(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_model_task.get(user)
    model_task = ModelTasks.test_filter_by_model_task.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(model_task)

    expect(filters.badges).to_be_visible()

    results = filters.run()
    expect(results).to_be_visible()
    row = results.locator("tr").filter(has_text=task.definition.name)
    expect(row).to_be_visible()


# --- Dynamic attached-form field conditions ---


# @matrix filters : attached-form run-results string-condition
def test_filter_by_attached_form_text_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_task, excluded_task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Inspection Notes")
        .text("contains", "Urgent")
        .add_filter()
    )
    expect(badges).to_contain_text("Inspection Notes")

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, matching_task, excluded_task)


# @matrix filters : attached-form number-condition run-results
def test_filter_by_attached_form_number_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_task, excluded_task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Risk Score")
        .number("is greater than or equal to", "90")
        .add_filter()
    )
    expect(badges).to_contain_text("Risk Score")

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, matching_task, excluded_task)


# @matrix filters : attached-form boolean-condition run-results
def test_filter_by_attached_form_checkbox_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_task, excluded_task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Requires Follow Up").checkbox(True).add_filter()
    )
    expect(badges).to_contain_text("Requires Follow Up")

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, matching_task, excluded_task)


# @matrix filters : attached-form checkbox quick-edit reload-persistence
def test_saved_filter_quick_edit_persists_attached_form_checkbox(get_user):
    user = get_user(Users.OWNER)
    task = Task(
        user=user,
        definition=replace(
            Tasks.test_filter_by_attached_form_nonmatch.value.definition,
            name=f"Attached Form Quick Edit {uuid4().hex}",
        ),
    ).create()
    filters, _matching_task, _excluded_task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Inspection Notes")
        .text("contains", "Routine")
        .add_filter()
    )
    expect(badges).to_contain_text("Inspection Notes")

    saved_filter = filters.save_filter()
    expect(saved_filter).to_be_visible()
    saved_filter.locator("a[aria-label='Run saved filter']").click()

    view = user.locate("[lp-view][data-kind='task']")
    expect(view).to_have_attribute("initialized", "")
    table = view.locator("#table")

    visibility_toggle = table.locator(
        "button[lp-show='table:TableVisibility'][aria-label='Choose visible columns']"
    )
    visibility_toggle.click()
    visibility = table.locator("tr[data-widget='TableVisibility']")
    expect(visibility).to_have_attribute("data-visible", "true")

    field = "filter-flagged"
    visible_toggle = visibility.locator(f"input[type='checkbox'][name='{field}']")
    expect(visible_toggle).to_be_visible()
    visible_toggle.set_checked(True)
    visibility_toggle.click()

    row = table.locator(f"tbody tr[data-key='{task.key}']")
    expect(row).to_be_visible()
    cell = row.locator(f"td[data-column='{field}']")
    expect(cell).to_be_visible()
    expect(cell).to_have_attribute("data-edit-value", "false")

    edit_toggle = view.locator("button[lp-show='table:TableEditor']")
    edit_toggle.click()
    checkbox = cell.locator(f"input[type='checkbox'][name='{field}']")
    expect(checkbox).to_be_visible()
    expect(checkbox).not_to_be_checked()

    with user.page.expect_response("**/tasks/*/patch"):
        checkbox.set_checked(True)

    expect(checkbox).to_be_checked()
    expect(cell).to_have_attribute("data-edit-value", "true")

    user.reload()
    expect(view).to_have_attribute("initialized", "")

    row = table.locator(f"tbody tr[data-key='{task.key}']")
    cell = row.locator(f"td[data-column='{field}']")
    expect(cell).to_be_visible()
    expect(cell).to_have_attribute("data-edit-value", "true")
    expect(cell.locator("[aria-label='True']")).to_be_visible()


# @matrix filters : attached-form selector
# @pair permissions:relationship
def test_filter_by_attached_form_select_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_task, excluded_task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Review Decision")
        .choice("Approved")
        .add_filter()
    )
    expect(badges).to_contain_text("Review Decision")

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, matching_task, excluded_task)


# @matrix embedded-table : horizontal-scroll run-results table-cell-expand visibility
# @template cell.html::table_cell
# @template controls.html::expand
def test_filter_results_expands_table_submission_cell(get_user):
    user = get_user(Users.OWNER)
    filters, matching_task, excluded_task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Inspection Notes")
        .text("contains", "Urgent")
        .add_filter()
    )
    expect(badges).to_contain_text("Inspection Notes")

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, matching_task, excluded_task)

    table_container = results.locator("[data-role='table'].table-container")
    expect(table_container).to_be_visible()
    expect(table_container).to_have_css("overflow-x", "auto")

    header = results.locator("tr[data-role='column-header']")
    header.get_by_role("button", name="Choose visible columns").click()
    visibility = results.locator("tr[data-widget='TableVisibility']")
    expect(visibility).to_have_attribute("data-visible", "true")

    items_toggle = visibility.locator("input[type='checkbox'][name='filter-items']")
    expect(items_toggle).to_be_visible()
    items_toggle.set_checked(True)

    row = results.locator("tr").filter(has_text=matching_task.definition.name)
    cell = row.locator("td[data-column='filter-items']")
    expect(cell).to_be_visible()
    expect(cell).to_contain_text("1 row")

    expand = cell.locator("button[data-role='expand']")
    expect(expand).to_be_visible()
    with user.page.expect_response("**/forms/*/expand-table-cell/filter-items"):
        expand.click()

    expect(expand).to_have_attribute("data-open", "true")
    embedded = results.locator(
        "#embedded-table > tbody > tr[data-embedded='true']"
    )
    expect(embedded).to_be_visible()
    expect(embedded).to_contain_text("Note")
    expect(embedded).to_contain_text("Escalated item")


# @matrix filters : boolean-condition run-results
# @matrix status : boolean-condition computed-column run-results
def test_filter_by_has_status_renders_status_column(get_user):
    user = get_user(Users.OWNER)
    matching_task = Tasks.test_filter_by_has_status_active.get(user)
    excluded_task = Tasks.test_filter_by_has_status_inactive.get(user)
    attached_form = Forms.test_task_status_form.get(user)
    project = user.go(matching_task.project)

    filters = Filters(user, project)
    filters.set_condition(attached_form)
    expect(filters.badges).to_contain_text(attached_form.definition.name)

    filters.set_condition(ProjectFilterConditions.HAS_STATUS)
    badges = filters.boolean("status").add_filter()
    expect(badges).to_contain_text("Has Status")

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, matching_task, excluded_task)

    header = results.locator("tr[data-role='column-header']")
    header.get_by_role("button", name="Choose visible columns").click()
    visibility = results.locator("tr[data-widget='TableVisibility']")
    expect(visibility).to_have_attribute("data-visible", "true")

    status_toggle = visibility.locator("input[type='checkbox'][name='status-field']")
    expect(status_toggle).to_be_visible()
    status_toggle.set_checked(True)

    row = results.locator("tr").filter(has_text=matching_task.definition.name)
    cell = row.locator("td[data-column='status-field']")
    expect(cell).to_be_visible()
    expect(cell).to_contain_text("Reorder Needed")


# --- Edge cases and compound filters ---


# @pair filters:empty-results
def test_filter_no_results(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)
    filters.name_contains("ZZZZNONEXISTENT").add_filter()

    results = filters.run()
    expect(results).to_be_visible()
    expect(results).to_contain_text("No matching tasks found")


# @pair filters:reset
def test_filter_reset(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)
    filters.name_contains("Filter").add_filter()

    expect(filters.badges).to_be_visible()

    filters.reset()

    expect(filters.badges).not_to_be_visible()


# @matrix filters : delete reload-persistence save saved-filters shared-viewer
def test_filter_save(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)
    filters.name_contains("Filter").add_filter()

    saved_filter = filters.save_filter()
    filter_key = saved_filter.get_attribute("data-key")
    expect(saved_filter).to_contain_text("Task Name")
    expect(saved_filter).to_contain_text("Filter")

    user.reload(project)
    reloaded_filters = Filters(user, project)
    reloaded_saved = reloaded_filters.section.locator(Filters.SAVED_FILTERS)
    expect(reloaded_saved).to_be_visible()
    expect(reloaded_saved.locator(f"li[data-key='{filter_key}']")).to_be_visible()

    viewer = get_user(Users.general_models_view_only)
    viewer.go(project)
    viewer_filters = Filters(viewer, project)
    viewer_saved = viewer_filters.section.locator(Filters.SAVED_FILTERS)
    viewer_filter = viewer_saved.locator(f"li[data-key='{filter_key}']")
    expect(viewer_filter).to_be_visible()
    expect(viewer_filter.locator("[lp-delete]")).to_have_count(0)

    user.go(project)
    owner_filters = Filters(user, project)
    owner_saved = owner_filters.section.locator(Filters.SAVED_FILTERS)
    owner_filter = owner_saved.locator(f"li[data-key='{filter_key}']")
    expect(owner_filter).to_be_visible()
    owner_filter.locator(Buttons.LP_DELETE).click()
    Modal(user.page).delete()
    expect(owner_filter).not_to_be_visible()

    user.reload(project)
    reloaded_filters = Filters(user, project)
    reloaded_saved = reloaded_filters.section.locator(Filters.SAVED_FILTERS)
    expect(reloaded_saved.locator(f"li[data-key='{filter_key}']")).to_have_count(0)


# @matrix filters : compound run-results
def test_filter_multiple_conditions(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_due_date.get(user)
    project = user.go(task.project)
    today = datetime.now().date().isoformat()

    filters = Filters(user, project)

    filters.set_condition(ProjectFilterConditions.NAME)
    filters.name_contains("Filter").add_filter()

    filters.set_condition(ProjectFilterConditions.DUE_DATE)
    filters.due_date("is on or after", today).add_filter()

    results = filters.run()
    expect(results).to_be_visible()
    row = results.locator("tr").filter(has_text=task.definition.name)
    expect(row).to_be_visible()


# @pair filters:saved-filter
# @template table.html::row
def test_saved_in_progress_filter_removes_completed_task_after_back_navigation(
    get_user,
):
    user = get_user(Users.OWNER)
    task = Task(
        user=user,
        definition=replace(
            Tasks.test_filter_by_completed.value.definition,
            name=f"Saved In Progress Filter Task {uuid4().hex}",
        ),
    ).create()
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.COMPLETED)
    filters.boolean("in progress").add_filter()

    saved_filter = filters.save_filter()
    expect(saved_filter).to_be_visible()

    with user.page.expect_navigation():
        saved_filter.locator("a[href*='/filters/']").click()
    user.page.wait_for_selector("[lp-view][initialized]")

    filtered_row = user.locate("#table tbody tr[lp-entity]").filter(
        has_text=task.definition.name
    )
    expect(filtered_row).to_be_visible()
    filtered_row.locator("td[data-column='name'] a[data-role='title']").click()
    expect(user.locate(f"li[data-key='{task.key}']")).to_be_visible()

    task.complete()

    user.page.go_back()
    user.page.wait_for_selector("[lp-view][initialized]")
    expect(filtered_row).not_to_be_attached(timeout=15000)
    expect(user.locate("#table tbody")).to_have_attribute("loaded", "")


# @pair filters:saved-filter
# @pairs polling:task-index reconnect-refresh:task-index
# @template tasks/index.html::view
# @template table.html::row
def test_saved_in_progress_filter_refreshes_after_reconnect(
    get_user,
    browser_failures,
):
    user = get_user(Users.OWNER)
    task = Task(
        user=user,
        definition=replace(
            Tasks.test_filter_by_completed.value.definition,
            name=f"Saved Filter Reconnect Task {uuid4().hex}",
        ),
    ).create()
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.COMPLETED)
    filters.boolean("in progress").add_filter()
    saved_filter = filters.save_filter()
    filter_key = saved_filter.get_attribute("data-key")

    with user.page.expect_navigation():
        saved_filter.locator("a[href*='/filters/']").click()
    user.page.wait_for_selector("[lp-view][initialized]")

    root = user.locate("[lp-view]")
    expect(root).to_have_attribute("data-key", filter_key)
    expect(root).to_have_attribute("data-poll-channel", "tasks")
    expect(root).to_have_attribute("data-poll-entity-revision", re.compile(r".+"))
    expect(root).to_have_attribute("data-fingerprint", re.compile(r".+"))

    filtered_row = user.locate(f"#table tbody tr[data-key='{task.key}']")
    expect(filtered_row).to_be_visible()

    with expect_poll_result(
        user.page,
        subscription_id=f"view:entity:{filter_key}",
    ):
        with expect_reconnect_refresh(user, browser_failures):
            task.mark_completed()
            user.offline = False

    expect(filtered_row).not_to_be_attached()
    expect(user.locate("#table tbody")).to_have_attribute("loaded", "")
