"""Signed-in, source-backed application reference pages."""

from flask import Blueprint, abort, render_template

from lagniappe.reference import get_topic
from lagniappe.web.auth import logged_in

help_pages = Blueprint("help", __name__)


# @testable true
# @tests tests_e2e/009_search/test_009e_help.py::test_help_article_navigation_and_canonical_ids
# @tests tests_e2e/009_search/test_009e_help.py::test_help_requires_login_but_general_admin_guidance_is_readable
# @matrix help : navigation context-permissions
@help_pages.route("/<topic_id>")
@logged_in
def article(topic_id):
    try:
        topic = get_topic(topic_id)
    except KeyError:
        abort(404)
    return render_template("help/page.html", topic=topic)
