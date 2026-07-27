"""
Tests for the CSV ingress import wizard on file pages.

Verified against:
- lagniappe/web/routes/files/ingress.py
- lagniappe/web/templates/files/ingress.html
- lagniappe/web/templates/files/status.html
- lagniappe/web/templates/files/status/*.html
- src/script/widgets/ingress.mjs
"""

import re

from playwright.sync_api import expect
import pytest

from lagniappe.core.entities import Entities
from testing.definitions import Categories, Forms, SitePages, Uploads, Users
from testing.elements import IngressWizard, SpinnerButtons
from testing.resources import File

pytestmark = pytest.mark.e2e


PAGE_IMPORT_CATEGORY = "Ingress Wizard Pages"
PAGE_IMPORT_FORM = "Ingress Wizard Page Form"
TASK_IMPORT_PROJECT = "Ingress Wizard Tasks"
TASK_IMPORT_FORM = "Ingress Wizard Task Form"
TARGET_PAGE_NAMES = ("Alpha Intake", "Beta Follow Up")


def _open_import_upload_form(user):
    admin = user.go(SitePages.ADMIN)
    return admin.open_import_upload_form()


def _upload_ingress_file(user, upload):
    admin = user.go(SitePages.ADMIN)
    file_item = admin.import_file(upload)

    file = File(user=user)
    file.key = file_item.get_attribute("data-key")

    user.go(file)
    return file, IngressWizard.open(user)


def _advance_page_import_to_assign(user, upload):
    file, wizard = _upload_ingress_file(user, upload)

    wizard.expect_stage("PROCESS_CSV", "Row Count")
    wizard.continue_stage("CHOOSE_TYPE", "Row Type")
    expect(wizard.progress.locator(wizard.ROW_TYPE_PAGE)).to_be_checked()

    wizard.continue_stage("CHOOSE_PARENT", "Choose or Create a Category")
    wizard.fill_parent_name(PAGE_IMPORT_CATEGORY)

    wizard.continue_stage("CHOOSE_FORM", "Choose or Create a Form")
    wizard.choose_form_mode("use-columns")
    wizard.fill_form_name(PAGE_IMPORT_FORM)

    wizard.continue_stage("ASSIGN_COLUMNS", "Assign Columns")
    expect(wizard.progress).to_contain_text("Form:")
    expect(wizard.progress).to_contain_text(PAGE_IMPORT_FORM)
    expect(wizard.progress.get_by_role("row", name="name")).to_be_visible()
    expect(wizard.progress.get_by_role("row", name="description")).to_be_visible()
    return file, wizard


def _advance_page_import_to_verify(user, upload):
    file, wizard = _advance_page_import_to_assign(user, upload)
    wizard.continue_stage("VERIFY_IMPORT", "Verify Page Import")
    return file, wizard


def _create_task_target_pages(user):
    category = Categories.test_empty_category.get(user)

    for name in TARGET_PAGE_NAMES:
        page = Entities.PAGE.create(
            {
                "name": name,
                "description": f"Target page for {name}",
                "model": category.entity,
                "attributes": ["tasks"],
            }
        )
        page.save()

    return category


# @features ingress
# @dimensions stage-wizard process-csv upload-counts
# @template home/ingress.html::upload_ingress_file
# @template files/ingress.html::ingress
# @template files/status.html::column_values
def test_import_wizard_opens_with_processed_csv_status(get_user):
    user = get_user(Users.OWNER)
    _, wizard = _upload_ingress_file(user, Uploads.ingress_pages_status_csv)

    wizard.expect_stage("PROCESS_CSV", "Row Count")
    expect(wizard.progress).to_contain_text("The file contains 2 rows.")
    expect(wizard.progress).to_contain_text("Columns Found")
    expect(wizard.progress).to_contain_text("name")
    expect(wizard.progress).to_contain_text("description")
    expect(wizard.progress).to_contain_text("status")
    expect(wizard.stage_button("PROCESS_CSV")).to_contain_text("Verify Columns")
    expect(wizard.stage_button("CHOOSE_TYPE")).to_contain_text("Select Entity Type")


# @features ingress
# @dimensions stage-wizard choose-type choose-parent choose-form assign-columns verify-import
# @template files/status.html::row_type_choices
# @template files/status/parent.html::category_choice
# @template files/status/form.html::form_choice
# @template files/status/assign.html::assign_columns
# @template files/status/verify.html::verify_import
def test_import_wizard_advances_through_page_import_stages(get_user):
    user = get_user(Users.OWNER)
    _, wizard = _advance_page_import_to_verify(user, Uploads.ingress_pages_stages_csv)

    expect(wizard.progress).to_contain_text(PAGE_IMPORT_CATEGORY)
    expect(wizard.progress).to_contain_text(PAGE_IMPORT_FORM)
    expect(wizard.progress).to_contain_text("Column Mapping")
    expect(wizard.progress).to_contain_text("{ name }")
    expect(wizard.progress).to_contain_text("{ description }")


# @features ingress
# @dimensions stage-wizard choose-type choose-parent choose-form assign-columns verify-import task-name
# @template files/status.html::row_type_choices
# @template files/status/parent.html::project_choice
# @template files/status/form.html::form_choice
# @template files/status/assign.html::assign_columns
# @template files/status/verify.html::verify_import
def test_import_wizard_advances_through_task_import_stages(get_user):
    user = get_user(Users.OWNER)
    _create_task_target_pages(user)
    _, wizard = _upload_ingress_file(user, Uploads.ingress_tasks_stages_csv)

    wizard.expect_stage("PROCESS_CSV", "Row Count")
    wizard.continue_stage("CHOOSE_TYPE", "Row Type")
    wizard.choose_row_type("task")
    expect(wizard.progress.locator(wizard.ROW_TYPE_TASK)).to_be_checked()

    wizard.continue_stage("CHOOSE_PARENT", "Choose or Create a Project")
    wizard.fill_parent_name(TASK_IMPORT_PROJECT)

    wizard.continue_stage("CHOOSE_FORM", "Choose or Create a Form")
    wizard.choose_form_mode("use-columns")
    wizard.fill_form_name(TASK_IMPORT_FORM)

    wizard.continue_stage("ASSIGN_COLUMNS", "Assign Columns")
    expect(wizard.progress).to_contain_text(TASK_IMPORT_FORM)
    expect(wizard.progress).to_contain_text("Each row creates a new task")
    expect(wizard.progress.get_by_role("row", name="name")).to_be_visible()
    expect(wizard.progress.get_by_role("row", name="notes")).to_be_visible()
    expect(wizard.progress.get_by_role("row", name="completed_on")).to_be_visible()
    expect(
        wizard.progress.locator("select option[value='task_name']").first
    ).to_have_text("Task Name")

    wizard.continue_stage("VERIFY_IMPORT", "Verify Task Import")
    expect(wizard.progress).to_contain_text(TASK_IMPORT_PROJECT)
    expect(wizard.progress).to_contain_text(TASK_IMPORT_FORM)
    expect(wizard.progress).to_contain_text("Column Mapping")
    expect(wizard.progress).to_contain_text("{ name }")


# @features ingress
# @dimensions stage-wizard set-stage error-handling
# @template files/status/parent.html::category_choice
def test_import_wizard_stage_navigation_reconciles_downstream_status(get_user):
    user = get_user(Users.OWNER)
    file, wizard = _upload_ingress_file(user, Uploads.ingress_pages_stage_nav_csv)

    wizard.continue_stage("CHOOSE_TYPE", "Row Type")
    wizard.continue_stage("CHOOSE_PARENT", "Choose or Create a Category")
    wizard.choose_parent_mode("existing-parent")
    wizard.continue_stage()

    wizard.expect_stage("CHOOSE_PARENT", "Choose or Create a Category")
    expect(wizard.progress.locator(wizard.ERROR)).to_contain_text(
        "Please select an existing option"
    )

    wizard.set_stage("CHOOSE_TYPE", "Row Type")
    wizard.choose_row_type("task")
    wizard.continue_stage("CHOOSE_PARENT", "Choose or Create a Project")


# @features ingress
# @dimensions import-results completed
# @template files/status/results.html::importing
# @template files/status/results.html::completed
def test_import_wizard_importing_stage_streams_results_and_completes(get_user):
    user = get_user(Users.OWNER)
    _, wizard = _advance_page_import_to_verify(user, Uploads.ingress_pages_import_csv)

    wizard.start_import()

    results = wizard.progress.locator(wizard.COMPLETED_RESULTS)
    expect(results).to_be_visible()
    expect(results).to_contain_text("Alpha Intake")
    expect(results).to_contain_text("Beta Follow Up")


# @features ingress
# @dimensions non-csv validation
def test_import_wizard_rejects_non_csv_upload(get_user):
    user = get_user(Users.OWNER)
    form = _open_import_upload_form(user)

    Uploads.plain_text_file.set(form)
    with user.page.expect_response("**/ingress") as response_info:
        SpinnerButtons.UPLOAD.click(form)

    assert response_info.value.status == 422
    expect(form).to_be_visible()
    expect(form.locator("[data-role='error']")).to_contain_text(
        "File must be a CSV file."
    )


# @features ingress
# @dimensions error-handling persistence reopen
def test_import_wizard_error_state_persists_after_reopen(get_user):
    user = get_user(Users.OWNER)
    file, wizard = _upload_ingress_file(user, Uploads.ingress_pages_error_csv)

    wizard.continue_stage("CHOOSE_TYPE", "Row Type")
    wizard.continue_stage("CHOOSE_PARENT", "Choose or Create a Category")
    wizard.choose_parent_mode("existing-parent")
    wizard.continue_stage()

    wizard.expect_stage("CHOOSE_PARENT", "Choose or Create a Category")
    expect(wizard.progress.locator(wizard.ERROR)).to_contain_text(
        "Please select an existing option"
    )

    user.go(SitePages.HOME)
    user.go(file)
    reopened = IngressWizard.open(user)

    reopened.expect_stage("CHOOSE_PARENT", "Choose or Create a Category")
    expect(reopened.progress.locator(reopened.ERROR)).to_contain_text(
        "Please select an existing option"
    )


# @features ingress
# @dimensions existing-parent existing-form
def test_import_wizard_selects_existing_parent_and_form(get_user):
    user = get_user(Users.OWNER)
    category = Categories.test_empty_category.get(user)
    form = Forms.test_create_page_form.get(user)
    _, wizard = _upload_ingress_file(user, Uploads.ingress_pages_existing_csv)

    wizard.continue_stage("CHOOSE_TYPE", "Row Type")
    wizard.continue_stage("CHOOSE_PARENT", "Choose or Create a Category")
    wizard.choose_parent_mode("existing-parent")
    wizard.select_existing_parent(category.definition.name)

    wizard.continue_stage("CHOOSE_FORM", "Choose or Create a Form")
    expect(wizard.progress).to_contain_text(category.definition.name)
    wizard.choose_form_mode("existing-form")
    wizard.select_existing_form(form.definition.name)

    wizard.continue_stage("ASSIGN_COLUMNS", "Assign Columns")
    expect(wizard.progress).to_contain_text(form.definition.name)

    wizard.continue_stage("VERIFY_IMPORT", "Verify Page Import")
    expect(wizard.progress).to_contain_text(category.definition.name)
    expect(wizard.progress).to_contain_text(form.definition.name)


# @features ingress
# @dimensions ignored-columns verify-import
def test_import_wizard_ignored_columns_are_not_imported(get_user):
    user = get_user(Users.OWNER)
    _, wizard = _advance_page_import_to_assign(user, Uploads.ingress_pages_ignored_csv)

    wizard.ignore_column("status")
    expect(wizard.column_row("status").locator("[lp-select]")).to_have_class(
        re.compile(".*opacity-50.*")
    )

    wizard.continue_stage("VERIFY_IMPORT", "Verify Page Import")
    expect(wizard.progress).to_contain_text("{ name }")
    expect(wizard.progress).to_contain_text("{ description }")
    expect(wizard.progress).not_to_contain_text("{ status }")


# @features ingress
# @dimensions task-import page-form-lookup
def test_import_wizard_task_page_form_lookup_updates_index_fields(get_user):
    user = get_user(Users.OWNER)
    page_form = Forms.test_create_category_with_form.get(user)
    _create_task_target_pages(user)
    _, wizard = _upload_ingress_file(user, Uploads.ingress_tasks_page_form_csv)

    wizard.continue_stage("CHOOSE_TYPE", "Row Type")
    wizard.choose_row_type("task")
    wizard.continue_stage("CHOOSE_PARENT", "Choose or Create a Project")
    wizard.fill_parent_name(TASK_IMPORT_PROJECT)
    wizard.continue_stage("CHOOSE_FORM", "Choose or Create a Form")
    wizard.choose_form_mode("use-columns")
    wizard.fill_form_name(TASK_IMPORT_FORM)
    wizard.continue_stage("ASSIGN_COLUMNS", "Assign Columns")
    wizard.ignore_column("name")

    wizard.continue_stage("VERIFY_IMPORT", "Verify Task Import")
    expect(wizard.section("page-index-field")).to_be_visible()
    expect(wizard.section("page-form-index")).to_contain_text("name")
    expect(wizard.section("page-form-index")).to_contain_text("Name")

    wizard.choose_page_index_mode("page-form")
    wizard.select_page_index_form(page_form.definition.name)
    wizard.select_index_source("name")
    wizard.select_index_destination("Pseudonym")

    expect(
        wizard.section("page-form-index").locator(
            "[data-option='page-form'] input[role='combobox']"
        )
    ).to_have_attribute("placeholder", page_form.definition.name)
    expect(wizard.section("page-form-index")).to_contain_text("Pseudonym")
