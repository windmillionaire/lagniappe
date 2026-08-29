"""Resolve the active user for request and unit-test code paths."""

from flask import has_request_context
from flask_login import current_user

from lagniappe import CONFIG


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_current_user_prefers_explicit_user
# @tests tests_unit/test_001_test_general_and_utilities.py::test_current_user_uses_config_test_user_without_request
# @tests tests_unit/test_001_test_general_and_utilities.py::test_current_user_prefers_flask_user_over_config
# @matrix testing users : config-mutable current-user flask-request resolver
def current_context_user(user=None):
    """Return explicit user, Flask-Login user in requests, then test config user."""
    if user is not None:
        return user

    if has_request_context():
        return current_user

    return getattr(CONFIG, "TEST_CURRENT_USER", None)
