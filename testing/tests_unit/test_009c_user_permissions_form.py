"""Unit tests for user permission map from form data (no groups).

Production users normally inherit permissions from groups; this covers the
fallback path when a user has no groups: ``UserPermissions.create(form_data)``
via ``create_permissions`` (e.g. migration or edge cases).

Rich entity-level and RESTRICTED pruning cases live under ``test_009e_user_groups``.
"""

import json
from unittest.mock import patch

import pytest

from testing.utility.permissions import (
    check_after_permissions,
    check_user_page_permission,
)


# @matrix permissions : form-data no-groups restricted
@pytest.mark.unit
def test_form_permissions(get_permissions_test_data):
    """No-group users receive explicit grants, restrictions, and own-page EDIT."""
    with patch("lagniappe.core.mixins.permissions.Entities.fetch") as mock_load:
        users, resources = get_permissions_test_data()
        assert users and resources
        resource_entities = {r.hash: r for r, _ in resources if hasattr(r, "hash")}

        for user in users:
            form_data = user.test_spec["form_data"]
            mock_load.return_value = [
                e for e in resource_entities.values() if e.hash in form_data
            ]
            expected = user.test_spec["expected"]

            user.properties.permissions.create(form_data)

            assert user.permissions == expected["permissions"]
            assert json.loads(user.db["permissions"]) == expected["permissions"]
            check_after_permissions(user, resources, expected)
            check_user_page_permission(user)
