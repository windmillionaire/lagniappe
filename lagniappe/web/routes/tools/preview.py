"""Browser-session shortcuts for user-facing AI reports."""

import re

from flask import abort, redirect, url_for
from flask_login import current_user

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.web.auth import abort_public_user_action, logged_in

from . import tools


REPORT_HASH_PATTERN = re.compile(r"^[A-Za-z0-9_-]{12}$")


# @testable true
# @tests tests_e2e/013_agent_api/test_013a_agent_api.py::test_api_plan_preview_redirect_is_session_and_creator_bound
# @matrix agent-api ai-report : browser-review creator-bound short-link
@tools.route("/api-plan/<plan_hash>", methods=["GET"])
@logged_in
def api_plan_preview(plan_hash):
    """Resolve an API report's short hash only within its creator's session."""
    abort_public_user_action()
    if not REPORT_HASH_PATTERN.fullmatch(str(plan_hash or "")):
        abort(404)
    record = database_get.ai_report_by_hash(current_user.key, plan_hash)
    report = Entities.fetch_one(record, request=Fetch.direct()) if record else None
    owner_key = getattr(getattr(report, "properties", None), "user", None)
    owner_key = getattr(owner_key, "key", None)
    if (
        not isinstance(report, Entities.REPORT)
        or report.origin != "api"
        or owner_key != current_user.key
    ):
        abort(404)
    return redirect(url_for("tools.report", key=report.urlsafe_key))
