"""Setup retries must not turn application or persistent failures into passes."""

from collections import defaultdict
from types import SimpleNamespace

import pytest

from testing.utility.browser_failures import BrowserFailureCollector
from testing.utility.navigation import navigate_with_static_retry


pytestmark = pytest.mark.tooling
URL = "https://test.example/"
ASSET = URL + "chunks/foundation.js?v=test"


class Page:
    def __init__(self, statuses, *, asset=ASSET, method="GET", kind="script", headers=None, document_status=200):
        self.context = SimpleNamespace(pages=[self], on=lambda *_: None)
        self.url = URL
        self.listeners = defaultdict(list)
        self.statuses = iter(statuses)
        self.asset = asset
        self.method = method
        self.kind = kind
        self.headers = headers or {}
        self.document_status = document_status
        self.navigations = []

    def on(self, event, callback):
        self.listeners[event].append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event, value):
        for callback in self.listeners[event][:]:
            callback(value)

    def goto(self, url, *, wait_until):
        assert url == URL and wait_until == "load"
        self.navigations.append("goto")
        return self.load()

    def reload(self, *, wait_until):
        assert wait_until == "load"
        self.navigations.append("reload")
        return self.load()

    def load(self):
        self.status = next(self.statuses)
        self.emit("response", SimpleNamespace(
            status=self.status, url=self.asset, headers=self.headers,
            request=SimpleNamespace(method=self.method, resource_type=self.kind),
            text=lambda: "Unavailable",
        ))
        if self.status >= 400:
            self.emit("console", SimpleNamespace(
                type="error",
                text=f"Failed to load resource: the server responded with a status of {self.status} ()",
                location={"url": self.asset, "lineNumber": 0},
            ))
        return SimpleNamespace(status=self.document_status, url=URL)

    def initialize(self):
        assert self.status == 200, "View not initialized"


def monitor(page):
    failures = BrowserFailureCollector()
    failures.monitor_context(page.context, label="Test user")
    return failures


# @matrix e2e : navigation static-assets failure-reporting
def test_navigation_recovers_only_the_current_pages_exact_static_error(caplog):
    page = Page([503, 200])
    failures = monitor(page)
    other = Page([503])
    failures.monitor_context(other.context, label="Other user")
    other.load()
    # An older matching failure must not be excused by this navigation either.
    page.emit("console", SimpleNamespace(type="error", text="earlier failure", location={"url": ASSET}))

    navigate_with_static_retry(page, URL, initialize=page.initialize, browser_failures=failures)

    assert page.navigations == ["goto", "reload"]
    assert failures.events[-1].ignored_reason == "static-503-recovered-by-navigation"
    assert all(event.ignored_reason is None for event in failures.events[:-1])
    assert "recovered after one reload" in caplog.text
    assert len(page.listeners["response"]) == 1  # Only the ordinary collector remains.
    with pytest.raises(AssertionError, match="Other user"):
        failures.assert_clean()


# @matrix e2e : bounded-retry failure-reporting
@pytest.mark.parametrize("statuses", [[503, 503], [503, 404]])
def test_navigation_persistent_asset_failure_still_fails(statuses):
    page = Page(statuses)
    failures = monitor(page)
    with pytest.raises(AssertionError):
        navigate_with_static_retry(page, URL, initialize=page.initialize, browser_failures=failures)
    assert page.navigations == ["goto", "reload"]
    assert all(event.ignored_reason is None for event in failures.events)
    with pytest.raises(AssertionError, match="Unexpected browser failures"):
        failures.assert_clean()
    assert len(page.listeners["response"]) == 1


# @matrix e2e : navigation bounded-retry
@pytest.mark.parametrize("options", [
    {"statuses": [404]},
    {"statuses": [500]},
    {"asset": URL + "l/poll", "kind": "fetch"},
    {"asset": URL + "l/query.js"},
    {"asset": "https://external.example/chunks/foundation.js"},
    {"method": "POST"},
    {"kind": "image"},
    {"headers": {"x-lagniappe-error": "Error 503"}},
    {"document_status": 500},
])
def test_navigation_does_not_retry_other_errors(options):
    page = Page(**{"statuses": [503], **options})
    failures = monitor(page)
    with pytest.raises(AssertionError):
        navigate_with_static_retry(page, URL, initialize=page.initialize, browser_failures=failures)
    assert page.navigations == ["goto"]
    assert all(event.ignored_reason is None for event in failures.events)


# @matrix e2e : navigation
def test_navigation_keeps_view_assertions_and_expected_http_status():
    page = Page([200])
    def broken_view():
        raise AssertionError("Broken view")
    with pytest.raises(AssertionError, match="Broken view"):
        navigate_with_static_retry(page, URL, initialize=broken_view)
    assert page.navigations == ["goto"]
    assert not page.listeners["response"]

    page = Page([200], document_status=403)
    response = navigate_with_static_retry(page, URL, expected_status=403)
    assert response.status == 403 and page.navigations == ["goto"]


# @matrix e2e : failure-reporting
def test_navigation_recovery_does_not_hide_an_unrelated_page_error():
    page = Page([503, 200])
    failures = monitor(page)
    def initialize():
        page.initialize()
        page.emit("pageerror", RuntimeError("Broken application"))
    navigate_with_static_retry(page, URL, initialize=initialize, browser_failures=failures)
    with pytest.raises(AssertionError, match="Broken application"):
        failures.assert_clean()
