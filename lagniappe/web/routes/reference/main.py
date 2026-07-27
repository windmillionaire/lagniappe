from flask import abort

from config import SETTINGS
from config.recovery import (
    RecoveryConfigurationError,
    build_recovery_snapshot,
    read_recovery_redis_ca,
)
from lagniappe.core.definitions import Resource
from lagniappe.core.tools import database
from lagniappe.web.auth import logged_in, permission
from lagniappe.web import responses

from . import reference


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_form
# @features projects
# @dimensions create-help
@reference.route("/section/<section>")
@logged_in
def section(section):
    """Document settings help page."""
    return responses.reference_topic(section)


# @testable true
# @tests tests_e2e/001_site/test_001c_messaging.py::test_allow_messages
@reference.route("/messaging")
@logged_in
def messaging():
    """Messaging help page."""
    return responses.reference_topic("messaging")


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_is_owner_only
@reference.route("/environment-variables")
@permission(Resource.SITE)
def environment_variables():
    """Return environment variables as YAML formatted HTML."""
    env_data = SETTINGS.app_settings

    return responses.reference_environment_variables(env_data)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_is_owner_only
# @tests tests_e2e/008_users/test_008f_recovery_settings.py::test_owner_download_is_complete_canonical_and_not_cacheable
# @tests tests_e2e/008_users/test_008f_recovery_settings.py::test_owner_download_fails_closed_when_live_settings_are_unavailable
# @features admin
# @dimensions recovery-export failure-isolation
@reference.route("/download-settings")
@permission(Resource.SITE)
def download_settings():
    """Download the complete canonical recovery snapshot."""
    try:
        persisted = SETTINGS.app_settings
        env_vars = build_recovery_snapshot(
            persisted,
            deployment_settings=database.get.site_deployment(),
            ai_settings=database.get.site_ai(),
            redis_ca_pem=read_recovery_redis_ca(persisted),
        )
    except Exception as error:
        if isinstance(error, RecoveryConfigurationError):
            message = "The recovery snapshot is incomplete."
        else:
            message = "The recovery snapshot could not be read."
        abort(503, f"{message} No settings were downloaded.")

    return responses.reference_environment_variables(env_vars, download=True)
