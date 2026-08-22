from flask import abort, g

from config import SETTINGS
from lagniappe.core.definitions import Resource
from lagniappe.core.tools.site.recovery import (
    RecoverySnapshotUnavailable,
    load_recovery_snapshot,
)
from lagniappe.web.auth import logged_in, owner_only, permission
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
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_requires_administrator
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
# @pair admin:environment-variables
@reference.route("/environment-variables")
@permission(Resource.SITE)
def environment_variables():
    """Return environment variables as YAML formatted HTML."""
    env_data = SETTINGS.app_settings

    return responses.reference_environment_variables(env_data)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_additional_admin_cannot_access_owner_configuration
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
# @pair owner:recovery-export
@reference.route("/download-settings")
@owner_only
def download_settings():
    """Download the complete canonical recovery snapshot."""
    g.NO_CACHE = True
    try:
        env_vars = load_recovery_snapshot(SETTINGS.app_settings)
    except RecoverySnapshotUnavailable as error:
        abort(503, error.public_message)

    return responses.reference_environment_variables(env_vars, download=True)
