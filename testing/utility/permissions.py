"""
Permission testing helpers for user and group permission tests.

Covers ``has_permission`` before/after ``UserPermissions.create()`` (group merge),
``create(form_data)`` for users without groups, and own-page EDIT checks.
"""

from lagniappe.core.definitions import Action


def check_before_permissions(user, resources, expected):
    """
    Check has_permission() for each resource before permissions are combined.

    Args:
        user: User entity to check
        resources: List of (resource, action) tuples
        expected: Dict with "before" key containing list of expected booleans
    """
    assert resources
    assert len(expected["before"]) == len(resources)
    for index, (resource, action) in enumerate(resources):
        result = user.has_permission(resource, action)
        assert result == expected["before"][index], (
            f"{user.name} BEFORE: has_permission({resource.name}, {action.name}) "
            f"= {result}, expected {expected['before'][index]}"
        )


def check_after_permissions(user, resources, expected):
    """
    Check has_permission() for each resource after permissions are combined.

    Stored permission maps are asserted explicitly by the calling scenario.

    Args:
        user: User entity to check
        resources: List of (resource, action) tuples
        expected: Dict with "after" key containing list of expected booleans
    """
    assert resources
    assert len(expected["after"]) == len(resources)
    for index, (resource, action) in enumerate(resources):
        result = user.has_permission(resource, action)
        assert result == expected["after"][index], (
            f"{user.name} AFTER: has_permission({resource.name}, {action.name}) "
            f"= {result}, expected {expected['after'][index]}"
        )



def check_user_page_permission(user):
    """
    Verify user always has EDIT permission on their own page.

    Args:
        user: User entity to check
    """
    assert user.has_permission(user.page, Action.EDIT), (
        f"{user.name}: own page {user.page.hash} should have EDIT permission"
    )
