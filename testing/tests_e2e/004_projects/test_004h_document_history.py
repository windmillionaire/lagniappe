"""
Tests for document history and restore functionality.

Verifies that editing a document creates history entries and that
restoring from history replaces the current content with the
historical snapshot.

Related Files:
    Application:
        - src/script/elements/editor/options/documentHistory.mjs: History button
        - lagniappe/core/properties/common_assets.py: Document.save history creation
        - lagniappe/web/routes/assets/editor.py: History list/restore endpoints

    Test Framework:
        - testing/elements/editor.py: Editor class
        - testing/resources/project.py: Project resource with editor property
"""

import re
from urllib.parse import urlsplit

import pytest
import requests
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.core.tools.database.core import DATA
from testing.definitions import Projects, Users
from testing.utility import assert_lagniappe_error_response


pytestmark = pytest.mark.e2e


def _history_entries(entity):
    rows = database.get.document_history(entity)
    return Entities.fetch(*rows, request=Fetch.root()) if rows else []


def _blob_exists(definition):
    visibility = definition.get("visibility", "private")
    return DATA.bucket(visibility).blob(definition["path"]).exists()


# @features editor
# @dimensions history-list
def test_document_history_created_on_save(get_user):
    """
    Test that saving changed content creates a history entry.

    Flow:
        1. Navigate to project, write initial content, save
        2. Reload, overwrite with new content, save
        3. Click the History toolbar button
        4. Verify the dropdown appears with at least one entry

    Verifies:
        - History entries are created when ydoc content changes
        - History dropdown populates with entries
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_document_history_created)
    editor = project.editor

    history_button = editor.toolbar.locator("button[title='History']")
    expect(history_button).to_be_visible()
    initial_history = editor.history
    expect(initial_history.get_by_role("option", name="Pin Version")).to_be_visible()
    expect(
        initial_history.get_by_role("option", name="Clear Unpinned Versions")
    ).to_have_count(0)
    history_button.click()
    expect(initial_history).to_be_hidden()

    editor.clear_text()
    editor.type_text("First version of the document")
    editor.blur()

    user.go(project)
    editor = project.editor
    editor.clear_text()
    editor.type_text("Second version of the document")
    editor.blur()

    user.go(project)
    editor = project.editor

    history_button = editor.toolbar.locator("button[title='History']")
    expect(history_button).to_be_visible()
    history_button.click()

    panel = user.page.locator("[role='listbox'][data-visible='true']")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("option", name="Clear Unpinned Versions")).to_be_visible()
    expect(panel.locator("[role='option']").nth(3)).to_be_visible()


# @features editor
# @dimensions history-restore
def test_document_history_restore(get_user):
    """
    Test that selecting a history entry restores the editor content.

    Flow:
        1. Navigate to project, write initial content, save
        2. Reload, overwrite with new content, save
        3. Reload, open history dropdown
        4. Click the first (most recent) history entry
        5. Verify the editor content reverts to the previous version

    Verifies:
        - Clicking a history entry applies the historical ydoc state
        - Editor content reflects the restored version
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_document_history_restore)
    editor = project.editor

    editor.clear_text()
    editor.type_text("Original content to preserve")
    editor.blur()

    user.go(project)
    editor = project.editor
    editor.clear_text()
    editor.type_text("Replacement content")
    editor.blur()

    user.go(project)
    editor = project.editor
    assert "Replacement content" in editor.get_text()

    history = editor.history
    expect(history).to_be_visible()
    earliest_history = history.locator("[role='option']").last
    expect(earliest_history).to_be_visible()

    with user.page.expect_response("**/history/*"):
        earliest_history.click()

    expect(editor.text_entry).to_contain_text("Original content to preserve")


# @features editor
# @dimensions history-pin history-clear current-content validation ordering cleanup parent-scope confirmation batch
# @pair request-errors:plain-validation
# @template delete/document_history.html::confirmation
def test_pin_and_clear_document_history(get_user, browser_failures):
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_document_history_pinned)
    other_project = Projects.test_formatting_persists.get(user)
    editor = project.editor

    editor.clear_text()
    editor.type_text("First automatic version")
    editor.blur()

    user.go(project)
    editor = project.editor
    editor.clear_text()
    editor.type_text("Saved live document")
    editor.blur()

    user.go(project)
    editor = project.editor
    editor.clear_text()
    editor.type_text("Pinned but not saved checkpoint")

    history = editor.history
    history.get_by_role("option", name="Pin Version").click()
    pin_form = editor.toolbar.locator("[data-option='pinVersion']")
    expect(pin_form).to_be_visible()
    pin_url = f"/assets/{project.key}/document/history/pin"
    history_before_invalid = tuple(
        sorted(entry.urlsafe_key for entry in _history_entries(project.entity))
    )
    assets_before_invalid = [
        entry.assets["document"]
        for entry in _history_entries(project.entity)
        if "document" in entry.assets
    ]

    def is_pin_response(response):
        return (
            response.request.method == "POST"
            and urlsplit(response.url).path == pin_url
        )

    def assert_invalid_pin(response, message):
        assert response.status == 422
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text() == message
        expect(pin_form.locator("[data-role='error']")).to_have_text(message)
        assert tuple(
            sorted(entry.urlsafe_key for entry in _history_entries(project.entity))
        ) == history_before_invalid
        assert all(_blob_exists(definition) for definition in assets_before_invalid)

    pin_form.locator("input[name='name']").fill("<b> </b>")
    with browser_failures.expect_http_error(
        user,
        status=422,
        path=pin_url,
    ):
        with user.page.expect_response(is_pin_response) as invalid_name_info:
            pin_form.locator("button[type='submit']").click()
        assert_invalid_pin(invalid_name_info.value, "Version name is required")

    editor.clear_text()
    history = editor.history
    history.get_by_role("option", name="Pin Version").click()
    expect(pin_form).to_be_visible()
    pin_form.locator("input[name='name']").fill("Empty document")
    with browser_failures.expect_http_error(
        user,
        status=422,
        path=pin_url,
    ):
        with user.page.expect_response(is_pin_response) as invalid_content_info:
            pin_form.locator("button[type='submit']").click()
        assert_invalid_pin(
            invalid_content_info.value,
            "Document content is required",
        )

    editor.type_text("Pinned but not saved checkpoint")
    history = editor.history
    history.get_by_role("option", name="Pin Version").click()
    expect(pin_form).to_be_visible()
    pin_form.locator("input[name='name']").fill("Release checkpoint")
    with user.page.expect_response(is_pin_response) as pin_response:
        pin_form.locator("button[type='submit']").click()

    assert pin_response.value.ok
    pinned_payload = pin_response.value.json()["entry"]
    assert pinned_payload["name"] == "Release checkpoint"
    assert pinned_payload["pinned"] is True
    expect(pin_form).to_be_hidden()

    reloaded = Entities.fetch_one(project.entity.key, request=Fetch.direct())
    live_html = reloaded.get_asset("document").get()
    assert "Saved live document" in live_html
    assert "Pinned but not saved checkpoint" not in live_html

    editor.clear_text()
    editor.type_text("Edits made after the checkpoint")
    history = editor.history
    pinned_option = history.get_by_role(
        "option", name=re.compile(r"Release checkpoint — .+")
    )
    expect(pinned_option).to_be_visible()
    with user.page.expect_response("**/document/history/*"):
        pinned_option.click()
    expect(editor.text_entry).to_have_text("Pinned but not saved checkpoint")

    entries = Entities.DOCUMENT_HISTORY.ordered(_history_entries(project.entity))
    assert entries[0].name == "Release checkpoint"
    assert entries[0].pinned is True
    assert all(not entry.pinned for entry in entries[1:])
    unpinned = entries[1:]
    assert len(unpinned) == 2
    unpinned_assets = [entry.assets["document"] for entry in unpinned]
    assert all(_blob_exists(definition) for definition in unpinned_assets)

    history_before_cross_document = tuple(
        entry.urlsafe_key for entry in _history_entries(project.entity)
    )
    cross_document = requests.get(
        f"{user.page.url.split('/projects/', 1)[0]}/assets/{other_project.key}"
        f"/document/history/{pinned_payload['key']}",
        cookies={
            cookie["name"]: cookie["value"]
            for cookie in user.page.context.cookies()
        },
        headers={"X-Lagniappe-Request": "true"},
        allow_redirects=False,
        timeout=10,
    )
    assert_lagniappe_error_response(cross_document, status=404)
    assert pinned_payload["key"] not in cross_document.text
    assert "Pinned but not saved checkpoint" not in cross_document.text
    assert tuple(
        entry.urlsafe_key for entry in _history_entries(project.entity)
    ) == history_before_cross_document
    assert _blob_exists(entries[0].assets["document"])

    history = editor.history
    history.get_by_role("option", name="Clear Unpinned Versions").click()
    modal = user.page.locator("#modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("clear 2 unpinned versions")
    delete_button = modal.locator("[data-role='delete']")
    with user.page.expect_response("**/document/history/unpinned") as clear_response:
        delete_button.click()

    assert clear_response.value.ok
    assert clear_response.value.json()["cleared"] == 2
    expect(modal).to_be_hidden()

    remaining = _history_entries(project.entity)
    assert len(remaining) == 1
    assert remaining[0].urlsafe_key == pinned_payload["key"]
    assert remaining[0].pinned is True
    assert all(not _blob_exists(definition) for definition in unpinned_assets)
    assert _blob_exists(remaining[0].assets["document"])

    refreshed = editor.history
    expect(
        refreshed.get_by_role("option", name="Clear Unpinned Versions")
    ).to_have_count(0)
    expect(
        refreshed.get_by_role(
            "option", name=re.compile(r"Release checkpoint — .+")
        )
    ).to_be_visible()
