from uuid import uuid4

import pytest
from playwright.sync_api import expect

from testing.definitions import Projects, Users
from testing.elements import Tabs
from testing.utility.network import expect_successful_response
from testing.utility.polling import expect_poll_result

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


# @matrix sync : checkpoint collaboration delta document persistence revision
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


# @matrix sync : document lifecycle presence
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
