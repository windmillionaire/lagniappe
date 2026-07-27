"""
Support helpers for the testing framework.

This package is for test-only infrastructure that does not represent app pages,
entities, or shared UI widgets directly. Keep failure capture, reports, file
helpers, and other support code here rather than in test modules.
"""

from .error_tracking import capture_on_failure
from .messaging import (
    simulate_collaboration_message,
    simulate_fcm_message,
    simulate_window_message,
)
from .test_file import TestFile
from .test_reporting import TestResults

__all__ = [
    "capture_on_failure",
    "simulate_collaboration_message",
    "simulate_fcm_message",
    "simulate_window_message",
    "TestFile",
    "TestResults",
]
