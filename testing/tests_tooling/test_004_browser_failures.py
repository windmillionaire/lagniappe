"""Tests for the E2E browser-failure collection support."""

import json
from types import SimpleNamespace

import pytest

from testing.utility.browser_failures import (
    BrowserFailureCollector,
    write_diagnostic_report,
)


pytestmark = pytest.mark.tooling


class FakeContext:
    def __init__(self):
        self.pages = []
        self.listeners = {}

    def on(self, event, callback):
        self.listeners[event] = callback

    def new_page(self, url="http://test.local/page"):
        page = FakePage(self, url)
        self.pages.append(page)
        self.listeners["page"](page)
        return page


class FakePage:
    def __init__(self, context, url):
        self.context = context
        self.url = url
        self.listeners = {}

    def on(self, event, callback):
        self.listeners[event] = callback

    def emit(self, event, value):
        self.listeners[event](value)


def _user(page):
    return SimpleNamespace(page=page)


def test_collector_tracks_only_console_errors_and_later_context_pages():
    collector = BrowserFailureCollector()
    context = FakeContext()
    messages = []
    collector.monitor_context(context, label="Owner", console_messages=messages)
    page = context.new_page()

    page.emit(
        "console",
        SimpleNamespace(
            type="warning",
            text="ordinary warning",
            location={"url": "http://test.local/app.js", "lineNumber": 3},
        ),
    )
    second = context.new_page("http://test.local/second")
    second.emit(
        "console",
        SimpleNamespace(
            type="error",
            text="broken widget",
            location={"url": "http://test.local/app.js", "lineNumber": 9},
        ),
    )

    assert messages == ["warning: ordinary warning", "error: broken widget"]
    assert [event.as_dict() for event in collector.events] == [
        {
            "kind": "console",
            "context": "Owner",
            "page_url": "http://test.local/second",
            "details": {
                "console_type": "error",
                "text": "broken widget",
                "source_url": "http://test.local/app.js",
                "source_path": "/app.js",
                "line": "9",
            },
            "expected": False,
            "expectation": None,
            "actionable": True,
            "ignored_reason": None,
        }
    ]


def test_expected_request_failure_requires_exact_context_bound_count():
    collector = BrowserFailureCollector()
    first_context = FakeContext()
    second_context = FakeContext()
    collector.monitor_context(first_context, label="Owner")
    collector.monitor_context(second_context, label="Collaborator")
    first = first_context.new_page()
    second = second_context.new_page()

    with collector.expect(
        _user(first),
        kind="requestfailed",
        method="POST",
        path="/sync",
    ):
        first.emit(
            "requestfailed",
            SimpleNamespace(
                method="POST",
                url="http://test.local/sync?retry=1",
                failure="net::ERR_FAILED",
            ),
        )
        second.emit(
            "requestfailed",
            SimpleNamespace(
                method="POST",
                url="http://test.local/sync",
                failure="net::ERR_FAILED",
            ),
        )

    with pytest.raises(AssertionError, match="Collaborator"):
        collector.assert_clean()


def test_offline_scope_requires_the_native_ping_failure_and_console_error():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with collector.expect_offline(_user(page)):
        page.emit(
            "requestfailed",
            SimpleNamespace(
                method="HEAD",
                url="http://test.local/l/ping",
                failure="net::ERR_INTERNET_DISCONNECTED",
            ),
        )
        page.emit(
            "console",
            SimpleNamespace(
                type="error",
                text="Failed to load resource: net::ERR_INTERNET_DISCONNECTED",
                location={"url": "http://test.local/l/ping", "lineNumber": 0},
            ),
        )

    collector.assert_clean()


def test_offline_scope_accepts_an_exact_reload_ping_count():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with collector.expect_offline(_user(page), ping_count=2):
        for _ in range(2):
            page.emit(
                "requestfailed",
                SimpleNamespace(
                    method="HEAD",
                    url="http://test.local/l/ping",
                    failure="net::ERR_INTERNET_DISCONNECTED",
                ),
            )
            page.emit(
                "console",
                SimpleNamespace(
                    type="error",
                    text="Failed to load resource: net::ERR_INTERNET_DISCONNECTED",
                    location={"url": "http://test.local/l/ping", "lineNumber": 0},
                ),
            )

    collector.assert_clean()


def test_offline_scope_accepts_a_bounded_reload_ping_count():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with collector.expect_offline(
        _user(page),
        ping_count=2,
        max_ping_count=3,
    ):
        for _ in range(3):
            page.emit(
                "requestfailed",
                SimpleNamespace(
                    method="HEAD",
                    url="http://test.local/l/ping",
                    failure="net::ERR_INTERNET_DISCONNECTED",
                ),
            )
            page.emit(
                "console",
                SimpleNamespace(
                    type="error",
                    text="Failed to load resource: net::ERR_INTERNET_DISCONNECTED",
                    location={"url": "http://test.local/l/ping", "lineNumber": 0},
                ),
            )

    collector.assert_clean()


def test_offline_scope_rejects_ping_counts_above_the_bound():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with pytest.raises(AssertionError, match="between 2 and 3 browser failure"):
        with collector.expect_offline(
            _user(page),
            ping_count=2,
            max_ping_count=3,
        ):
            for _ in range(4):
                page.emit(
                    "requestfailed",
                    SimpleNamespace(
                        method="HEAD",
                        url="http://test.local/l/ping",
                        failure="net::ERR_INTERNET_DISCONNECTED",
                    ),
                )
                page.emit(
                    "console",
                    SimpleNamespace(
                        type="error",
                        text=(
                            "Failed to load resource: "
                            "net::ERR_INTERNET_DISCONNECTED"
                        ),
                        location={
                            "url": "http://test.local/l/ping",
                            "lineNumber": 0,
                        },
                    ),
                )


@pytest.mark.parametrize("count", [0, 2])
def test_bounded_scope_can_allow_an_optional_exact_failure(count):
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with collector.expect(
        _user(page),
        kind="console",
        count=0,
        max_count=2,
        console_type="error",
        text_contains="status of 503",
        source_path="/notifications",
    ):
        for _ in range(count):
            page.emit(
                "console",
                SimpleNamespace(
                    type="error",
                    text="Failed to load resource: status of 503",
                    location={
                        "url": "http://test.local/notifications",
                        "lineNumber": 0,
                    },
                ),
            )

    collector.assert_clean()


def test_http_error_scope_matches_status_path_and_count():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with collector.expect_http_error(
        _user(page),
        status=422,
        path="http://test.local/poll?source=test",
        count=2,
    ):
        for reason in ("UNPROCESSABLE ENTITY", "Unprocessable Content"):
            page.emit(
                "console",
                SimpleNamespace(
                    type="error",
                    text=(
                        "Failed to load resource: the server responded with a "
                        f"status of 422 ({reason})"
                    ),
                    location={"url": "http://test.local/poll", "lineNumber": 0},
                ),
            )

    collector.assert_clean()


def test_http_error_scope_supports_bounded_optional_console_reporting():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with collector.expect_http_error(
        _user(page),
        status=400,
        path="http://test.local/auth",
        count=0,
        max_count=1,
    ):
        pass

    collector.assert_clean()


@pytest.mark.parametrize("count", [0, 2])
def test_expected_scope_fails_when_failure_count_is_not_exact(count):
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()

    with pytest.raises(AssertionError, match="Expected 1 browser failure"):
        with collector.expect(_user(page), kind="pageerror", message="sentinel"):
            for _ in range(count):
                page.emit("pageerror", RuntimeError("sentinel"))

    collector.assert_clean()


def test_unexpected_events_report_request_and_page_details():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page("http://test.local/home")
    page.emit("pageerror", RuntimeError("unhandled sentinel"))

    with pytest.raises(AssertionError) as error:
        collector.assert_clean()

    assert "pageerror" in str(error.value)
    assert "http://test.local/home" in str(error.value)
    assert "unhandled sentinel" in str(error.value)


def test_navigation_cancellations_are_reported_but_do_not_fail_teardown():
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()
    page.emit(
        "requestfailed",
        SimpleNamespace(
            method="GET",
            url="http://test.local/activity",
            failure="net::ERR_ABORTED",
        ),
    )

    collector.assert_clean()
    assert collector.events[0].ignored_reason == "browser-navigation-cancellation"


def test_diagnostic_report_preserves_expected_and_unexpected_events(tmp_path):
    collector = BrowserFailureCollector()
    context = FakeContext()
    collector.monitor_context(context, label="Owner")
    page = context.new_page()
    with collector.expect(_user(page), kind="pageerror", message="expected"):
        page.emit("pageerror", RuntimeError("expected"))
    page.emit("pageerror", RuntimeError("unexpected"))

    path = tmp_path / "browser-failures.json"
    write_diagnostic_report([collector.diagnostic_record("test_node")], path=path)
    payload = json.loads(path.read_text())

    assert payload["schema_version"] == 1
    assert payload["tests"][0]["nodeid"] == "test_node"
    assert [event["expected"] for event in payload["tests"][0]["events"]] == [
        True,
        False,
    ]
