from flask import abort

from lagniappe.core.definitions.manual import (
    MANUAL_SECTIONS,
    VALID_MANUAL_SECTIONS,
)
from lagniappe.web.auth import manual_permission
from lagniappe.web import responses

from . import manual


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_navigate_to_manual_from_home_button
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_security_section_loads
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_public_manual_loads_without_login_or_auth_bootstrap
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_ai_manual_keeps_account_addresses_authenticated
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_search_metadata_and_navigation
# @matrix manual : address-redaction ai-email anonymous-access direct-section no-auth-bootstrap page-load section-navigation
@manual.route("/", methods=["GET"])
@manual.route("/<section>", methods=["GET"])
@manual_permission()
def index(section=None):
    if section and section not in VALID_MANUAL_SECTIONS:
        abort(404)

    key = section if section in VALID_MANUAL_SECTIONS else "overview"
    return responses.manual_index(key, MANUAL_SECTIONS)


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_navigate_to_manual_from_home_button
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_security_section_loads
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_ai_manual_keeps_account_addresses_authenticated
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_search_metadata_and_navigation
# @matrix manual : address-redaction ai-email ajax-section anonymous-access section-navigation
# @pair manual:page-load
@manual.route("/section/<section>", methods=["GET"])
@manual_permission()
def content(section):
    if section not in VALID_MANUAL_SECTIONS:
        abort(404)

    return responses.manual_content(section)
