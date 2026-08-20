"""
Tests for offline/online behavior and state transitions.

Exercises the app-layer offline logic through browser network events and
server health checks. This tests the offline indicator, sync queue behavior,
and transition resilience.

Related Files:
    Application:
        - src/script/views/base/core.mjs: Core.offline() state transitions
        - src/script/shared/sync.mjs: SyncManager.sendUpdates offline path
        - src/script/main.mjs: pingServer, syncView

    Test Framework:
        - testing/resources/project.py: Project resource with editor property
"""

import pytest

from testing.definitions import Projects, SitePages, Users
from testing.utility import (
    expect_successful_response,
    scoped_browser_route,
    wait_for_offline_sync_records,
)
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

OFFLINE_INDICATOR = "[data-role='offline']"
# @features offline
# @dimensions indicator browser-state
def test_offline_indicator_toggles(get_user, browser_failures):
    """
    Test that the offline indicator responds to offline state changes.

    Flow:
        1. Navigate to home, verify indicator is hidden
        2. Set offline, verify indicator is visible
        3. Set online, verify indicator is hidden again

    Verifies:
        - Indicator defaults to hidden (data-visible="false")
        - Indicator becomes visible when offline
        - Indicator hides when back online
    """
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    indicator = user.locate(OFFLINE_INDICATOR)
    expect(indicator).to_be_hidden()

    with browser_failures.expect_offline(user):
        user.offline = True
        expect(indicator).to_be_visible()

    user.offline = False
    expect(indicator).to_be_hidden()


# @features offline
# @dimensions indicator server-health
def test_failed_ping_marks_view_offline_until_next_sync_event(
    get_user,
    browser_failures,
):
    """
    Test that server health, not just client connectivity, drives offline UI.

    Flow:
        1. Navigate home while online
        2. Fail /l/ping while leaving the browser online
        3. Reload and verify the failed health check makes the indicator visible
        4. Restore /l/ping and reload again
        5. Verify the indicator hides again

    Verifies:
        - Failed server health checks mark the view offline
        - A later browser lifecycle sync restores online state
    """
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    indicator = user.locate(OFFLINE_INDICATOR)
    failed_pings = []

    def fail_ping(route):
        assert route.request.method == "HEAD"
        failed_pings.append(route.request)
        route.abort("connectionfailed")

    # Reload startup can coalesce focus, pageshow, and controller events behind
    # the first failed health check. Keep the expectation open through the
    # recovery reload so Chromium has delivered every failure event.
    with browser_failures.expect(
        user,
        kind="requestfailed",
        count=1,
        max_count=3,
        method="HEAD",
        path="/l/ping",
        failure="net::ERR_CONNECTION_FAILED",
    ):
        with browser_failures.expect(
            user,
            kind="console",
            count=1,
            max_count=3,
            console_type="error",
            text="Failed to load resource: net::ERR_CONNECTION_FAILED",
            source_path="/l/ping",
        ):
            with scoped_browser_route(user.page.context, "**/l/ping", fail_ping):
                user.reload()
                expect(indicator).to_be_visible()

            assert 1 <= len(failed_pings) <= 3

            with expect_successful_response(
                user.page,
                method="HEAD",
                path="/l/ping",
            ):
                user.reload()
    expect(indicator).to_be_hidden()


# @features offline
# @dimensions indicator browser-state server-health reconnect
def test_offline_poll_recovers_without_online_event(get_user, browser_failures):
    """
    Test that retry polling recovers after the native online event fails.

    Flow:
        1. Navigate home in the normal testing mode
        2. Set the browser context offline
        3. Verify the offline indicator becomes visible
        4. Restore the browser context and fail that native reconnect ping
        5. Verify the retry loop succeeds without a second online event

    Verifies:
        - Offline state schedules a server health retry
        - A later successful ping restores online UI without another event
    """
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    indicator = user.locate(OFFLINE_INDICATOR)
    with browser_failures.expect_offline(user):
        user.offline = True
        expect(indicator).to_be_visible()

    failed_pings = []

    def fail_ping(route):
        assert route.request.method == "HEAD"
        failed_pings.append(route.request)
        route.abort("connectionfailed")

    with expect_successful_response(
        user.page,
        method="HEAD",
        path="/l/ping",
        timeout=8000,
    ):
        with scoped_browser_route(user.page.context, "**/l/ping", fail_ping):
            with browser_failures.expect(
                user,
                kind="requestfailed",
                method="HEAD",
                path="/l/ping",
                failure="net::ERR_CONNECTION_FAILED",
            ):
                with browser_failures.expect(
                    user,
                    kind="console",
                    console_type="error",
                    text="Failed to load resource: net::ERR_CONNECTION_FAILED",
                    source_path="/l/ping",
                ):
                    with user.page.expect_event(
                        "requestfailed",
                        predicate=lambda request: request.method == "HEAD"
                        and request.url.endswith("/l/ping"),
                    ):
                        user.offline = False
                    expect(indicator).to_be_visible()
                    assert user.page.evaluate("navigator.onLine") is True

    assert len(failed_pings) == 1
    expect(indicator).to_be_hidden()


# @pairs sync:offline-replay sync:queue-clear
def test_offline_prevents_sync_requests(get_user, browser_failures):
    """
    Test that going offline prevents sync network requests and that
    coming back online flushes the queue.

    Flow:
        1. Navigate to project with editor
        2. Set offline
        3. Type text and blur (should store to IndexedDB, not POST)
        4. Set online and expect the sync request to fire

    Verifies:
        - No sync POST while offline
        - Sync fires on re-online transition
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_toolbar_loads)
    editor = project.editor
    document_sync_id = project.entity.sync_ids["document"]["id"]

    with browser_failures.expect_offline(user):
        user.offline = True
        editor.type_text("offline edit")
        editor.text_entry.blur()
        wait_for_offline_sync_records(
            user,
            sync_id=document_sync_id,
            minimum=1,
        )

    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/sync",
        request_payload_contains=document_sync_id,
    ):
        user.offline = False
    wait_for_offline_sync_records(
        user,
        sync_id=document_sync_id,
        exact=0,
    )


# @features offline
# @dimensions indicator view-reset
def test_testing_mode_navigation_resets_offline_state(get_user, browser_failures):
    """
    Test that a new testing-mode view rechecks server state after navigation.

    Flow:
        1. Navigate to home, set offline
        2. Verify indicator is visible
        3. Navigate to a project (which re-initializes the view)
        4. Verify indicator reflects online state after re-init

    Verifies:
        - View re-initialization from navigation resets online state
          (since __TESTING__ forces server status to true on init)
    """
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    with browser_failures.expect_offline(user):
        user.offline = True
        indicator = user.locate(OFFLINE_INDICATOR)
        expect(indicator).to_be_visible()

    user.go(Projects.test_toolbar_loads)
    indicator = user.locate(OFFLINE_INDICATOR)
    expect(indicator).to_be_hidden()
