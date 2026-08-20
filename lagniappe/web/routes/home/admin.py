from lagniappe.core.definitions import Resource
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import home


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_admin_directory_link_opens_admin_settings
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_is_owner_only
# @features admin
# @dimensions route owner-only site-settings
@home.route("/admin", methods=["GET"])
@permission(Resource.SITE)
def admin():
    return responses.admin_page()
