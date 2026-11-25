"""Resolve the active user for request and unit-test code paths."""

from typing import TYPE_CHECKING, Literal, cast, overload

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User
    from werkzeug.local import LocalProxy

from flask import g, has_request_context
from flask_login import current_user

from lagniappe import CONFIG


@overload
def current_context_user(user: User | None = None) -> User | None: ...
@overload
def current_context_user(user: LocalProxy[User | None]) -> LocalProxy[User | None]: ...
@overload
def current_context_user(user: Literal[False]) -> Literal[False]: ...


def current_context_user(
    user: User | LocalProxy[User | None] | Literal[False] | None = None,
) -> User | LocalProxy[User | None] | Literal[False] | None:
    """Return the explicit, bearer, browser-session, or configured test user."""
    if user is not None:
        return user

    if has_request_context():
        agent_api_user = getattr(g, "agent_api_user", None)
        if agent_api_user is not None:
            return agent_api_user
        return cast("User", current_user)

    return getattr(CONFIG, "TEST_CURRENT_USER", None)
