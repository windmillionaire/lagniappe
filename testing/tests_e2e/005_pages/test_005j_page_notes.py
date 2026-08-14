"""E2E coverage for Page note visibility, composition, and deletion."""

from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Users
from testing.elements import Buttons, Modal
from testing.utility import TestFile as _TestFile


pytestmark = pytest.mark.e2e


def _unique(label):
    return f"{label} {uuid4().hex[:8]}"


def _save_page_note(page, user, body, visibility="private"):
    note = Entities.NOTE.create(
        {
            "parent": page.entity,
            "user": user.entity,
            "body": body,
            "visibility": visibility,
            "scope": "page",
        }
    )
    Entities.save(note)
    return note


def _page_note(user, body):
    return user.locate("#page-notes li[data-kind='note']").filter(
        has_text=body
    ).first


def _open_note_composer(user):
    user.page.get_by_role("button", name="Page actions").click()
    menu = user.page.get_by_role("menu", name="Page actions")
    expect(menu).to_be_visible()
    menu.get_by_role("menuitem", name="Add note").click()
    composer = user.locate("#page-notes [data-widget='CreateNote']")
    expect(composer).to_be_visible()
    return composer


# @pair notes:attribute-gate
# @pair pages:attribute-gate
# @pair notes:load
# @pair notes:shared
# @pair notes:private
# @pair notes:viewer
# @pair notes:owner
# @pair pages:load
# @pair pages:shared
# @pair pages:private
# @pair pages:viewer
# @pair pages:owner
# @pair permissions:load
# @pair permissions:shared
# @pair permissions:private
# @pair permissions:viewer
# @pair permissions:owner
# @template pages/page.html::view_header
# @template pages/notes.html::notes_section
# @template pages/notes.html::note_list
# @template notes.html::note_item
def test_page_notes_visibility_and_title_menu(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    page = Pages.acl_lab_visible.get(owner)
    shared_body = _unique("Shared Page note")
    private_body = _unique("Private Page note")
    _save_page_note(page, owner, shared_body, visibility="everyone")
    _save_page_note(page, owner, private_body)

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(page)
    note_list = viewer.locate("#page-notes [data-widget='BaseList']")
    expect(note_list).to_have_attribute("loaded", "")
    expect(_page_note(viewer, shared_body)).to_be_visible()
    expect(_page_note(viewer, shared_body).locator(Buttons.LP_DELETE)).not_to_be_attached()
    expect(_page_note(viewer, private_body)).not_to_be_attached()
    viewer.page.get_by_role("button", name="Page actions").click()
    viewer_menu = viewer.page.get_by_role("menu", name="Page actions")
    expect(viewer_menu).to_be_visible()
    expect(viewer_menu.get_by_role("menuitem", name="Star", exact=True)).to_be_visible()
    expect(viewer_menu.get_by_role("menuitem", name="Add note")).not_to_be_attached()
    expect(viewer_menu.get_by_role("menuitem", name="Delete")).not_to_be_attached()

    owner.go(page)
    expect(owner.locate("#page-notes [data-widget='BaseList']")).to_have_attribute(
        "loaded", ""
    )
    expect(_page_note(owner, shared_body)).to_be_visible()
    expect(_page_note(owner, private_body)).to_be_visible()

    composer = _open_note_composer(owner)
    header = owner.locate("[data-nav='view']")
    header_box = header.bounding_box()
    composer_box = composer.bounding_box()
    assert header_box and composer_box
    assert composer_box["y"] >= header_box["y"] + header_box["height"]

    page_without_notes = Pages.test_create_page_task.get(owner)
    notes_url = f"{page_without_notes.url}/notes"
    with browser_failures.expect_http_error(owner, status=404, path=notes_url):
        owner.navigate(notes_url)
        expect(owner.page).to_have_title("Error 404")


# @pair notes:create
# @pair notes:body
# @pair notes:photo
# @pair notes:visibility
# @pair notes:scope
# @pair notes:validation
# @pair pages:create
# @pair pages:body
# @pair pages:photo
# @pair pages:visibility
# @pair pages:scope
# @pair pages:validation
# @pair request-errors:plain-validation
# @template pages/page.html::view_header
# @template pages/notes.html::notes_section
# @template pages/notes.html::note_list
# @template notes.html::composer
# @template notes.html::note_item
# @style note.section
def test_page_note_text_photo_and_delete_modal(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    page = owner.go(Pages.test_create_page)
    body = _unique("Page text and photo note")
    notes_section = owner.locate("#page-notes")
    note_list = notes_section.locator("[data-widget='BaseList']")
    expect(note_list).to_have_attribute("loaded", "")
    expect(notes_section).to_be_hidden()

    composer = _open_note_composer(owner)
    expect(notes_section).to_be_visible()
    composer.locator("[lp-close='page-notes:BaseList']").click()
    expect(notes_section).to_be_hidden()

    composer = _open_note_composer(owner)

    notes_path = f"/pages/{page.key}/notes"
    with browser_failures.expect_http_error(owner, status=422, path=notes_path):
        with owner.page.expect_response(
            lambda response: response.request.method == "POST"
            and urlsplit(response.url).path == notes_path
        ) as invalid_response:
            composer.locator("button[type='submit']").click()
        assert invalid_response.value.status == 422
        expect(composer.locator("[data-role='error']")).to_contain_text(
            "Add a note before saving."
        )

    composer.locator("textarea[name='body']").fill(body)
    composer.locator("input[name='visibility'][value='everyone']").check()
    with owner.page.expect_file_chooser() as chooser_info:
        composer.locator("[data-action='add-photo']").click()
    chooser_info.value.set_files(_TestFile("editor_test_image.jpeg").path)
    expect(composer.locator("textarea[name='body']")).to_have_value(body)
    expect(composer.locator("[data-role='photo-preview']")).to_be_visible()

    with owner.page.expect_response("**/pages/*/notes"):
        composer.locator("button[type='submit']").click()

    item = _page_note(owner, body)
    expect(item).to_be_visible()
    expect(item.locator("img")).to_be_attached()
    expect(item).to_contain_text("Everyone")
    key = item.get_attribute("data-key")
    note = Entities.fetch_one(key, request=Fetch.direct())
    assert note.body == body
    assert note.visibility == "everyone"
    assert note.scope == "page"
    assert note.properties.parent.key == page.entity.key
    assert "photo" in note.assets

    item.locator(Buttons.LP_DELETE).click()
    modal = Modal(owner.page)
    expect(modal.element).to_contain_text("Delete Note")
    modal.element.get_by_role("button", name="Cancel").click()
    expect(modal.element).to_be_hidden()
    expect(item).to_be_visible()

    item.locator(Buttons.LP_DELETE).click()
    with owner.page.expect_response(
        lambda response: response.request.method == "DELETE"
        and response.url.endswith(f"/l/activity/{key}")
    ):
        modal.delete()
    expect(item).not_to_be_attached()
    expect(notes_section).to_be_hidden()
    assert Entities.fetch_one(key, request=Fetch.root()) is None
