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

from testing.definitions import Projects, Users
from testing.utility import assert_lagniappe_error_response


pytestmark = pytest.mark.e2e


# @pair editor:history-list
def test_document_history_created_on_save(get_user):
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


# @pair editor:history-restore
def test_document_history_restore(get_user):
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


# @matrix editor : confirmation current-content history-clear history-pin parent-scope validation
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
    def is_pin_response(response):
        return (
            response.request.method == "POST"
            and urlsplit(response.url).path == pin_url
        )

    def assert_invalid_pin(message):
        expect(pin_form.locator("[data-role='error']")).to_have_text(message)

    pin_form.locator("input[name='name']").fill("<b> </b>")
    with browser_failures.expect_http_error(
        user,
        status=422,
        path=pin_url,
    ):
        with user.page.expect_response(is_pin_response):
            pin_form.locator("button[type='submit']").click()
        assert_invalid_pin("Version name is required")

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
        with user.page.expect_response(is_pin_response):
            pin_form.locator("button[type='submit']").click()
        assert_invalid_pin("Document content is required")

    editor.type_text("Pinned but not saved checkpoint")
    history = editor.history
    history.get_by_role("option", name="Pin Version").click()
    expect(pin_form).to_be_visible()
    pin_form.locator("input[name='name']").fill("Release checkpoint")
    with user.page.expect_response(is_pin_response) as pin_response:
        pin_form.locator("button[type='submit']").click()

    pinned_payload = pin_response.value.json()["entry"]
    expect(pin_form).to_be_hidden()

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

    # Keep the parent-scope route boundary here: lower-level entity tests own
    # ordering and cleanup, but cannot exercise the deployed permission route.
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

    history = editor.history
    history.get_by_role("option", name="Clear Unpinned Versions").click()
    modal = user.page.locator("#modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("clear 2 unpinned versions")
    delete_button = modal.locator("[data-role='delete']")
    with user.page.expect_response("**/document/history/unpinned"):
        delete_button.click()

    expect(modal).to_be_hidden()

    refreshed = editor.history
    expect(
        refreshed.get_by_role("option", name="Clear Unpinned Versions")
    ).to_have_count(0)
    expect(
        refreshed.get_by_role(
            "option", name=re.compile(r"Release checkpoint — .+")
        )
    ).to_be_visible()
