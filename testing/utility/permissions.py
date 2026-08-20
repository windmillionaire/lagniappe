"""
Permission testing helpers for user and group permission tests.

Covers ``has_permission`` before/after ``UserPermissions.create()`` (group merge),
``create(form_data)`` for users without groups, and own-page EDIT checks.
"""

from lagniappe.core.definitions import Action, Resource


def check_before_permissions(user, resources, expected):
    """
    Check has_permission() for each resource before permissions are combined.

    Args:
        user: User entity to check
        resources: List of (resource, action) tuples
        expected: Dict with "before" key containing list of expected booleans
    """
    for index, (resource, action) in enumerate(resources):
        result = user.has_permission(resource, action)
        assert result == expected["before"][index], (
            f"{user.name} BEFORE: has_permission({resource.name}, {action.name}) "
            f"= {result}, expected {expected['before'][index]}"
        )


def check_after_permissions(user, resources, expected):
    """
    Check has_permission() for each resource after permissions are combined.

    Also verifies:
    - Entity hash not in permissions if covered by general permission
    - User should have at most one overlapping permission with resource.required

    Args:
        user: User entity to check
        resources: List of (resource, action) tuples
        expected: Dict with "after" key containing list of expected booleans
    """
    for index, (resource, action) in enumerate(resources):
        result = user.has_permission(resource, action)
        assert result == expected["after"][index], (
            f"{user.name} AFTER: has_permission({resource.name}, {action.name}) "
            f"= {result}, expected {expected['after'][index]}"
        )

        if not hasattr(resource, "required") or not result:
            continue

        # Check entity not in permissions if covered by general permission
        global_permissions = {"models", "forms", "users"}
        for permission in global_permissions:
            if (
                Resource(permission).allowed(action, user)
                and Resource(permission).value in resource.required
            ):
                assert resource.hash not in user.permissions, (
                    f"{user.name}[{user.permissions.keys()}] vs {resource.name}[{resource.required}]: {resource.hash} in permissions but "
                    f"should be covered by general {permission} permission"
                )

        # Check redundant children are pruned (exclude RESTRICTED markers)
        resource_action = Action[user.permissions.get(resource.hash)]
        if not any(
            Action[p].implies(resource_action)
            for p in [r for r in resource.required if r != resource.hash]
        ):
            continue
        else:
            shared = set(user.permissions.keys()) & set(resource.required)
            assert len(shared) <= 1, (
                f"{user.name}[{list(user.permissions.keys())}] vs "
                f"{resource.name}[{resource.required}]: "
                f"should share at most 1 permission, found {len(shared)}: {shared}"
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
