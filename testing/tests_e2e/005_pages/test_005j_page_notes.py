from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.web import app
from testing.definitions import Pages, Users
from testing.elements import Buttons, Modal
from testing.utility.test_file import TestFile as _TestFile


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


def _go_with_page_notes(user, page):
    user.go(page)
    expect(user.locate("#page-notes [data-widget='BaseList']")).to_have_attribute("loaded", "")
    return page


def _open_note_composer(user):
    user.page.get_by_role("button", name="Page actions").click()
    menu = user.page.get_by_role("menu", name="Page actions")
    expect(menu).to_be_visible()
    menu.get_by_role("menuitem", name="Add note").click()
    composer = user.locate("#page-notes [data-widget='CreateNote']")
    expect(composer).to_be_visible()
    return composer


# @matrix notes pages : load owner private shared viewer
# @matrix permissions : load owner private shared viewer
# @template pages/page.html::view_header
# @template pages/notes.html::notes_section
# @template pages/notes.html::note_list
# @template notes.html::note_item
def test_page_notes_visibility_and_title_menu(get_user):
    owner = get_user(Users.OWNER)
    page = Pages.acl_lab_visible.get(owner)
    shared_body = _unique("Shared Page note")
    private_body = _unique("Private Page note")
    _save_page_note(page, owner, private_body)

    viewer = get_user(Users.page_acl_one_visible)
    # A viewer's empty projection must never become a Page-wide empty hint.
    _go_with_page_notes(viewer, page)
    expect(_page_note(viewer, private_body)).not_to_be_attached()
    assert Entities.fetch_one(page.key, request=Fetch.root()).has_notes is True
    _go_with_page_notes(owner, page)
    expect(_page_note(owner, private_body)).to_be_visible()
    _save_page_note(page, owner, shared_body, visibility="everyone")
    _go_with_page_notes(viewer, page)
    expect(_page_note(viewer, shared_body)).to_be_visible()
    expect(_page_note(viewer, shared_body).locator(Buttons.LP_DELETE)).not_to_be_attached()
    expect(_page_note(viewer, private_body)).not_to_be_attached()
    viewer.page.get_by_role("button", name="Page actions").click()
    viewer_menu = viewer.page.get_by_role("menu", name="Page actions")
    expect(viewer_menu).to_be_visible()
    expect(viewer_menu.get_by_role("menuitem", name="Star", exact=True)).to_be_visible()
    expect(viewer_menu.get_by_role("menuitem", name="Add note")).not_to_be_attached()
    expect(viewer_menu.get_by_role("menuitem", name="Delete")).not_to_be_attached()

    _go_with_page_notes(owner, page)
    expect(_page_note(owner, shared_body)).to_be_visible()
    expect(_page_note(owner, private_body)).to_be_visible()

    composer = _open_note_composer(owner)
    header = owner.locate("[data-nav='view']")
    header_box = header.bounding_box()
    composer_box = composer.bounding_box()
    assert header_box and composer_box
    assert composer_box["y"] >= header_box["y"] + header_box["height"]

    page_without_notes = Pages.test_create_page_task.get(owner)
    _go_with_page_notes(owner, page_without_notes)
    expect(owner.locate("#page-notes")).to_be_hidden()


# @matrix notes pages : body create photo scope validation visibility
# @pair request-errors:plain-validation
# @template pages/page.html::view_header
# @template pages/notes.html::notes_section
# @template pages/notes.html::note_list
# @template notes.html::composer
# @template notes.html::note_item
# @style note.section
def test_page_note_text_photo_and_delete_modal(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    page = Pages.test_create_page.get(owner)
    _go_with_page_notes(owner, page)
    body = _unique("Page text and photo note")
    notes_section = owner.locate("#page-notes")
    # The loaded list distinguishes a known empty state from a placeholder.
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


# @source lagniappe/web/routes/pages/notes.py::get_notes
# @matrix notes : empty-presence revision-bound etag load
# @template pages/notes.html::notes_section
# @template pages/notes.html::note_list
# @template notes.html::composer
# @template notes.html::note_item
def test_empty_notes_skip_fetch_without_hiding_new_notes(get_user):
    owner = get_user(Users.OWNER)
    page = Entities.PAGE.create({"name": _unique("Notes presence")})
    Entities.save(page)
    url = f"{SETTINGS.test_config['BASE_URL']}/pages/{page.urlsafe_key}"
    notes_path = f"/pages/{page.urlsafe_key}/notes"
    stale = Entities.fetch_one(page.key, request=Fetch.root())
    original_revision = stale.modified
    client = app.test_client()
    for cookie in owner.page.context.cookies():
        client.set_cookie(cookie["name"], cookie["value"])
    path = f"/pages/{page.urlsafe_key}"

    # The first read learns from legacy/unknown state. Conditional HTML must
    # then change even though no content or modification timestamp changed.
    before = client.get(path)
    assert before.status_code == 200
    empty = client.get(notes_path)
    assert empty.status_code == 200
    current = Entities.fetch_one(page.key, request=Fetch.root())
    assert current.has_notes is False
    assert current.modified == original_revision
    after = client.get(path, headers={"If-None-Match": before.headers["etag"]})
    assert after.status_code == 200
    assert after.headers["etag"] != before.headers["etag"]
    unchanged = client.get(path, headers={"If-None-Match": after.headers["etag"]})
    assert unchanged.status_code == 304

    requests = []

    def collect(request):
        if request.method == "GET" and urlsplit(request.url).path == notes_path:
            requests.append(request)

    owner.page.on("request", collect)
    try:
        owner.page.goto(url)
        expect(owner.locate("#page-notes [data-widget='BaseList']")).to_have_attribute("loaded", "")
        expect(owner.locate("#page-notes")).to_be_hidden()
        composer = _open_note_composer(owner)
        assert requests == []
        first_body = _unique("First note on known empty Page")
        composer.locator("textarea[name='body']").fill(first_body)
        with owner.page.expect_response(
            lambda response: response.request.method == "POST"
            and urlsplit(response.url).path == notes_path
        ):
            composer.locator("button[type='submit']").click()
        first = _page_note(owner, first_body)
        expect(first).to_be_visible()

        # Simulate an empty reader that began before creation and commits last.
        # Only its two hint fields may overwrite the now newer Page record.
        stale.remember_empty_notes()
        current = Entities.fetch_one(page.key, request=Fetch.root())
        assert current.has_notes is True
        assert current.modified != original_revision
        owner.page.reload()
        expect(_page_note(owner, first_body)).to_be_visible()

        _page_note(owner, first_body).locator(Buttons.LP_DELETE).click()
        Modal(owner.page).delete()
        expect(_page_note(owner, first_body)).not_to_be_attached()
        owner.page.reload()
        expect(owner.locate("#page-notes [data-widget='BaseList']")).to_have_attribute("loaded", "")
        assert Entities.fetch_one(page.key, request=Fetch.root()).has_notes is False

        # Mount the known-empty list again, then add from another real tab.
        # Normal foreground refresh must still discover its first new note.
        owner.page.reload()
        expect(owner.locate("#page-notes [data-widget='BaseList']")).to_have_attribute("loaded", "")
        other = owner.page.context.new_page()
        try:
            other.goto(url)
            other.get_by_role("button", name="Page actions").click()
            other.get_by_role("menuitem", name="Add note", exact=True).click()
            other_composer = other.locator("#page-notes [data-widget='CreateNote']")
            cross_tab_body = _unique("Note from another tab")
            other_composer.locator("textarea[name='body']").fill(cross_tab_body)
            other_composer.locator("button[type='submit']").click()
            expect(other.locator("#page-notes li[data-kind='note']").filter(has_text=cross_tab_body)).to_be_visible()
            owner.page.bring_to_front()
            owner.page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(_page_note(owner, cross_tab_body)).to_be_visible(timeout=20000)
        finally:
            other.close()
    finally:
        owner.page.remove_listener("request", collect)
