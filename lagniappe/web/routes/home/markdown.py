"""Authenticated Markdown rendering endpoint."""

from flask import request

from lagniappe.core.tools.files.html import render_markdown
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import internal


# @testable true
# @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_markdown_table_preserves_table_after_reload
# @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_plain_html_inserts_safe_formatted_content
# @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_common_markdown_preserves_formatting
# @matrix editor markdown : conversion paste
@internal.route("/markdown", methods=["POST"])
@logged_in
def markdown():
    """Render a plain Markdown string into sanitized editor-compatible HTML."""
    payload = request.get_json(silent=True) or {}
    source = payload.get("markdown")
    if not isinstance(source, str):
        return responses.error("Markdown must be a string.")
    return responses.json_response({"markup": render_markdown(source)})
