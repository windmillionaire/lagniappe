"""
E2E coverage for collaborative document sync.

These tests exercise the live app with real browser contexts and the real test
Redis/cache stack. Service-worker push delivery is simulated only after a real
browser /sync request has produced the update payload.
"""

import json
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from testing.definitions import Projects, Users
from testing.utility import simulate_fcm_message

pytestmark = pytest.mark.e2e


def unique_text(label):
    return f"test-sync-{label}-{uuid4().hex[:8]}"


def sync_update_from(response):
    return json.loads(response.request.post_data or "{}")["updates"][0]


def document_save_response(text):
    def predicate(response):
        post_data = response.request.post_data or ""
        return (
            response.url.endswith("/sync")
            and '"save":true' in post_data
            and text in post_data
        )

    return predicate


# @features sync
# @dimensions document collaboration persistence
def test_two_users_see_document_edits_without_reload(get_user):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_sync_document_collaboration.get(owner)

    owner.go(project)
    owner_editor = project.editor

    collaborator.go(project)
    collaborator_editor = project.editor

    text = unique_text("live-document-text")
    owner_editor.clear_text()
    owner_editor.type_text(text)
    owner_editor.wait_for_render()

    with owner.page.expect_response(document_save_response(text)) as response_info:
        owner_editor.text_entry.blur()

    update = sync_update_from(response_info.value)
    simulate_fcm_message(
        collaborator,
        "sync-update",
        {
            "update": {
                "sync_id": update["sync_id"],
                "user_hash": owner.entity.hash,
                "fetch": True,
            }
        },
    )

    expect(collaborator_editor.text_entry).to_contain_text(text)

    owner.go(project)
    expect(project.editor.text_entry).to_contain_text(text)


# @features sync
# @dimensions document sync-state presence deregistration stale-sessions state-registration
def test_document_presence_appears_and_clears(get_user):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_sync_document_presence.get(owner)

    owner.go(project)
    # Presence is document-scoped; the owner must mount the document to join it.
    expect(project.editor.text_entry).to_be_visible()

    collaborator.go(project)
    collaborator_editor = project.editor

    users_button = collaborator_editor.toolbar.locator("button[title='Users']")
    expect(users_button).to_be_visible(timeout=15000)
    users_button.click()

    users_panel = collaborator.page.locator("[role='listbox'][data-visible='true']")
    expect(users_panel).to_contain_text(owner.entity.name)

    owner.page.evaluate(
        """async () => {
            await document.querySelector("[lp-view]")._lp_view.SyncManager.deregister();
        }"""
    )
    with collaborator.page.expect_response("**/register"):
        collaborator.reload(project)
    collaborator_editor = project.editor

    expect(collaborator_editor.toolbar.locator("button[title='Users']")).to_have_count(0)


# @features sync
# @dimensions document sync-state response-contract
def test_document_sync_response_contract_is_browser_visible(get_user):
    owner = get_user(Users.OWNER)
    project = Projects.test_sync_document_contract.get(owner)
    owner.go(project)
    editor = project.editor

    text = unique_text("document-contract")
    editor.clear_text()
    editor.type_text(text)
    editor.wait_for_render()

    with owner.page.expect_response(document_save_response(text)) as response_info:
        editor.text_entry.blur()

    assert response_info.value.ok
    payload = json.loads(response_info.value.request.post_data or "{}")
    assert payload["token"]
    assert len(payload["updates"]) == 1

    update = payload["updates"][0]
    assert update["key"] == project.key
    assert update["sync_id"] == project.entity.sync_ids["document"]["id"]
    assert update["save"] is True
    assert update["html"]
    assert update["ydoc"]
