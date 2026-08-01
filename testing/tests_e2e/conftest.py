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

from contextlib import contextmanager
import fcntl
import logging
import os
from pathlib import Path

import pytest

from config import SETTINGS
from runner.testing import (
    cleanup_test_data,
    prepare_test_artifacts,
    run_test_server,
    terminate_test_server_process,
)

from ..utility import TestResults, capture_on_failure
from ..utility.structural_evidence import full_e2e_collection_state

os.environ["FLASK_ENV"] = "testing"

# Timeout values (in milliseconds)
DEFAULT_TIMEOUT = 15000  # 15 seconds - standard test operations
AI_TIMEOUT = 30000  # 30 seconds - for @pytest.mark.ai tests

logger = logging.getLogger(__name__)
E2E_ROOT = Path(__file__).parent.resolve()


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """Run the accumulated-data evidence check only after a complete E2E collection."""
    evidence_items = [
        item for item in items if item.get_closest_marker("structural_evidence")
    ]
    if not evidence_items:
        return

    root = Path(str(config.rootpath)).resolve()
    expected_files = {
        str(path.resolve().relative_to(root))
        for path in E2E_ROOT.rglob("test_*.py")
    }
    selected_files = {
        str(Path(str(item.path)).resolve().relative_to(root))
        for item in items
        if Path(str(item.path)).resolve().is_relative_to(E2E_ROOT)
    }
    state = full_e2e_collection_state(
        expected_files=expected_files,
        selected_files=selected_files,
        keyword=config.option.keyword,
        mark_expression=config.option.markexpr,
    )
    config._structural_evidence_collection = state

    for evidence_item in evidence_items:
        if not state["full_e2e_run"]:
            reason = "; ".join(state["reasons"])
            evidence_item.add_marker(
                pytest.mark.skip(
                    reason="Structural evidence requires a complete E2E run: "
                    + reason
                )
            )
            continue

        items.remove(evidence_item)
        last_e2e_index = max(
            index
            for index, item in enumerate(items)
            if Path(str(item.path)).resolve().is_relative_to(E2E_ROOT)
        )
        items.insert(last_e2e_index + 1, evidence_item)


@contextmanager
def _e2e_session_lock():
    """Prevent overlapping E2E sessions from sharing one test server."""
    port = SETTINGS.test_config["SERVER_PORT"]
    lock_path = Path("/tmp") / f"lagniappe-e2e-{port}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.seek(0)
            owner = lock_file.read().strip() or "unknown owner"
            pytest.exit(
                "Another E2E pytest session is already running against the "
                f"managed test server on port {port} ({owner}). Run E2E "
                "targets sequentially or pass multiple files/nodeids to one "
                "pytest command.",
                returncode=2,
            )

        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={os.getpid()}")
        lock_file.flush()

        try:
            yield
        finally:
            lock_file.seek(0)
            lock_file.truncate()
            fcntl.flock(lock_file, fcntl.LOCK_UN)


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
    with _e2e_session_lock():
        process = None
        try:
            # Recover from interrupted runs whose fixture finalizers never ran.
            cleanup_test_data()

            # Clean up previous test artifacts
            prepare_test_artifacts()

            process = run_test_server()

            from lagniappe.core.entities import Entities

            Entities.initialize()

            yield
        finally:
            # Cleanup test data from database and cache
            cleanup_test_data()

            # Graceful shutdown with fallback to forceful termination
            if process is not None:
                terminate_test_server_process(process)


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
def get_user(browser, request):
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

    Returns:
        User: Resource with .page, .go(), .locate() methods

    Context Configuration:
        - storage_state: Persisted auth from user.login()
        - permissions: clipboard-read, clipboard-write enabled
        - viewport: 1280x720 desktop size

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

    def _get_user(user_definition, creator=None):
        from testing.definitions.user_definitions import UserDefinition
        from testing.resources import User

        if isinstance(user_definition, UserDefinition):
            user = User(user=creator, definition=user_definition).create()
        else:
            user = user_definition.get(creator)

        # Persisted cache invalidation belongs to the browser acknowledgement
        # protocol; permission-mutating tests must consume it explicitly.
        # Authenticate if user has email but no stored session
        if not user.storage_state and user.email:
            user.login(browser)

        # Close any existing page/context from previous test or fixture reuse.
        if user.page:
            _close_page_context(user.page)
            user.page = None

        # Create isolated browser context with auth state
        context = browser.new_context(
            storage_state=user.storage_state,
            permissions=["clipboard-read", "clipboard-write"],
            viewport={"width": 1280, "height": 720},
        )
        contexts.append(context)

        user.page = context.new_page()
        user.console_messages.clear()

        # Capture console messages for debugging on failure
        def handle_console(msg):
            message = f"{msg.type}: {msg.text}"
            user.console_messages.append(message)
            logger.debug(f"Console [{user.name}]: {message}")

        user.page.on("console", handle_console)

        # Apply appropriate timeout based on test markers
        if request.node.get_closest_marker("ai"):
            user.page.set_default_timeout(AI_TIMEOUT)
        else:
            user.page.set_default_timeout(DEFAULT_TIMEOUT)

        users.append(user)
        return user

    yield _get_user

    try:
        # Teardown: capture screenshots and console logs if test failed
        rep_call = getattr(request.node, "rep_call", None)
        if rep_call and rep_call.failed:
            for user in users:
                if user.page and not user.page.is_closed():
                    for msg in user.console_messages:
                        logger.error(f"\n{user.name} Console: {msg}")
                    capture_on_failure(
                        user.page, f"{request.node.name} - {user.name}"
                    )
    finally:
        for context in list(reversed(contexts)):
            _close_context(context)
        for user in users:
            user.page = None
