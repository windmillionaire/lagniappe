from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User

from datetime import datetime, UTC
import hmac

from lagniappe import CONFIG
from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get


def _enabled_flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def enabled() -> bool:
    code = str(getattr(CONFIG, "AGENT_ACCESS_CODE", "") or "").strip()
    email = str(getattr(CONFIG, "AGENT_ACCESS_EMAIL", "") or "").strip()
    return bool(
        _enabled_flag(getattr(CONFIG, "AGENT_ACCESS_ENABLED", False)) and code and email
    )


def code_matches(code: str | None) -> bool:
    expected = str(getattr(CONFIG, "AGENT_ACCESS_CODE", ""))
    submitted = str(code or "").strip()
    return bool(submitted and expected and hmac.compare_digest(submitted, expected))


def _ensure_own_page_access(user):
    page = user.page
    if user.has_permission(page, Action.EDIT):
        return

    permissions = dict(user.permissions)
    permissions[page.hash] = Action.EDIT.name
    user.permissions = permissions


def get_or_create_user() -> User:
    email = str(getattr(CONFIG, "AGENT_ACCESS_EMAIL", "")).strip().lower()
    name = str(getattr(CONFIG, "AGENT_ACCESS_NAME", "") or "Agent").strip() or "Agent"

    exists = database_get.user(email)
    if exists:
        user = Entities.fetch_one(
            exists,
            request=Fetch.nested(because=FetchReason.USER_SAVE_REQUIREMENTS),
        ) or Entities.USER(exists)
    else:
        user = Entities.USER.create({"email": email, "name": name})

    assert user is not None
    _ensure_own_page_access(user)
    user.last_login = datetime.now(UTC)
    user.save()
    return cast("User", user)
