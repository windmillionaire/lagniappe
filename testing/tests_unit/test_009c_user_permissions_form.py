"""Unit tests for user permission map from form data (no groups).

Production users normally inherit permissions from groups; this covers the
fallback path when a user has no groups: ``UserPermissions.create(form_data)``
via ``create_permissions`` (e.g. migration or edge cases).

Rich entity-level and RESTRICTED pruning cases live under ``test_009e_user_groups``.
"""

from unittest.mock import patch

import pytest

from testing.utility.permissions import (
    check_after_permissions,
    check_user_page_permission,
)


# @matrix permissions : form-data no-groups restricted
@pytest.mark.unit
def test_form_permissions(get_permissions_test_data):
    """Empty form vs general models:VIEW for a user with no groups."""
    with (
        patch("lagniappe.core.mixins.permissions.Entities.fetch") as mock_load,
        patch(
            "lagniappe.core.mixins.permissions.cache.get_details_by_hash"
        ) as mock_cache,
    ):
        users, resources = get_permissions_test_data()

        resource_entities = {r.hash: r for r, _ in resources if hasattr(r, "hash")}

        for user in users:
            form_data = user.test_spec.get("form_data", {})

            # Mock Entities.fetch to return entities matching form_data keys
            mock_load.return_value = [
                e for e in resource_entities.values() if e.hash in form_data
            ]

            def _details(hashes):
                if not hashes:
                    return {}
                out = {}
                for h in hashes:
                    if h in resource_entities:
                        out[h] = {"requires": resource_entities[h].required}
                    else:
                        out[h] = {"requires": []}
                return out

            mock_cache.side_effect = _details

            expected = user.test_spec["expected"]

            user.properties.permissions.create(form_data)

            check_after_permissions(user, resources, expected)
            check_user_page_permission(user)

            # Check expected RESTRICTED entries
            for hash in expected.get("restricted", []):
                assert user.permissions.get(hash) == "RESTRICTED", (
                    f"{user.name}: {hash} should be RESTRICTED, got {user.permissions.get(hash)}"
                )
