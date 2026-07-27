from flask import render_template

from lagniappe.web.auth import test_permission

from . import testing


# @testable true
# @tests tests_e2e/001_site/test_001c_messaging.py::test_allow_messages
@testing.route("/messaging", methods=["GET"])
@test_permission
def main():
    return render_template("testing/main.html")
