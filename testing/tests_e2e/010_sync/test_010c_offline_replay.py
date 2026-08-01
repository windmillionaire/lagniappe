"""
E2E coverage for offline sync replay.

These tests use real browser offline mode, real sync widgets, and the app's
IndexedDB queue. They assert replay by observing network requests and document
persistence after reconnects.
"""

from time import monotonic
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, SitePages, Users

pytestmark = pytest.mark.e2e

SYNC_TEXT_FIELD = "sync-text"
OFFLINE_INDICATOR = "[data-role='offline']"
OFFLINE_STORE_ROWS = """
async ({ storeName }) => await new Promise((resolve) => {
        const request = indexedDB.open("offline-db", 5);
        request.onerror = () => resolve([]);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains("sync")) {
                db.createObjectStore("sync", { keyPath: "sync_id" });
            }
            if (!db.objectStoreNames.contains("mutations")) {
                db.createObjectStore("mutations", { keyPath: "id" });
            }
        };
        request.onsuccess = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains(storeName)) {
                db.close();
                resolve([]);
                return;
            }
            const tx = db.transaction(storeName, "readonly");
            const allRequest = tx.objectStore(storeName).getAll();
            allRequest.onsuccess = () => resolve(allRequest.result || []);
            allRequest.onerror = () => resolve([]);
            tx.oncomplete = () => db.close();
            tx.onerror = () => {
                db.close();
                resolve([]);
            };
        };
})
"""


def _unique(label):
    return f"test-sync-{label}-{uuid4().hex[:8]}"


def _document_save_response(*parts):
    def predicate(response):
        post_data = response.request.post_data or ""
        return (
            response.url.endswith("/sync")
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


def _offline_store_rows(user, store_name="sync"):
    return user.page.evaluate(OFFLINE_STORE_ROWS, arg={"storeName": store_name})


def _wait_for_offline_sync_records(user, *, minimum=None, exact=None):
    deadline = monotonic() + 15
    last_count = None
    while monotonic() < deadline:
        last_count = len(_offline_store_rows(user, "sync"))
        if exact is not None and last_count == exact:
            return
        if exact is None and minimum is not None and last_count >= minimum:
            return
        user.page.wait_for_timeout(100)
    expected = f"exactly {exact}" if exact is not None else f"at least {minimum}"
    raise AssertionError(f"Expected {expected} offline sync records; found {last_count}.")


def _wait_for_offline_document_record(user, *parts):
    deadline = monotonic() + 15
    last_rows = []
    while monotonic() < deadline:
        last_rows = _offline_store_rows(user, "sync")
        if any(
            row.get("save")
            and isinstance(row.get("html"), str)
            and all(part in row["html"] for part in parts)
            for row in last_rows
        ):
            return
        user.page.wait_for_timeout(100)
    raise AssertionError(
        f"Expected offline document row containing {parts!r}; found {last_rows!r}."
    )


def _offline_document_edit(user, browser_failures, editor, *parts):
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
        _wait_for_offline_document_record(user, *parts)


def _offline_form_edit(user, form, value):
    _go_offline(user)
    field = form.locator(f"[id^='{SYNC_TEXT_FIELD}'].form-element")
    expect(field).to_be_visible()
    field.locator("[data-role='label']").click()
    field.locator("input").fill(value)
    field.locator("input").press("Tab")
    _wait_for_offline_sync_records(user, minimum=1)


def _reconnect_with_sync(user):
    with user.page.expect_response("**/sync") as response_info:
        user.offline = False
        user.page.evaluate("window.dispatchEvent(new Event('online'))")
    assert response_info.value.ok
    return response_info.value


# @features sync
# @dimensions offline-replay replay-order queue-clear
def test_offline_document_edits_replay_in_order(get_user, browser_failures):
    user = get_user(Users.OWNER)
    project = Projects.test_offline_document_replay.get(user)
    user.go(project)
    editor = project.editor
    first = _unique("first-offline-edit")
    second = _unique("second-offline-edit")
    _offline_document_edit(user, browser_failures, editor, first, second)
    _reconnect_with_sync(user)
    _wait_for_offline_sync_records(user, exact=0)

    user.go(project)
    replayed = project.editor.get_text()
    assert first in replayed
    assert second in replayed
    assert replayed.index(first) < replayed.index(second)


# @features sync
# @dimensions offline-replay replay-error queue-preserved retry
def test_failed_offline_replay_keeps_queue_and_retries(get_user, browser_failures):
    user = get_user(Users.OWNER)
    project = Projects.test_offline_document_retry.get(user)
    user.go(project)
    editor = project.editor
    text = _unique("retry-after-failure")

    _offline_document_edit(user, browser_failures, editor, text)

    failed_sync_attempts = []

    def fail_sync(route):
        failed_sync_attempts.append(route.request)
        route.abort()

    with browser_failures.expect(
        user,
        kind="console",
        console_type="error",
        text="Failed to load resource: the server responded with a status of 503 ()",
        source_path="/sync",
    ):
        with browser_failures.expect(
            user,
            kind="console",
            console_type="error",
            text="Failed to load resource: the server responded with a status of 503 ()",
            source_path="/poll",
        ):
            user.page.context.route("**/sync", fail_sync)
            with user.page.expect_request("**/sync"):
                user.offline = False
            assert len(failed_sync_attempts) == 1
            user.page.context.unroute("**/sync", fail_sync)
            _wait_for_offline_sync_records(user, minimum=1)

            with browser_failures.expect_offline(user):
                _go_offline(user)
                _reconnect_with_sync(user)
                _wait_for_offline_sync_records(user, exact=0)

            user.go(project)
            expect(project.editor.text_entry).to_contain_text(text)


# @features sync
# @dimensions offline-replay dedupe reload document headless-widget
def test_offline_replay_does_not_duplicate_after_reload(get_user, browser_failures):
    user = get_user(Users.OWNER)
    project = Projects.test_offline_document_reload.get(user)
    user.go(project)
    editor = project.editor
    text = _unique("reload-dedupe")

    _offline_document_edit(user, browser_failures, editor, text)
    _replace_page(user)

    with user.page.expect_response("**/sync"):
        user.go(SitePages.HOME)
    _wait_for_offline_sync_records(user, exact=0)

    user.go(project)
    replayed = project.editor.get_text()
    assert replayed.count(text) == 1


# @pairs sync:offline-replay sync:headless sync:concurrency sync:merge
# @pairs sync:revision sync:checkpoint sync:queue-clear
# @pairs polling:document polling:current-state polling:cursor
def test_headless_offline_replay_merges_concurrent_remote_edits(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    collaborator = get_user(Users.admin, creator=owner)
    project = Projects.test_offline_document_concurrent_replay.get(owner)

    owner.go(project)
    owner_editor = project.editor
    collaborator.go(project)
    collaborator_editor = project.editor

    offline_text = _unique("offline-branch")
    _offline_document_edit(owner, browser_failures, owner_editor, offline_text)

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
    with owner.page.expect_response(
        _document_save_response(offline_text, remote_text)
    ) as replay_response:
        owner.go(SitePages.HOME)

    assert replay_response.value.ok
    acknowledgement = replay_response.value.json()["updates"][0]
    assert acknowledgement["checkpoint_accepted"] is True
    _wait_for_offline_sync_records(owner, exact=0)

    owner.go(project)
    replayed = project.editor.get_text()
    assert offline_text in replayed
    assert remote_text in replayed
    assert replayed.count(offline_text) == 1
    assert replayed.count(remote_text) == 1


# @features sync
# @dimensions headless-widget form-submission offline-replay
