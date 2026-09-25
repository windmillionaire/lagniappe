import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Submissions, Users
from testing.elements import SpinnerButtons
from testing.utility.network import manual_mutation_headers

pytestmark = pytest.mark.e2e


def _table_field(page):
    table = page.info_form.locator("[id^='items-'].form-element")
    expect(table).to_be_visible()
    return table


def _table_rows(table):
    return table.locator("tbody tr")


def _open_row_actions(table, index):
    row = _table_rows(table).nth(index)
    expect(row).to_be_visible()
    row.hover()
    row.focus()

    actions = row.locator("[data-role='row-actions']")
    expect(actions).to_be_visible()
    expect(actions).to_have_attribute("data-index", str(index))
    return actions


def _add_table_row(user, table, note):
    table.locator("button[data-role='create']").click()
    form = table.locator("form")
    expect(form).to_be_visible()
    form.locator("input[name='row_note']").fill(note)

    with user.page.expect_response("**/validate-row/items**"):
        form.locator("button[data-role='validate']").click()

    expect(form).not_to_be_attached()


# @matrix template-formatting : date number phone time
# @pair pages:basic-inputs
def test_basic_input_submission(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_basic_input_submission.get(user)
    user.go(page)

    submission = Submissions.basic_inputs.get()
    page.set_submission(submission)
    page.submit_and_verify_submission(submission)


# @matrix pages tasks : submission-validation
# @pair request-errors:plain-validation
@pytest.mark.parametrize("entity_kind", ["PAGE", "TASK"])
def test_invalid_typed_submission_returns_error_without_saving(get_user, entity_kind):
    user = get_user(Users.OWNER)
    # These cases register page forms; keep that state out of the shared ACL
    # category used by the submitted-reference permission tests.
    category = Entities.CATEGORY.create({"name": f"Typed validation {entity_kind}"})
    category.save()
    form = Entities.FORM.create({
        "name": f"Typed validation {entity_kind}",
        "form-type": entity_kind.lower(),
        "schema": [
            {"id": "note", "type": "input", "input": "text", "title": "Note"},
            *[
                {"id": kind, "type": "input", "input": kind, "title": kind.title()}
                for kind in ("email", "time", "date", "number")
            ],
        ],
    })
    form.save()
    page = Entities.PAGE.create({
        "name": f"Typed validation page {entity_kind}",
        "model": category,
        "categories": [],
        **({"form": form} if entity_kind == "PAGE" else {}),
    })
    page.save()
    entity = page if entity_kind == "PAGE" else Entities.TASK.create({
        "name": "Typed validation task", "page": page, "form": form,
    })
    answers = {
        "note": "Keep this", "email": "ada@example.com", "time": "09:30",
        "date": "2026-09-19", "number": "0",
    }
    entity.form_submission(answers)
    entity.save()

    user.navigate(f"{SETTINGS.test_config['BASE_URL']}/pages/{page.urlsafe_key}")
    cookies = {cookie["name"]: cookie["value"] for cookie in user.page.context.cookies()}
    headers = manual_mutation_headers(user.page.url, user.locate("#token").input_value())
    before = Entities.fetch_one(entity.key, request=Fetch.direct())
    saved = dict(before.db)
    assert saved["submission"]
    payload = {
        **answers, "note": "Do not save", "name": entity.name,
        "category": category.urlsafe_key, "form": form.urlsafe_key,
        "form-generation": str(form.generation), "active": "TaskForm",
        "form-revision": before.autofill_revision,
    }
    route = "pages" if entity_kind == "PAGE" else "tasks"

    # Bypass native input validation: the server must enforce the boundary too.
    for field, invalid in (
        ("email", "not-an-email"), ("time", "25:99"),
        ("date", "2026-02-30"), ("number", "NaN"),
    ):
        response = requests.put(
            f"{SETTINGS.test_config['BASE_URL']}/{route}/{entity.urlsafe_key}/update",
            data={**payload, field: invalid}, cookies=cookies, headers=headers,
            allow_redirects=False, timeout=10,
        )
        assert response.status_code == 422, (field, response.text)
        assert response.headers["Content-Type"].startswith("text/plain")
        assert field.title() in response.text
        after = Entities.fetch_one(entity.key, request=Fetch.root())
        assert after.db == saved


# @matrix pages : read-mode selection-fields submission
def test_selection_submission(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_selection_submission.get(user)
    user.go(page)

    submission = Submissions.selection_types.get()
    page.set_submission(submission)
    page.submit_and_verify_submission(submission)

    for field_id, labels in {
        "radio-priorityef": ("Medium",),
        "select-statusgh": ("Published",),
        "select-tagsij12": ("Featured", "Sale"),
    }.items():
        read_value = page.info_form.locator(
            f"[id^='{field_id}-'] [data-role='read']"
        )
        expect(read_value).to_be_visible()
        expect(read_value.locator("i")).to_have_count(0)
        for label in labels:
            expect(read_value).to_contain_text(label)


# @matrix pages : link-field submission
# @pair form-link:read-layout
# @style form.linkLabel
def test_link_submission(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_link_submission.get(user)
    user.go(page)

    submission = Submissions.link_external.get()
    page.set_submission(submission)
    page.submit_and_verify_submission(submission)

    read_value = page.info_form.locator(
        "[id^='link-ab12-'] [data-role='read']"
    )
    layout = read_value.evaluate(
        """readValue => {
          const label = readValue.querySelector(".form-link-label");
          const icon = readValue.querySelector(".icon[data-icon='out']");
          return {
            iconHeight: icon.getBoundingClientRect().height,
            lineHeight: Number.parseFloat(getComputedStyle(label).lineHeight),
          };
        }"""
    )
    assert layout["lineHeight"] == pytest.approx(layout["iconHeight"])


# @matrix form-table : delete edit reload reorder row-actions
def test_table_submission_row_actions(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_table_submission.get(user)
    user.go(page)

    table = _table_field(page)
    rows = _table_rows(table)
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Row one")

    _add_table_row(user, table, "Row two")
    expect(rows).to_have_count(2)
    expect(rows.nth(1)).to_contain_text("Row two")

    first_actions = _open_row_actions(table, 0)
    expect(first_actions.locator("button[data-role='moveUp']")).to_be_disabled()
    expect(first_actions.locator("button[data-role='moveDown']")).to_be_enabled()

    second_actions = _open_row_actions(table, 1)
    expect(second_actions.locator("button[data-role='moveUp']")).to_be_enabled()
    expect(second_actions.locator("button[data-role='moveDown']")).to_be_disabled()
    second_actions.locator("button[data-role='moveUp']").click()

    expect(second_actions).not_to_be_visible()
    expect(rows.nth(0)).to_contain_text("Row two")
    expect(rows.nth(1)).to_contain_text("Row one")
    edit_actions = _open_row_actions(table, 0)
    edit_actions.locator("button[data-role='edit']").click()
    edit_form = table.locator("form")
    expect(edit_form).to_be_visible()
    expect(edit_form).to_be_in_viewport()
    edit_form.locator("input[name='row_note']").fill("Row two edited")

    with user.page.expect_response("**/validate-row/items**"):
        edit_form.locator("button[data-role='validate']").click()

    expect(edit_form).not_to_be_attached()
    expect(rows.nth(0)).to_contain_text("Row two edited")
    delete_actions = _open_row_actions(table, 1)
    delete_actions.locator("button[data-role='delete']").click()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Row two edited")
    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(page.info_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(page.info_form)
    user.reload(page)
    table = _table_field(page)
    rows = _table_rows(table)
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Row two edited")


# @matrix form-table : mobile row-actions touch-gesture
def test_table_submission_mobile_row_action_gestures(get_user):
    user = get_user(Users.OWNER, has_touch=True)
    page = Pages.test_table_submission.get(user)
    user.go(page)
    user.mobile = True

    table = _table_field(page)
    rows = _table_rows(table)
    actions = table.locator("[data-role='row-actions']")
    expect(rows).to_have_count(1)
    rows.first.scroll_into_view_if_needed()
    expect(rows.first).to_be_in_viewport()
    expect(actions).not_to_be_visible()

    rows.first.tap(position={"x": 12, "y": 12})
    expect(actions).to_be_visible()

    rows.first.tap(position={"x": 12, "y": 12})
    expect(actions).not_to_be_visible()
