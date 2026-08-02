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
from testing.utility import expect_successful_response, scoped_browser_route
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

OFFLINE_INDICATOR = "[data-role='offline']"
OFFLINE_SYNC_RECORD_WAIT = """
async ({ minimum, exact }) => {
    const count = await new Promise((resolve) => {
        const request = indexedDB.open("offline-db", 5);
        request.onerror = () => resolve(0);
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
            if (!db.objectStoreNames.contains("sync")) {
                db.close();
                resolve(0);
                return;
            }
            const tx = db.transaction("sync", "readonly");
            const countRequest = tx.objectStore("sync").count();
            countRequest.onsuccess = () => resolve(countRequest.result);
            countRequest.onerror = () => resolve(0);
            tx.oncomplete = () => db.close();
            tx.onerror = () => {
                db.close();
                resolve(0);
            };
        };
    });
    return exact === null ? count >= minimum : count === exact;
}
"""


def trigger_focus_sync(user):
    user.page.evaluate("window.dispatchEvent(new Event('focus'));")


def suppress_online_event_sync(user):
    user.page.add_init_script(
        """
        (() => {
            if (window.__LP_ONLINE_LISTENER_WRAPPED__) return;
            window.__LP_ONLINE_LISTENER_WRAPPED__ = true;
            window.__LP_SUPPRESS_ONLINE_EVENT__ = true;

            const addEventListener = window.addEventListener.bind(window);
            window.addEventListener = (type, listener, options) => {
                if (type !== "online") {
                    return addEventListener(type, listener, options);
                }

                return addEventListener(
                    type,
                    function wrappedOnlineListener(event) {
                        if (window.__LP_SUPPRESS_ONLINE_EVENT__) return;
                        if (typeof listener === "function") {
                            return listener.call(this, event);
                        }
                        return listener?.handleEvent?.(event);
                    },
                    options,
                );
            };
        })();
        """
    )


def wait_for_offline_sync_records(user, *, minimum=None, exact=None):
    user.page.wait_for_function(
        OFFLINE_SYNC_RECORD_WAIT,
        arg={"minimum": minimum, "exact": exact},
    )


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
        2. Fail /ping while leaving the browser online
        3. Trigger a focus sync event and verify the indicator becomes visible
        4. Restore /ping and trigger another focus sync event
        5. Verify the indicator hides again

    Verifies:
        - Failed server health checks mark the view offline
        - A later sync event can restore online state without a test-only hook
    """
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    indicator = user.locate(OFFLINE_INDICATOR)
    failed_pings = []

    def fail_ping(route):
        assert route.request.method == "HEAD"
        failed_pings.append(route.request)
        route.abort("connectionfailed")

    with scoped_browser_route(user.page.context, "**/ping", fail_ping):
        with browser_failures.expect(
            user,
            kind="requestfailed",
            method="HEAD",
            path="/ping",
            failure="net::ERR_CONNECTION_FAILED",
        ):
            with browser_failures.expect(
                user,
                kind="console",
                console_type="error",
                text="Failed to load resource: net::ERR_CONNECTION_FAILED",
                source_path="/ping",
            ):
                trigger_focus_sync(user)
                expect(indicator).to_be_visible()

    assert len(failed_pings) == 1

    with expect_successful_response(
        user.page,
        method="HEAD",
        path="/ping",
    ):
        trigger_focus_sync(user)
    expect(indicator).to_be_hidden()


# @features offline
# @dimensions indicator browser-state server-health reconnect
def test_offline_poll_recovers_without_online_event(get_user, browser_failures):
    """
    Test that offline recovery does not depend solely on the online event.

    Flow:
        1. Navigate home with the app's online listener suppressed
        2. Allow production polling, then set the browser context offline
        3. Verify the offline indicator becomes visible
        4. Restore the browser context without delivering online to the app
        5. Verify the retry loop pings the server and hides the indicator

    Verifies:
        - Offline state schedules a server health retry
        - A later successful ping restores online UI without an online event
    """
    user = get_user(Users.OWNER)
    suppress_online_event_sync(user)
    user.go(SitePages.HOME)
    user.page.evaluate("window.__TESTING__ = false;")

    indicator = user.locate(OFFLINE_INDICATOR)
    with browser_failures.expect_offline(user):
        user.offline = True
        expect(indicator).to_be_visible()

    user.offline = False
    expect(indicator).to_be_hidden(timeout=8000)


# @features offline
# @dimensions sync-queue reconnect
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

    with browser_failures.expect_offline(user):
        user.offline = True
        editor.type_text("offline edit")
        editor.text_entry.blur()
        wait_for_offline_sync_records(user, minimum=1)

    with user.page.expect_response("**/sync") as response_info:
        user.offline = False
    assert response_info.value.ok
    wait_for_offline_sync_records(user, exact=0)


# @features offline
# @dimensions indicator transitions
def test_rapid_offline_online_transitions(get_user, browser_failures):
    """
    Test that rapid offline/online toggling settles to the correct state.

    Flow:
        1. Navigate to home
        2. Toggle offline/online 5 times rapidly
        3. Verify indicator settles to hidden (online)

    Verifies:
        - No stale state after rapid transitions
        - Indicator reflects final state
    """
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    indicator = user.locate(OFFLINE_INDICATOR)

    with browser_failures.expect_offline(user):
        for _ in range(5):
            user.offline = True
            user.offline = False

    expect(indicator).to_be_hidden()


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
