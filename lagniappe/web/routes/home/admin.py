from flask import g

from lagniappe.core.definitions import Resource
from lagniappe.web import responses
from lagniappe.web.auth import permission

from . import home


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_admin_directory_link_opens_admin_settings
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_requires_administrator
# @tests tests_e2e/008_users/test_008d_admin_data_protection.py::test_backups_tab_reveals_static_status_panel
# @matrix admin : admin-only route site-settings
# @pairs admin:no-store admin:status cache:no-store cache:status disaster-recovery:no-store disaster-recovery:status
@home.route("/admin", methods=["GET"])
@permission(Resource.SITE)
def admin():
    g.NO_CACHE = True
    return responses.admin_page()
