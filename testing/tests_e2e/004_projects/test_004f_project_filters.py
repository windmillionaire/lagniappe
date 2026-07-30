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

import json
import re
from datetime import datetime

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Forms, ModelTasks, Projects, Tasks, Users
from testing.elements import (
    Badges,
    Buttons,
    Dropdown,
    Filters,
    Modal,
    ProjectFilterConditions,
)

pytestmark = pytest.mark.e2e


# @features filters
# @dimensions tab-open
def test_filters_tab_opens(get_user):
    """Test that clicking filters tab opens filter panel."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)

    filters = Filters(user, project)
    expect(filters.save_button).to_be_visible()
    expect(filters.run_button).to_be_visible()
    expect(filters.reset_button).to_be_visible()
    expect(filters.conditions).to_be_visible()


# @features filters
# @dimensions conditions completed
def test_project_filter_conditions_include_task_fields(get_user):
    """Project filters expose task completion status."""
    user = get_user(Users.OWNER)
    project = Projects.test_filter_project.get(user)
    user.go(project)

    filters = Filters(user, project)
    panel = Dropdown(filters.conditions).open()

    expect(panel.get_by_role("option", name="Task Name", exact=True)).to_be_visible()
    expect(panel.get_by_role("option", name="Has Status", exact=True)).to_be_visible()
    expect(panel.get_by_role("option", name="Completed", exact=True)).to_be_visible()


# --- String conditions (Task Name) ---


# @features filters
# @dimensions string-condition run-results
def test_filter_by_task_name(get_user):
    """Test filtering by task name substring."""
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


# @features filters
# @dimensions string-condition exact-match run-results
def test_filter_by_task_name_exact(get_user):
    """Test filtering by exact task name match."""
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)

    badges = filters.name_equals(task.definition.name).add_filter()
    expect(badges).to_be_visible()

    results = filters.run()
    expect(results).to_be_visible()
    row = results.locator("tr").filter(has_text=task.definition.name)
    expect(row).to_be_visible()


# --- Timestamp conditions (Due Date) ---


# @features filters
# @dimensions date-condition run-results
def test_filter_by_due_date(get_user):
    """Test filtering by due date (is on or after today)."""
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


# @features filters
# @dimensions string-condition run-results view-access
def test_project_filter_results_respect_task_permissions(get_user):
    """Project filters return only matching tasks the viewer can see."""
    owner = get_user(Users.OWNER)
    visible_task = Tasks.test_filter_permission_visible.get(owner)
    hidden_task = Tasks.test_filter_permission_hidden.get(owner)
    hidden_task.entity.properties.restricted_to.add("owner")
    hidden_task.entity.save()
    project = visible_task.project

    viewer = get_user(Users.general_models_view_only)
    project = viewer.go(project)

    filters = Filters(viewer, project)
    filters.set_condition(ProjectFilterConditions.NAME)

    badges = filters.name_contains("Permission Filter").add_filter()
    expect(badges).to_be_visible()

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, visible_task, hidden_task)


# @features filters
# @dimensions entity-condition category run-results
def test_filter_by_category(get_user):
    """Test filtering by category (facets picker)."""
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


# @features filters
# @dimensions entity-condition assigned-user run-results
def test_filter_by_assigned_user(get_user):
    """Test filtering by assigned user (facets picker)."""
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


# @features filters
# @dimensions entity-condition model-task run-results
def test_filter_by_model_task(get_user):
    """Test filtering by model task (dynamic condition, no options panel)."""
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


# @features filters
# @dimensions attached-form string-condition run-results
def test_filter_by_attached_form_text_condition(get_user):
    """Test filtering by a text field from a model task's attached form."""
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


# @features filters
# @dimensions attached-form number-condition run-results
def test_filter_by_attached_form_number_condition(get_user):
    """Test filtering by a number field from a model task's attached form."""
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


# @features filters
# @dimensions attached-form boolean-condition run-results
def test_filter_by_attached_form_checkbox_condition(get_user):
    """Test filtering by a checkbox field from a model task's attached form."""
    user = get_user(Users.OWNER)
    filters, matching_task, excluded_task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Requires Follow Up").checkbox(True).add_filter()
    )
    expect(badges).to_contain_text("Requires Follow Up")

    results = filters.run()
    expect(results).to_be_visible()
    _expect_only_matching_task(results, matching_task, excluded_task)


# @pairs filters:quick-edit filters:attached-form filters:checkbox filters:reload-persistence
def test_saved_filter_quick_edit_persists_attached_form_checkbox(get_user):
    """A task form checkbox edited in a saved filter persists after reload."""
    user = get_user(Users.OWNER)
    filters, _matching_task, task = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Inspection Notes")
        .text("contains", "Routine")
        .add_filter()
    )
    expect(badges).to_contain_text("Inspection Notes")

    saved = filters.save_filter()
    saved_filter = saved.locator("li").filter(has_text="Inspection Notes")
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


# @features filters
# @dimensions attached-form select-condition run-results
def test_filter_by_attached_form_select_condition(get_user):
    """Test filtering by a select field from a model task's attached form."""
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


# @features embedded-table
# @dimensions run-results table-cell-expand visibility horizontal-scroll
# @template cell.html::table_cell
# @template controls.html::expand
def test_filter_results_expands_table_submission_cell(get_user):
    """Filter results can show and expand a table-valued attached-form column."""
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


# @pairs status:boolean-condition status:run-results status:computed-column
# @pairs filters:boolean-condition filters:run-results
def test_filter_by_has_status_renders_status_column(get_user):
    """Has Status filters active computed statuses and renders the status column."""
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


# @features filters
# @dimensions empty-results
def test_filter_no_results(get_user):
    """Test filter that matches nothing."""
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)
    filters.name_contains("ZZZZNONEXISTENT").add_filter()

    results = filters.run()
    expect(results).to_be_visible()
    expect(results).to_contain_text("No matching tasks found")


# @features filters
# @dimensions reset
def test_filter_reset(get_user):
    """Test reset button clears filters and hides results."""
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)
    filters.name_contains("Filter").add_filter()

    expect(filters.badges).to_be_visible()

    filters.reset()

    expect(filters.badges).not_to_be_visible()


# @features filters
# @dimensions saved-filters save delete reload-persistence shared-viewer
def test_filter_save(get_user):
    """Saved project filters persist and are visible to users who can view them."""
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_task_name.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.NAME)
    filters.name_contains("Filter").add_filter()

    saved = filters.save_filter()
    expect(saved).to_be_visible()
    saved_filter_pattern = re.compile(r"Task Name\s*contains\s*Filter")
    saved_filter = saved.locator("li").filter(has_text=saved_filter_pattern)
    expect(saved_filter).to_have_count(1, timeout=5000)

    user.reload(project)
    reloaded_filters = Filters(user, project)
    reloaded_saved = reloaded_filters.section.locator(Filters.SAVED_FILTERS)
    expect(reloaded_saved).to_be_visible()
    expect(
        reloaded_saved.locator("li").filter(has_text=saved_filter_pattern)
    ).to_be_visible()

    viewer = get_user(Users.general_models_view_only)
    viewer.go(project)
    viewer_filters = Filters(viewer, project)
    viewer_saved = viewer_filters.section.locator(Filters.SAVED_FILTERS)
    viewer_filter = viewer_saved.locator("li").filter(has_text=saved_filter_pattern)
    expect(viewer_filter).to_be_visible()
    expect(viewer_filter.locator("[lp-delete]")).to_have_count(0)

    user.go(project)
    owner_filters = Filters(user, project)
    owner_saved = owner_filters.section.locator(Filters.SAVED_FILTERS)
    owner_filter = owner_saved.locator("li").filter(has_text=saved_filter_pattern)
    expect(owner_filter).to_be_visible()
    owner_filter.locator(Buttons.LP_DELETE).click()
    Modal(user.page).delete()
    expect(owner_filter).not_to_be_visible()

    user.reload(project)
    reloaded_filters = Filters(user, project)
    reloaded_saved = reloaded_filters.section.locator(Filters.SAVED_FILTERS)
    expect(
        reloaded_saved.locator("li").filter(has_text=saved_filter_pattern)
    ).to_have_count(0)


# @features filters
# @dimensions compound run-results
def test_filter_multiple_conditions(get_user):
    """Test combining two filter conditions (name + due date)."""
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
# @pair reconnect-refresh:filtered-index
# @pair reconnect-refresh:back-navigation
# @template table.html::row
def test_saved_in_progress_filter_removes_completed_task_after_back_navigation(
    get_user,
):
    """Back navigation omits a completed task from its saved in-progress filter."""
    user = get_user(Users.OWNER)
    task = Tasks.test_filter_by_completed.get(user)
    project = user.go(task.project)

    filters = Filters(user, project)
    filters.set_condition(ProjectFilterConditions.COMPLETED)
    filters.boolean("in progress").add_filter()

    saved = filters.save_filter()
    saved_filter = saved.locator("li").first
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

    with user.page.expect_response("**/refresh") as refresh_info:
        user.page.evaluate(
            "document.querySelector('[lp-view]')._lp_view.refresh(true)"
        )

    request_payload = json.loads(refresh_info.value.request.post_data or "{}")
    assert request_payload["view"]["hash"]
    assert request_payload["view"]["key"] == user.locate("[lp-view]").get_attribute(
        "data-key"
    )
    assert {target["id"] for target in request_payload["targets"]} == {"table"}

    response_payload = refresh_info.value.json()
    table_refresh = next(
        target for target in response_payload["targets"] if target["id"] == "table"
    )
    assert table_refresh["fallback"] is False
    expect(filtered_row).not_to_be_attached()
