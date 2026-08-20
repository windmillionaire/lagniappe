"""Public browser lifecycle helpers for E2E refresh stories."""

from contextlib import contextmanager

from playwright.sync_api import expect

from .network import expect_successful_response


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_forms_index_page
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_reconnect_refreshes_external_page
# @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_shows_public_users
# @features e2e
# @dimensions reconnect-refresh
@contextmanager
def expect_reconnect_refresh(user, browser_failures, *, timeout=None):
    """Drive a native reconnect and retain the resulting collection refresh."""
    offline_indicator = user.locate("[data-role='offline']")
    user.page.wait_for_function(
        "() => !document.fonts || document.fonts.status === 'loaded'"
    )
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
