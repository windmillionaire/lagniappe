"""Resolve the active user for request and unit-test code paths."""

from flask import g, has_request_context
from flask_login import current_user

from lagniappe import CONFIG


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_current_user_prefers_explicit_user
# @tests tests_unit/test_001_test_general_and_utilities.py::test_current_user_uses_config_test_user_without_request
# @tests tests_unit/test_001_test_general_and_utilities.py::test_current_user_prefers_flask_user_over_config
# @tests tests_unit/test_001_test_general_and_utilities.py::test_current_user_prefers_agent_api_user_over_flask_user
# @matrix agent-api testing users : bearer-user config-mutable current-user flask-request resolver
def current_context_user(user=None):
    """Return the explicit, bearer, browser-session, or configured test user."""
    if user is not None:
        return user

    if has_request_context():
        agent_api_user = getattr(g, "agent_api_user", None)
        if agent_api_user is not None:
            return agent_api_user
        return current_user

    return getattr(CONFIG, "TEST_CURRENT_USER", None)
