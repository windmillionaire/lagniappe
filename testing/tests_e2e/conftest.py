"""
Pytest configuration and fixtures for Lagniappe E2E testing.

This module provides the core infrastructure for running Playwright-based
end-to-end tests against a live Flask test server with real database and
cache connections.

Related Files:
    - runner/testing.py: run_test_server(), server startup and filtering
    - config/__init__.py: SETTINGS.test_config for BASE_URL, SERVER_PORT, GCLOUD_CONFIG
    - testing/resources/user.py: User resource (login, navigation, locate)
    - testing/utility/error_tracking.py: capture_on_failure() for screenshots
    - testing/utility/test_reporting.py: TestResults for recording test data

Fixtures:
    setup_test_server (session): Starts Flask test server, initializes entities,
        cleans up test data on teardown.
    browser (session): Shared Playwright Chromium browser instance.
    get_user (function): Factory for getting authenticated User resources
        with isolated browser contexts.
    results (function): TestResults instance for recording data to HTML reports.

Configuration:
    DEFAULT_TIMEOUT: 15 seconds for standard tests
    AI_TIMEOUT: 30 seconds for tests marked with @pytest.mark.ai

See Also:
    - testing/pytest.ini for test discovery paths and markers
    - documentation/TESTING_WRITING_TESTS.md for test authoring guidance
"""

from dataclasses import dataclass
import logging
import os

import pytest

from config import SETTINGS
from runner.testing import (
    cleanup_test_data,
    initialize_test_data,
    prepare_test_artifacts,
)

from ..utility.browser_failures import BrowserFailureCollector, write_diagnostic_report
from ..utility.error_tracking import capture_on_failure
from ..utility.test_reporting import TestResults

os.environ["FLASK_ENV"] = "testing"

# Timeout values (in milliseconds)
DEFAULT_TIMEOUT = 15000  # 15 seconds - standard test operations
AI_TIMEOUT = 30000  # 30 seconds - for @pytest.mark.ai tests

PAGE_REVEAL_TRANSITION_OBSERVER = """
window.__WAIT_FOR_VIEW_TRANSITIONS__ = () => new Promise((resolve) => {
  let inactiveFrames = 0;
  const publishAfterStablePaint = () => {
    const transitionAnimation = document.getAnimations().some((animation) =>
      animation.playState !== "finished" &&
      animation.effect?.pseudoElement?.startsWith("::view-transition")
    );
    if (document.activeViewTransition || transitionAnimation) {
      inactiveFrames = 0;
    } else {
      inactiveFrames += 1;
    }
    if (inactiveFrames >= 2) {
      resolve();
      return;
    }
    requestAnimationFrame(publishAfterStablePaint);
  };
  requestAnimationFrame(publishAfterStablePaint);
});
window.__NAVIGATION_TRANSITION_SETTLED__ = false;
window.__NAVIGATION_TRANSITION_READY__ = new Promise((resolve) => {
  addEventListener("pagereveal", (event) => {
    Promise.resolve(event.viewTransition?.finished)
      .catch(() => undefined)
      .then(async () => {
        // `pagereveal` precedes the first rendered frame. Start sampling after
        // that paint, when Chromium exposes the transition and its animations.
        await new Promise((painted) =>
          requestAnimationFrame(() => requestAnimationFrame(painted))
        );
        await window.__WAIT_FOR_VIEW_TRANSITIONS__();
        window.__NAVIGATION_TRANSITION_SETTLED__ = true;
        resolve();
      });
  }, { once: true });
});
"""

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class E2ERuntime:
    """Browser-facing state shared by every context in one pytest session."""

    run_id: str
    browser_cookies: tuple[dict, ...] = ()


def _validate_hosted_e2e_health():
    """Validate the exact hosted deployment before touching shared test data."""
    import requests

    from lagniappe import CONFIG

    health_response = requests.get(
        f"{CONFIG.BASE_URL}/testing/health",
        timeout=30,
    )
    health_response.raise_for_status()
    expected_health = {
        "ready": True,
        "service": CONFIG.HOSTED_E2E_SERVICE,
        "version": CONFIG.HOSTED_E2E_VERSION,
        "source": CONFIG.HOSTED_E2E_SOURCE,
        "source_snapshot": CONFIG.HOSTED_E2E_SOURCE_SNAPSHOT,
        "build_id": CONFIG.HOSTED_E2E_BUILD_ID,
    }
    if health_response.json() != expected_health:
        raise RuntimeError(
            "Hosted E2E health metadata does not match this job execution."
        )


def _hosted_e2e_browser_cookie(run_id):
    """Exchange one Google OIDC token for the deployment's browser cookie."""
    import requests
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    from lagniappe import CONFIG
    from lagniappe.core.tools.hosted_e2e.auth import HOSTED_E2E_COOKIE

    token = id_token.fetch_id_token(google_requests.Request(), CONFIG.BASE_URL)
    session_response = requests.post(
        f"{CONFIG.BASE_URL}/testing/session",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "run_id": run_id,
            "version": CONFIG.HOSTED_E2E_VERSION,
            "source": CONFIG.HOSTED_E2E_SOURCE,
        },
        timeout=30,
    )
    if session_response.status_code != 204:
        raise RuntimeError(
            "Hosted E2E browser bootstrap was rejected "
            f"(HTTP {session_response.status_code})."
        )
    value = session_response.cookies.get(HOSTED_E2E_COOKIE)
    if not value:
        raise RuntimeError("Hosted E2E bootstrap did not return its browser cookie.")
    return {
        "name": HOSTED_E2E_COOKIE,
        "value": value,
        "url": CONFIG.BASE_URL,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Strict",
    }


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Store pytest phase reports on the test item for fixture teardown access."""
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session", autouse=True)
def setup_test_server():
    """
    Start Flask test server with real database and cache connections.

    This session-scoped fixture runs automatically before any tests.

    Setup:
        1. Starts Flask via runner.testing.run_test_server() (subprocess on test port)
        2. Initializes Entities registry for entity lookups

    Teardown:
        1. Cleans up test data from database (entities with 'test-' prefix)
        2. Cleans up test data from cache
        3. Terminates server process (with 15s graceful shutdown, then kill)

    The server runs against the gcloud config specified in SETTINGS.test_config,
    using test-prefixed entity kinds to isolate test data from production.

    See Also:
        - runner/testing.py: run_test_server() implementation
        - runner/testing.py: cleanup_test_data()
        - lagniappe/core/tools/cache.py: cleanup_test_data()
    """
    from lagniappe import CONFIG

    if CONFIG.hosted_e2e_runner:
        from lagniappe.core.tools.hosted_e2e.lease import E2ELease

        # Hosted execution shares only the cross-machine data lease; it has no
        # local Flask process or checkout-local ownership record.
        _validate_hosted_e2e_health()
        lease = E2ELease()
        lease.__enter__()
        try:
            cleanup_test_data(lease)
            initialize_test_data(lease)
            prepare_test_artifacts(lease)

            from lagniappe.core.entities import Entities

            Entities.initialize()
            yield E2ERuntime(
                run_id=lease.run_id,
                browser_cookies=(_hosted_e2e_browser_cookie(lease.run_id),),
            )
        finally:
            try:
                lease.assert_active()
                cleanup_test_data(lease)
            finally:
                lease.__exit__(None, None, None)
        return

    from runner.test_session import authority_from_environment

    try:
        state, adopter = authority_from_environment(expected_mode="local-e2e")
    except RuntimeError as error:
        pytest.exit(str(error), returncode=2)

    try:
        from runner.testing import wait_for_session_server

        if not wait_for_session_server(
            state["base_url"],
            state["nonce"],
            expected_pid=state["server"]["pid"],
            expected_mode=state["mode"],
            timeout_seconds=2,
        ):
            pytest.exit(
                "Inherited Flask health does not match local E2E ownership.",
                returncode=2,
            )
        from lagniappe.core.entities import Entities

        adopter.assert_active()
        Entities.initialize()
        yield E2ERuntime(run_id=state["nonce"])
    finally:
        adopter.__exit__(None, None, None)


@pytest.fixture(scope="session", autouse=True)
def browser_failure_diagnostics(request):
    """Write one diagnostic report after all function collectors have finalized."""
    if request.config.getoption("--browser-failure-diagnostics"):
        request.config._browser_failure_diagnostics = []
    yield
    if request.config.getoption("--browser-failure-diagnostics"):
        write_diagnostic_report(request.config._browser_failure_diagnostics)


@pytest.fixture(scope="session", autouse=True)
def browser():
    """
    Shared Playwright Chromium browser instance for all tests.

    Session-scoped to avoid browser startup overhead per test. Each test
    gets its own browser context via get_user fixture.

    Configuration:
        - headless=True: Set to False for visual debugging
        - --no-sandbox: Required for some CI environments

    Yields:
        Browser: Playwright Chromium browser instance

    Example (debugging with visible browser):
        Change headless=True to headless=False in this fixture.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        yield browser
        browser.close()


@pytest.fixture
def results(request):
    """
    TestResults instance for recording test data to HTML reports.

    Use this fixture in tests that need to capture and review output,
    particularly useful for AI tests where you want to inspect prompts,
    responses, and other generated content.

    The report is automatically generated during fixture teardown and
    saved to reports/test_reports/{test_name}_{timestamp}.html

    Example:
        def test_ai_generation(results):
            prompt = "Generate a summary"
            response = ai.generate(prompt)

            results.record("prompt", prompt)
            results.record("response", response)
            results.record("metadata", {"model": "example-model", "tokens": 150})

            assert "summary" in response.lower()

    The HTML report includes:
        - Collapsible sections for each recorded value
        - Formatted JSON for dicts/lists
        - Syntax-highlighted values by type
        - Test metadata (timestamp, duration, record count)

    See Also:
        - testing/utility/test_reporting.py: TestResults implementation
    """
    test_results = getattr(request.node, "ai_results", None) or TestResults(
        request.node.name
    )

    yield test_results

    # Finalize and save report on teardown
    test_results.finalize()


@pytest.fixture(autouse=True)
def ai_results(request):
    """
    Automatically attach a TestResults report object to tests marked ``ai``.

    AI tests often need durable prompt/output artifacts. Marked tests can use
    ``request.node.ai_results.record(...)`` directly, while tests that still
    request the existing ``results`` fixture receive the same report object.
    """
    if not request.node.get_closest_marker("ai"):
        yield
        return

    test_results = getattr(request.node, "ai_results", None) or TestResults(
        request.node.name
    )
    request.node.ai_results = test_results

    yield

    test_results.finalize()


@pytest.fixture
def browser_failures(request):
    """Per-test browser failure collector exposed for narrow expected-error scopes."""
    collector = BrowserFailureCollector()
    yield collector
    if request.config.getoption("--browser-failure-diagnostics"):
        diagnostics = getattr(request.config, "_browser_failure_diagnostics", None)
        if diagnostics is None:
            diagnostics = []
            request.config._browser_failure_diagnostics = diagnostics
        diagnostics.append(collector.diagnostic_record(request.node.nodeid))


@pytest.fixture
def get_user(browser, request, browser_failures, setup_test_server):
    """
    Factory fixture for getting authenticated User resources with isolated contexts.

    This is the primary entry point for tests. Each call returns a User with:
    - Its own browser context (isolated cookies/storage)
    - Authentication state persisted from login
    - Console message capture for debugging
    - Automatic screenshot capture on test failure

    Args:
        user_definition: A Users enum member or a fresh UserDefinition for an
            exact-lifecycle story
        creator: User with admin permissions to create new users
        has_touch: Whether the isolated browser context supports touch input.
            Required for Playwright tap gestures; viewport resizing alone does
            not enable touch events.

    Returns:
        User: Resource with .page, .go(), .locate() methods

    Context Configuration:
        - storage_state: Persisted auth from user.login()
        - permissions: clipboard-read, clipboard-write enabled
        - viewport: 1280x720 desktop size
        - has_touch: disabled unless explicitly requested by the test

    Timeout Behavior:
        - Standard tests: 15 seconds (DEFAULT_TIMEOUT)
        - @pytest.mark.ai tests: 30 seconds (AI_TIMEOUT)

    Failure Handling:
        On test failure, automatically captures for every user created in the test:
        - Screenshot to reports/test_failures/{test_name} - {user_name} - {timestamp}.png
        - HTML content to reports/test_failures/{test_name} - {user_name} - {timestamp}.html
          (only when page content matches 500-style heuristics)
        - Console messages logged at ERROR level

    Example:
        def test_example(get_user):
            user = get_user(Users.OWNER)
            home = user.go(SitePages.HOME)
            user.locate(home.CATEGORY_LIST_TOGGLE).click()

    See Also:
        - testing/definitions/users.py: User definitions (OWNER, ANONYMOUS, etc.)
        - testing/resources/user.py: User resource implementation
    """

    users = []
    contexts = []

    def _close_context(context):
        try:
            context.close()
        except Exception as exc:
            logger.debug(f"Browser context close skipped: {exc}")

    def _close_page_context(page):
        context = page.context
        try:
            if not page.is_closed():
                page.close()
        except Exception as exc:
            logger.debug(f"Browser page close skipped: {exc}")

        _close_context(context)
        if context in contexts:
            contexts.remove(context)

    def _get_user(user_definition, creator=None, *, has_touch=False):
        from testing.definitions.user_definitions import UserDefinition
        from testing.resources import User

        if isinstance(user_definition, UserDefinition):
            user = User(user=creator, definition=user_definition).create()
        else:
            user = user_definition.get(creator)

        user.console_messages.clear()

        # Persisted cache invalidation belongs to the browser acknowledgement
        # protocol; permission-mutating tests must consume it explicitly.
        # Authenticate if user has email but no stored session.
        if not user.storage_state and user.email:
            user.login(
                browser,
                cookies=setup_test_server.browser_cookies,
                monitor_context=lambda context: browser_failures.monitor_context(
                    context,
                    label=user.name,
                    console_messages=user.console_messages,
                ),
            )

        # Close any existing page/context from previous test or fixture reuse.
        if user.page:
            _close_page_context(user.page)
            user.page = None

        # Create isolated browser context with auth state
        context = browser.new_context(
            storage_state=user.storage_state,
            permissions=["clipboard-read", "clipboard-write"],
            viewport={"width": 1280, "height": 720},
            has_touch=has_touch,
        )
        if setup_test_server.browser_cookies:
            context.add_cookies(list(setup_test_server.browser_cookies))
        context.add_init_script(script=PAGE_REVEAL_TRANSITION_OBSERVER)
        contexts.append(context)
        browser_failures.monitor_context(
            context,
            label=user.name,
            console_messages=user.console_messages,
        )

        user.page = context.new_page()

        # Apply appropriate timeout based on test markers
        if request.node.get_closest_marker("ai"):
            user.page.set_default_timeout(AI_TIMEOUT)
        else:
            user.page.set_default_timeout(DEFAULT_TIMEOUT)

        users.append(user)
        return user

    yield _get_user

    try:
        # Teardown: capture screenshots and console logs for either assertion
        # failures or browser failures discovered by the universal guard.
        rep_call = getattr(request.node, "rep_call", None)
        unexpected = [
            event
            for event in browser_failures.events
            if event.expected_by is None and event.ignored_reason is None
        ]
        if (rep_call and rep_call.failed) or unexpected:
            for user in users:
                if user.page and not user.page.is_closed():
                    for msg in user.console_messages:
                        logger.error(f"\n{user.name} Console: {msg}")
                    capture_on_failure(user.page, f"{request.node.name} - {user.name}")
        if unexpected and not request.config.getoption("--browser-failure-diagnostics"):
            browser_failures.assert_clean()
    finally:
        for context in list(reversed(contexts)):
            _close_context(context)
        for user in users:
            user.page = None
