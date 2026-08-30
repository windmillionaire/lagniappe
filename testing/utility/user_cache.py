"""Browser-owned user cache invalidation helpers for E2E tests."""

from lagniappe.core.entities import Entities
from testing.definitions import SitePages


# @testable false
# @reason Reusable E2E cache protocol; consuming tests assert product outcomes.
def acknowledge_user_cache_invalidation(user, destination=None):
    """Consume a permission mutation through the browser-owned protocol."""
    assert Entities.USER.load(user.email).invalidate_cache is True
    destination = destination or SitePages.HOME.get(user).url
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        response = user.navigate(destination)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    user.entity = Entities.USER.load(user.email)
    assert user.entity.invalidate_cache is False
    return response
