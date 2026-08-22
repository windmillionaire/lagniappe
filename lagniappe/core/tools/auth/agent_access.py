from datetime import datetime, timezone
import hmac

from lagniappe import CONFIG
from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_access.py::enabled
# @reason boolean parsing helper exercised through the public access gate
def _enabled_flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_agent_access_config_and_user_helpers
# @features login
# @dimensions agent-access config
def enabled():
    code = str(getattr(CONFIG, "AGENT_ACCESS_CODE", "") or "").strip()
    email = str(getattr(CONFIG, "AGENT_ACCESS_EMAIL", "") or "").strip()
    return bool(
        _enabled_flag(getattr(CONFIG, "AGENT_ACCESS_ENABLED", False)) and code and email
    )


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_agent_access_config_and_user_helpers
# @features login
# @dimensions agent-access code-validation
def code_matches(code):
    expected = str(getattr(CONFIG, "AGENT_ACCESS_CODE", ""))
    submitted = str(code or "").strip()
    return bool(submitted and expected and hmac.compare_digest(submitted, expected))


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_access.py::get_or_create_user
# @reason agent login owns repairing stale agent account access before seeding session
def _ensure_own_page_access(user):
    page = user.page
    if user.has_permission(page, Action.EDIT):
        return

    permissions = dict(user.permissions)
    permissions[page.hash] = Action.EDIT.name
    user.permissions = permissions


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_agent_access_user_helper_creates_or_loads_user_with_groups
# @features login
# @dimensions agent-access user groups user-page
def get_or_create_user():
    email = str(getattr(CONFIG, "AGENT_ACCESS_EMAIL", "")).strip().lower()
    name = str(getattr(CONFIG, "AGENT_ACCESS_NAME", "") or "Agent").strip() or "Agent"

    exists = database.get.user(email)
    if exists:
        user = Entities.fetch_one(
            exists,
            request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
        ) or Entities.USER(exists)
    else:
        user = Entities.USER.create({"email": email, "name": name})

    _ensure_own_page_access(user)
    user.last_login = datetime.now(timezone.utc)
    user.save()
    return user
