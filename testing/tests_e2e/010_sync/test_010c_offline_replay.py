"""
E2E coverage for offline sync replay.

These tests use real browser offline mode, real sync widgets, and the app's
IndexedDB queue. They assert replay by observing network requests and document
persistence after reconnects.
"""

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, SitePages, Users
from testing.utility import (
    expect_offline_sync_replay,
    expect_successful_response,
    wait_for_connectivity_replay,
    wait_for_offline_sync_records,
)

pytestmark = pytest.mark.e2e

SYNC_TEXT_FIELD = "sync-text"
OFFLINE_INDICATOR = "[data-role='offline']"
def _unique(label):
    return f"test-sync-{label}-{uuid4().hex[:8]}"


def _document_save_response(*parts):
    def predicate(response):
        post_data = response.request.post_data or ""
        return (
            response.url.endswith("/l/sync")
            and '"save":true' in post_data
            and all(part in post_data for part in parts)
        )

    return predicate


def _fresh_submission(page):
    return Entities.fetch_one(
        page.key, request=Fetch.direct()
    ).properties.submission.value


def _replace_page(user):
    context = user.page.context
    user.page.close()
    user.page = context.new_page()
    user.page.set_default_timeout(15000)


def _go_offline(user):
    user.offline = True
    expect(user.locate(OFFLINE_INDICATOR)).to_be_visible()


def _offline_document_edit(user, browser_failures, editor, *parts, sync_id):
    with browser_failures.expect_http_error(
        user,
        status=503,
        path="/l/poll",
        count=0,
        max_count=1,
    ):
        with browser_failures.expect_offline(user):
            _go_offline(user)
            editor.focus()
            for index, part in enumerate(parts):
                if index:
                    editor.enter()
                editor.type_text(part)
            editor.wait_for_render()
            for part in parts:
                expect(editor.text_entry).to_contain_text(part)
            editor.text_entry.blur()
            wait_for_offline_sync_records(
                user,
                sync_id=sync_id,
                saved_html_contains=parts,
            )


def _offline_form_edit(user, form, value):
    _go_offline(user)
    field = form.locator(f"[id^='{SYNC_TEXT_FIELD}'].form-element")
    expect(field).to_be_visible()
    field.locator("[data-role='label']").click()
    field.locator("input").fill(value)
    field.locator("input").press("Tab")
    wait_for_offline_sync_records(user, minimum=1)


def _reconnect_with_sync(user, sync_id):
    sync_requests = []

    def record_sync(request):
        request_body = request.post_data or ""
        if (
            request.method == "POST"
            and request.url.endswith("/l/sync")
            and sync_id in request_body
        ):
            sync_requests.append(request)

    user.page.on("request", record_sync)
    try:
        with expect_successful_response(
            user.page,
            method="POST",
            path="/l/sync",
            request_payload_contains=sync_id,
        ) as response_info:
            user.offline = False
        wait_for_offline_sync_records(user, sync_id=sync_id, exact=0)
    finally:
        user.page.remove_listener("request", record_sync)

    assert len(sync_requests) == 1
    return response_info.value


# @features sync
# @dimensions offline-replay replay-order queue-clear
def test_offline_document_edits_replay_in_order(get_user, browser_failures):
    user = get_user(Users.OWNER)
    project = Projects.test_offline_document_replay.get(user)
    user.go(project)
    editor = project.editor
    document_sync_id = project.entity.sync_ids["document"]["id"]
    first = _unique("first-offline-edit")
    second = _unique("second-offline-edit")
    _offline_document_edit(
        user,
        browser_failures,
        editor,
        first,
        second,
        sync_id=document_sync_id,
    )
    _reconnect_with_sync(user, document_sync_id)

    user.go(project)
    replayed = project.editor.get_text()
    assert first in replayed
    assert second in replayed
    assert replayed.index(first) < replayed.index(second)


# @pairs sync:offline-replay sync:queue-preserved
def test_failed_offline_replay_keeps_queue_and_retries(get_user, browser_failures):
    user = get_user(Users.OWNER)
    project = Projects.test_offline_document_retry.get(user)
    user.go(project)
    editor = project.editor
    document_sync_id = project.entity.sync_ids["document"]["id"]
    text = _unique("retry-after-failure")

    _offline_document_edit(
        user,
        browser_failures,
        editor,
        text,
        sync_id=document_sync_id,
    )

    failed_sync_attempts = []

    def fail_sync(route):
        if document_sync_id not in (route.request.post_data or ""):
            route.continue_()
            return
        failed_sync_attempts.append(route.request)
        route.abort()

    user.page.context.route("**/l/sync", fail_sync)
    try:
        with browser_failures.expect_http_error(
            user,
            status=503,
            path="/l/sync",
            max_count=2,
        ):
            with browser_failures.expect_http_error(
                user,
                status=503,
                path="/l/poll",
                count=0,
                max_count=1,
            ):
                with user.page.expect_request(
                    lambda request: request.method == "POST"
                    and request.url.endswith("/l/sync")
                    and document_sync_id in (request.post_data or "")
                ):
                    user.offline = False
                wait_for_connectivity_replay(user)
    finally:
        user.page.context.unroute("**/l/sync", fail_sync)

    assert len(failed_sync_attempts) == 1
    wait_for_offline_sync_records(
        user,
        sync_id=document_sync_id,
        minimum=1,
    )

    with browser_failures.expect_offline(user):
        _go_offline(user)
        _reconnect_with_sync(user, document_sync_id)

    user.go(project)
    expect(project.editor.text_entry).to_contain_text(text)


# @pairs sync:offline-replay sync:headless sync:concurrency sync:merge
# @pairs sync:queue-clear sync:document sync:headless-widget
# @pairs polling:document polling:current-state polling:cursor
def test_headless_offline_replay_merges_concurrent_remote_edits(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_offline_document_concurrent_replay.get(owner)
    document_sync_id = project.entity.sync_ids["document"]["id"]

    owner.go(project)
    owner_editor = project.editor
    collaborator.go(project)
    collaborator_editor = project.editor

    offline_text = _unique("offline-branch")
    _offline_document_edit(
        owner,
        browser_failures,
        owner_editor,
        offline_text,
        sync_id=document_sync_id,
    )

    remote_text = _unique("remote-branch")
    collaborator_editor.focus()
    collaborator_editor.type_text(remote_text)
    collaborator_editor.wait_for_render()
    with collaborator.page.expect_response(
        _document_save_response(remote_text)
    ) as remote_response:
        collaborator_editor.text_entry.blur()
    assert remote_response.value.ok

    _replace_page(owner)
    with expect_offline_sync_replay(
        owner,
        sync_id=document_sync_id,
        request_payload_contains=(offline_text, remote_text),
    ) as replay_responses:
        owner.go(SitePages.HOME)

    acknowledgement = replay_responses[0].json()["updates"][0]
    assert acknowledgement["checkpoint_accepted"] is True
    wait_for_offline_sync_records(
        owner,
        sync_id=document_sync_id,
        exact=0,
    )

    owner.go(project)
    replayed = project.editor.get_text()
    assert offline_text in replayed
    assert remote_text in replayed
    assert replayed.count(offline_text) == 1
    assert replayed.count(remote_text) == 1
