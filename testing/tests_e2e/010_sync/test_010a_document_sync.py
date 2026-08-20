"""
E2E coverage for collaborative document sync.

These tests exercise the live app with real browser contexts and the real test
Redis/cache stack.
"""

import json
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, Users
from testing.elements import Tabs
from testing.utility import expect_poll_result, expect_successful_response

pytestmark = pytest.mark.e2e


def unique_text(label):
    return f"test-sync-{label}-{uuid4().hex[:8]}"


def document_save_response(text):
    def predicate(response):
        post_data = response.request.post_data or ""
        return (
            response.url.endswith("/l/sync")
            and '"save":true' in post_data
            and text in post_data
        )

    return predicate


def document_parent_touch_response(response):
    post_data = response.request.post_data or ""
    return (
        response.url.endswith("/l/sync")
        and '"touch_parent":true' in post_data
        and '"ydoc"' not in post_data
    )


# @pairs sync:document sync:collaboration sync:persistence
# @pairs sync:revision sync:delta sync:checkpoint
def test_two_users_see_document_edits_without_reload(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_sync_document_collaboration.get(owner)

    owner.go(project)
    owner_editor = project.editor

    collaborator.go(project)
    collaborator_editor = project.editor
    document_sync_id = project.entity.sync_ids["document"]["id"]

    text = unique_text("live-document-text")
    with browser_failures.expect_offline(collaborator):
        collaborator.offline = True
        expect(collaborator.locate("[data-role='offline']")).to_be_visible()
    owner_editor.clear_text()
    owner_editor.type_text(text)
    owner_editor.wait_for_render()

    with owner.page.expect_response(document_save_response(text)):
        owner_editor.text_entry.blur()

    with expect_poll_result(
        collaborator.page,
        subscription_id=f"document:{document_sync_id}",
    ):
        collaborator.offline = False

    expect(collaborator_editor.text_entry).to_contain_text(text)

    owner.go(project)
    expect(project.editor.text_entry).to_contain_text(text)


# @pairs sync:document sync:presence sync:lifecycle
# @pairs polling:document polling:presence polling:lifecycle
def test_document_presence_appears_and_clears(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_sync_document_presence.get(owner)

    owner.go(project)
    # Presence is document-scoped; the owner must mount the document to join it.
    expect(project.editor.text_entry).to_be_visible()
    document_sync_id = project.entity.sync_ids["document"]["id"]

    collaborator.go(project)
    collaborator_editor = project.editor

    users_button = collaborator_editor.toolbar.locator("button[title='Users']")
    expect(users_button).to_be_visible(timeout=15000)
    users_button.click()

    users_panel = collaborator.page.locator("[role='listbox'][data-visible='true']")
    expect(users_panel).to_contain_text(owner.entity.name)

    collaborator.page.wait_for_function(
        "() => !document.fonts || document.fonts.status === 'loaded'"
    )
    with browser_failures.expect_offline(collaborator):
        collaborator.offline = True
        expect(collaborator.locate("[data-role='offline']")).to_be_visible()
    with expect_successful_response(
        owner.page,
        method="POST",
        path="/l/poll",
        request_payload_contains=(
            f'"closed_documents":["{document_sync_id}"]'
        ),
    ):
        Tabs(owner).info

    with expect_poll_result(
        collaborator.page,
        subscription_id=f"document:{document_sync_id}",
    ):
        collaborator.offline = False

    expect(collaborator_editor.toolbar.locator("button[title='Users']")).to_have_count(0)


# @pairs sync:document sync:document-only sync:validation sync:revision
# @pairs sync:response-contract sync:client-identity sync:checkpoint
# @pair sync:persistence
def test_document_sync_response_contract_is_browser_visible(get_user):
    owner = get_user(Users.OWNER)
    project = Projects.test_sync_document_contract.get(owner)
    owner.go(project)
    editor = project.editor
    before = Entities.fetch_one(project.key, request=Fetch.direct())
    modified_before = before.modified
    document_before = before.properties.document.fingerprint

    text = unique_text("document-contract")
    editor.clear_text()
    editor.type_text(text)
    editor.wait_for_render()

    with owner.page.expect_response(document_save_response(text)) as response_info:
        editor.text_entry.blur()

    assert response_info.value.ok
    payload = json.loads(response_info.value.request.post_data or "{}")
    assert payload["client_id"]
    assert len(payload["updates"]) == 1

    update = payload["updates"][0]
    assert update["key"] == project.key
    assert update["sync_id"] == project.entity.sync_ids["document"]["id"]
    assert update["save"] is True
    assert "generation" in update
    assert isinstance(update["revision"], int)
    assert update["html"]
    assert update["ydoc"]

    response = response_info.value.json()
    assert response["updates"][0]["sync_id"] == update["sync_id"]
    assert response["updates"][0]["checkpoint_accepted"] is True
    assert response["updates"][0]["checkpoint_persisted"] is True
    assert response["updates"][0]["entity_touched"] is False

    checkpoint = Entities.fetch_one(project.key, request=Fetch.direct())
    assert checkpoint.modified == modified_before
    assert checkpoint.properties.document.fingerprint != document_before

    with owner.page.expect_response(document_parent_touch_response) as touch_info:
        Tabs(owner).info

    touch = touch_info.value.json()["updates"][0]
    assert touch["checkpoint_accepted"] is False
    assert touch["checkpoint_persisted"] is False
    assert touch["entity_touched"] is True
    advanced = Entities.fetch_one(project.key, request=Fetch.direct())
    assert advanced.modified > modified_before
