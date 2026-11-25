"""Public browser lifecycle helpers for E2E refresh stories."""

from contextlib import contextmanager

from playwright.sync_api import expect

from .network import expect_successful_response


@contextmanager
def expect_reconnect_refresh(user, browser_failures, *, timeout=None):
    """Drive a native reconnect and retain the resulting collection refresh."""
    offline_indicator = user.locate("[data-role='offline']")
    user.page.wait_for_function(
        "() => !document.fonts || document.fonts.status === 'loaded'"
    )
    # Finish the current health cycle before rejecting the reconnect probe.
    user.page.evaluate("() => window.__CONNECTIVITY_READY__")
    with browser_failures.expect_offline(user):
        user.offline = True
        expect(offline_indicator).to_be_visible()

    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/refresh",
        timeout=timeout,
    ) as response_info:
        yield response_info

    expect(offline_indicator).to_be_hidden()
