"""
Support helpers for the testing framework.

This package is for test-only infrastructure that does not represent app pages,
entities, or shared UI widgets directly. Keep failure capture, reports, file
helpers, and other support code here rather than in test modules.
"""

from importlib import import_module


_EXPORTS = {
    "assert_lagniappe_error_response": (".network", "assert_lagniappe_error_response"),
    "assert_same_etag": (".network", "assert_same_etag"),
    "capture_on_failure": (".error_tracking", "capture_on_failure"),
    "expect_offline_sync_replay": (".offline", "expect_offline_sync_replay"),
    "expect_poll_result": (".polling", "expect_poll_result"),
    "expect_reconnect_refresh": (".reconnect", "expect_reconnect_refresh"),
    "expect_successful_response": (".network", "expect_successful_response"),
    "manual_mutation_headers": (".network", "manual_mutation_headers"),
    "multipart_form_fields": (".network", "multipart_form_fields"),
    "scoped_browser_route": (".network", "scoped_browser_route"),
    "wait_for_connectivity_replay": (".offline", "wait_for_connectivity_replay"),
    "wait_for_offline_mutations": (".offline", "wait_for_offline_mutations"),
    "wait_for_offline_sync_records": (".offline", "wait_for_offline_sync_records"),
    "TestFile": (".test_file", "TestFile"),
    "TestResults": (".test_reporting", "TestResults"),
}


# @testable true
# @tests testing/tests_tooling/test_009_hosted_e2e.py::test_traceability_common_import_does_not_require_playwright
# @pair hosted-e2e:ci-import
def __getattr__(name):
    """Load public test helpers without importing browser dependencies eagerly."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "assert_lagniappe_error_response",
    "assert_same_etag",
    "capture_on_failure",
    "expect_offline_sync_replay",
    "expect_poll_result",
    "expect_successful_response",
    "expect_reconnect_refresh",
    "manual_mutation_headers",
    "multipart_form_fields",
    "scoped_browser_route",
    "wait_for_connectivity_replay",
    "wait_for_offline_mutations",
    "wait_for_offline_sync_records",
    "TestFile",
    "TestResults",
]
