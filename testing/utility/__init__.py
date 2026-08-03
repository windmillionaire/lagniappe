"""
Support helpers for the testing framework.

This package is for test-only infrastructure that does not represent app pages,
entities, or shared UI widgets directly. Keep failure capture, reports, file
helpers, and other support code here rather than in test modules.
"""

from .error_tracking import capture_on_failure
from .network import (
    assert_lagniappe_error_response,
    expect_successful_response,
    multipart_form_fields,
    scoped_browser_route,
)
from .offline import wait_for_offline_mutations, wait_for_offline_sync_records
from .polling import expect_poll_result
from .reconnect import expect_reconnect_refresh
from .test_file import TestFile
from .test_reporting import TestResults

__all__ = [
    "assert_lagniappe_error_response",
    "capture_on_failure",
    "expect_poll_result",
    "expect_successful_response",
    "expect_reconnect_refresh",
    "multipart_form_fields",
    "scoped_browser_route",
    "wait_for_offline_mutations",
    "wait_for_offline_sync_records",
    "TestFile",
    "TestResults",
]
