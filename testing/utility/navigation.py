"""Bounded recovery for static-file failures during E2E setup navigation."""

import logging
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as BrowserTimeout


logger = logging.getLogger(__name__)


# @testable true
# @tests tests_tooling/test_004_navigation.py::test_*
# @tests tests_e2e/001_site/test_001a_environment.py::test_setup_navigation_recovers_a_static_503
# @matrix e2e : navigation static-assets bounded-retry failure-reporting
def navigate_with_static_retry(
    page, url, *, expected_status=None, initialize=None, browser_failures=None,
):
    """Reload once for a confirmed static GET 503; retain all other failures."""
    origin = urlsplit(url)
    failed_urls = set()
    loaded_urls = set()
    event_start = len(browser_failures.events) if browser_failures else 0

    def response_received(response):
        parsed = urlsplit(response.url)
        request = response.request
        static_path = (
            parsed.path.startswith("/chunks/") and parsed.path.endswith(".js")
        ) or parsed.path in {"/script.js", "/login.js", "/public.js", "/sentry.js", "/style.css"}
        if (
            (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc)
            or request.method != "GET"
            or request.resource_type not in {"script", "stylesheet"}
            or not static_path
        ):
            return
        if response.status == 503 and "x-lagniappe-error" not in response.headers:
            failed_urls.add(response.url)
        elif 200 <= response.status < 300 or response.status == 304:
            loaded_urls.add(response.url)

    page.on("response", response_received)
    recovered_urls = set()
    try:
        for attempt in range(2):
            failed_urls.clear()
            loaded_urls.clear()
            response = None
            unexpected_status = False
            try:
                response = (
                    page.goto(url, wait_until="load") if attempt == 0
                    else page.reload(wait_until="load")
                )
                # A document/application error must not borrow an asset's retry.
                unexpected_status = bool(
                    response and expected_status is not None
                    and response.status != expected_status
                )
                if unexpected_status:
                    raise AssertionError(
                        f"Navigation returned HTTP {response.status}, expected "
                        f"{expected_status}: {response.url}"
                    )
                if response and expected_status is None and response.status >= 400:
                    raise AssertionError(
                        f"Navigation failed with HTTP {response.status}: {response.url}"
                    )
                if failed_urls:
                    raise AssertionError(f"Startup static HTTP 503: {sorted(failed_urls)}")
                if initialize:
                    initialize()
                if failed_urls:
                    raise AssertionError(f"Startup static HTTP 503: {sorted(failed_urls)}")
            except (AssertionError, BrowserTimeout):
                if attempt or not failed_urls or unexpected_status or (response and response.status >= 400):
                    raise
                recovered_urls = set(failed_urls)
                logger.warning("Reloading setup navigation after static HTTP 503: %s", sorted(recovered_urls))
                continue

            if recovered_urls:
                assert recovered_urls <= loaded_urls, "Reload did not recover every failed startup asset"
                if browser_failures:
                    for event in browser_failures.events[event_start:]:
                        if (
                            event.page_id == id(page)
                            and event.kind == "console"
                            and event.details.get("source_url") in recovered_urls
                            and event.details.get("http_status") == "503"
                            and "Failed to load resource" in (event.details.get("text") or "")
                        ):
                            event.ignored_reason = "static-503-recovered-by-navigation"
                logger.warning("Setup navigation recovered after one reload: %s", sorted(recovered_urls))
            return response
    finally:
        page.remove_listener("response", response_received)
