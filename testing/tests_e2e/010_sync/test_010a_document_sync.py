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
from testing.utility import trigger_poll

pytestmark = pytest.mark.e2e


def unique_text(label):
    return f"test-sync-{label}-{uuid4().hex[:8]}"


def document_save_response(text):
    def predicate(response):
        post_data = response.request.post_data or ""
        return (
            response.url.endswith("/sync")
            and '"save":true' in post_data
            and text in post_data
        )

    return predicate


def document_parent_touch_response(response):
    post_data = response.request.post_data or ""
    return (
        response.url.endswith("/sync")
        and '"touch_parent":true' in post_data
        and '"ydoc"' not in post_data
    )


# @pairs sync:document sync:collaboration sync:persistence
# @pairs sync:revision sync:delta sync:checkpoint
# @pairs sync:author-color editor:remote-highlight
def test_two_users_see_document_edits_without_reload(get_user):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_sync_document_collaboration.get(owner)

    owner.go(project)
    owner_editor = project.editor

    collaborator.go(project)
    collaborator_editor = project.editor

    users_button = collaborator_editor.toolbar.locator("button[title='Users']")
    expect(users_button).to_be_visible(timeout=15000)
    users_button.click()
    users_panel = collaborator.page.locator("[role='listbox'][data-visible='true']")
    owner_option = users_panel.get_by_role("option").filter(
        has_text=owner.entity.name
    )
    expect(owner_option).to_be_visible()
    owner_color = owner_option.locator("span").first.evaluate(
        "(dot) => dot.style.backgroundColor"
    )
    users_button.click()
    expect(users_panel).to_be_hidden()

    text = unique_text("live-document-text")
    collaborator_editor.text_entry.evaluate(
        """(editor) => {
            const seen = new WeakSet();
            window.__remoteRevisionFlashes = [];
            window.__remoteRevisionObserver?.disconnect();
            const record = () => {
                editor.querySelectorAll(".remote-change-flash").forEach((node) => {
                    if (seen.has(node)) return;
                    seen.add(node);
                    window.__remoteRevisionFlashes.push({
                        text: node.textContent,
                        color: node.style.color,
                        author: node.dataset.editorAuthor,
                        title: node.title,
                        label: getComputedStyle(node, "::after").content.replace(
                            /^["']|["']$/g,
                            "",
                        ),
                    });
                });
            };
            window.__remoteRevisionObserver = new MutationObserver(record);
            window.__remoteRevisionObserver.observe(editor, {
                childList: true,
                subtree: true,
            });
        }"""
    )
    owner_editor.clear_text()
    owner_editor.type_text(text)
    owner_editor.wait_for_render()

    with owner.page.expect_response(document_save_response(text)) as save_info:
        owner_editor.text_entry.blur()

    save_result = save_info.value.json()
    assert save_result["updates"][0]["checkpoint_accepted"] is True

    owner.page.evaluate(
        """async () => {
            const view = document.querySelector("[lp-view]")._lp_view;
            await view.SyncManager.deregister();
        }"""
    )
    trigger_poll(collaborator)

    expect(collaborator_editor.text_entry).to_contain_text(text)
    expect(collaborator_editor.toolbar.locator("button[title='Users']")).to_have_count(
        0
    )
    observed = collaborator.page.evaluate(
        "() => window.__remoteRevisionFlashes"
    )
    remote_revision = next(
        (
            revision
            for revision in observed
            if text in revision["text"]
        ),
        None,
    )
    assert remote_revision, observed
    assert remote_revision["color"] == owner_color
    assert remote_revision["author"] == owner.entity.name
    assert remote_revision["title"] == f"Edited by {owner.entity.name}"
    assert remote_revision["label"] == owner.entity.name

    owner.go(project)
    expect(project.editor.text_entry).to_contain_text(text)


# @pairs sync:document sync:presence sync:lifecycle
# @pairs polling:document polling:presence polling:lifecycle
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

    deregistered = owner.page.evaluate(
        """async () => {
            const view = document.querySelector("[lp-view]")._lp_view;
            return await Promise.race([
                view.SyncManager.deregister().then(() => ({ done: true })),
                new Promise((resolve) => setTimeout(() => resolve({
                    done: false,
                    active_poll: Boolean(view.PollingCoordinator.activePoll),
                    inflight: Boolean(view.PollingCoordinator.inflight),
                    send_pending: Boolean(view.SyncManager._sendPromise),
                    subscriptions: [...view.SyncManager._subscriptions.keys()],
                }), 10000)),
            ]);
        }"""
    )
    assert deregistered["done"], deregistered
    trigger_poll(collaborator)

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
