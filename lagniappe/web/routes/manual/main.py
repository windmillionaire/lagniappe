from flask import abort

from lagniappe.web.auth import manual_permission
from lagniappe.web import responses

from . import manual

MANUAL_SECTIONS = [
    {
        "key": "overview",
        "name": "Overview",
        "icon": "overview",
        "kind": "category",
    },
    {
        "key": "quickstart",
        "name": "Quickstart",
        "icon": "launch",
        "kind": "page",
    },
    {
        "key": "forms",
        "name": "Forms",
        "icon": "form",
        "kind": "form",
    },
    {
        "key": "tasks",
        "name": "Tasks",
        "icon": "tasks",
        "kind": "task",
    },
    {
        "key": "permissions",
        "name": "Permissions",
        "icon": "permissions",
        "kind": "user",
    },
    {
        "key": "search",
        "name": "Search & Filters",
        "icon": "search",
        "kind": "page",
    },
    {
        "key": "collaboration",
        "name": "Collaboration",
        "icon": "users",
        "kind": "user",
    },
    {
        "key": "installation",
        "name": "Installation",
        "icon": "installation",
        "kind": "task",
    },
    {
        "key": "security",
        "name": "Security",
        "icon": "security",
        "kind": "user",
    },
    {
        "key": "personalization",
        "name": "Personalization",
        "icon": "personalization",
        "kind": "project",
    },
    {
        "key": "ai",
        "name": "AI Integration",
        "icon": "generate",
        "kind": "form",
    },
    {
        "key": "under-the-hood",
        "name": "Under the Hood",
        "icon": "sitemap",
        "kind": "page",
    },
]


VALID_SECTIONS = {s["key"] for s in MANUAL_SECTIONS}


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_navigate_to_manual_from_home_button
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_security_section_loads
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_public_manual_loads_without_login_or_auth_bootstrap
# @features manual
# @dimensions page-load section-navigation anonymous-access no-auth-bootstrap
@manual.route("/", methods=["GET"])
@manual.route("/<section>", methods=["GET"])
@manual_permission()
def index(section=None):
    if section and section not in VALID_SECTIONS:
        abort(404)

    key = section if section in VALID_SECTIONS else "overview"
    return responses.manual_index(key, MANUAL_SECTIONS)


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_navigate_to_manual_from_home_button
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_security_section_loads
# @features manual
# @dimensions section-navigation
@manual.route("/section/<section>", methods=["GET"])
@manual_permission()
def content(section):
    if section not in VALID_SECTIONS:
        abort(404)

    return responses.manual_content(section)
