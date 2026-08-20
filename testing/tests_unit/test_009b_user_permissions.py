"""Unit tests for User permissions system."""

import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from google.cloud import datastore
import pytest

from testing.utility.test_entities import TestEntities


def permission_user(*, authenticated=True, owner=False, permissions=None):
    return SimpleNamespace(
        is_authenticated=authenticated,
        is_owner=owner,
        permissions=permissions or {},
    )


# @features permissions
# @dimensions action-lattice resource-gates owner anonymous default-deny aliases
@pytest.mark.unit
def test_resource_allowed_direct_contract():
    """Direct contract for permission action ordering and resource gates."""
    from lagniappe.core.definitions import Action, Resource

    anonymous = permission_user(authenticated=False)
    owner = permission_user(owner=True)
    model_viewer = permission_user(permissions={"models": "VIEW"})
    form_editor = permission_user(permissions={"forms": "EDIT"})
    missing = permission_user()

    assert Action.DELETE.implies(Action.VIEW)
    assert Action.EDIT.implies(Action.EDIT)
    assert not Action.VIEW.implies(Action.EDIT)
    assert not Action.NONE.implies(Action.NONE)

    assert not Resource.MODELS.allowed(Action.VIEW, anonymous)
    assert not Resource.SITE.allowed(Action.VIEW, anonymous)

    assert Resource.SITE.allowed(Action.VIEW, owner)
    assert Resource.USER_GROUPS.allowed(Action.DELETE, owner)
    assert Resource.MODELS.allowed(Action.DELETE, owner)

    assert not Resource.SITE.allowed(Action.VIEW, model_viewer)
    assert Resource.MODELS.allowed(Action.VIEW, model_viewer)
    assert not Resource.MODELS.allowed(Action.EDIT, model_viewer)

    assert Resource.FORMS.allowed(Action.VIEW, form_editor)
    assert Resource.FORMS.allowed(Action.EDIT, form_editor)
    assert not Resource.FORMS.allowed(Action.DELETE, form_editor)

    assert Resource.PROJECT.allowed(Action.VIEW, model_viewer)
    assert Resource["REPORT"] == Resource.MODELS
    assert Resource.REPORT.allowed(Action.VIEW, model_viewer)
    assert not Resource.FORM.allowed(Action.DELETE, form_editor)
    assert Resource.PUBLIC_GROUP.allowed(Action.VIEW, owner)
    assert not Resource.PUBLIC_GROUP.allowed(Action.VIEW, model_viewer)
    assert not Resource.USERS.allowed(Action.VIEW, missing)


# @features permissions cache
# @dimensions stored-permissions fingerprint owner empty-permissions
@pytest.mark.unit
def test_user_permissions_fingerprint_tracks_permissions_and_owner_state():
    viewer = TestEntities.get(
        "USER",
        {
            "name": "Fingerprint Viewer",
            "hash": "fingerprint-viewer",
            "permissions": {"models": "VIEW"},
        },
    )
    expected = hashlib.md5(viewer.db["permissions"].encode("utf-8")).hexdigest()

    assert viewer.permissions_fingerprint == expected

    viewer.permissions = {"models": "EDIT"}
    assert viewer.permissions_fingerprint != expected

    owner = TestEntities.get(
        "USER",
        {"name": "Fingerprint Owner", "hash": "fingerprint-owner", "owner": True},
    )
    owner.db.pop("permissions", None)
    assert owner.permissions_fingerprint == hashlib.md5(b"").hexdigest()


# @features permissions
# @dimensions global-resources resource-gates owner
@pytest.mark.unit
def test_global_resources(get_permissions_test_data):
    """Test has_permission() with Resource enums (global resource access).

    Resource.allowed(user) returns:
    - Owner-only resources (SITE, USER_GROUPS, INGRESS): ALL for site owner only
    - Global resources (MODELS, FORMS, USERS): ALL for site owner, else from ``user.permissions``
    - Instance aliases (PROJECT, TASK, …): same global checks via ``Resource`` mapping
    """
    users, resources = get_permissions_test_data()
    for user in users:
        for index, (resource, action) in enumerate(resources):
            result = user.has_permission(resource, action)
            expected = user.test_spec["expected"][index]
            resource_name = (
                resource.name if hasattr(resource, "name") else resource.hash
            )
            assert result == expected, (
                f"{user.name}: has_permission({resource_name}, {action.name}) = {result}, "
                f"expected {expected}"
            )


# @features permissions
# @dimensions entity-resources requires
@pytest.mark.unit
def test_entity_permissions(get_permissions_test_data):
    """Test has_permission() with Entity instances (requires chain).

    Access is granted if the user has permission on the global marker present in
    ``entity.requires`` (models, forms, users) or a specific required hash.
    """
    users, resources = get_permissions_test_data()
    for user in users:
        for index, (entity, action) in enumerate(resources):
            result = user.has_permission(entity, action)
            expected = user.test_spec["expected"][index]
            assert result == expected, (
                f"{user.name}: has_permission({entity.hash}, {action.name}) = {result}, "
                f"expected {expected}"
            )


# @pairs users:owner users:users-view users:group-view
# @pair users:restriction-independence
@pytest.mark.unit
def test_user_visibility_uses_users_and_group_permissions_without_page_restrictions():
    """A user row is governed by Users/group permissions, not its page or form."""
    from lagniappe.core.definitions import Action

    target = TestEntities.get(
        "USER",
        {
            "name": "Scoped User",
            "hash": "scoped-user",
            "groups": [{"name": "Scoped Group", "hash": "scoped-group"}],
        },
    )
    owner = TestEntities.get(
        "USER",
        {"name": "Owner Viewer", "hash": "owner-viewer", "owner": True},
    )
    global_viewer = TestEntities.get(
        "USER",
        {
            "name": "Global User Viewer",
            "hash": "global-user-viewer",
            "permissions": {"users": "VIEW"},
        },
    )
    group_viewer = TestEntities.get(
        "USER",
        {
            "name": "Group User Viewer",
            "hash": "group-user-viewer",
            "permissions": {"scoped-group": "VIEW"},
        },
    )
    unrelated_viewer = TestEntities.get(
        "USER",
        {
            "name": "Unrelated Viewer",
            "hash": "unrelated-viewer",
            "permissions": {"other-group": "VIEW"},
        },
    )

    def unexpected_restriction_traversal(_viewer):
        raise AssertionError("User visibility traversed page/form restrictions")

    target.restricted_access = unexpected_restriction_traversal

    assert target.allowed(Action.DELETE, owner)
    assert target.allowed(Action.VIEW, global_viewer)
    assert not target.allowed(Action.EDIT, global_viewer)
    assert target.allowed(Action.VIEW, group_viewer)
    assert not target.allowed(Action.VIEW, unrelated_viewer)
    assert not target.allowed(
        Action.VIEW,
        SimpleNamespace(is_authenticated=False),
    )


# @features category permissions users
# @dimensions users-category models-scope
@pytest.mark.unit
def test_users_category_uses_users_scope_not_models_scope():
    """Generic Models permission must not grant access to the reserved Users category."""
    from lagniappe.core.definitions import Action
    from lagniappe.core.entities import Entities
    from testing.utility.test_entities import TestEntities

    reserved = datastore.Entity(
        key=datastore.Key("models", "reserved-users", project="test")
    )
    reserved.update(
        {"type": "users", "name": "Users", "hash": "users", "reserved": True}
    )

    with patch(
        "lagniappe.core.entities.category.database.get.reserved",
        return_value=reserved,
    ) as reserved_get:
        loaded_users_category = Entities.USERS.get()

    viewer = TestEntities.get(
        "USER",
        {
            "name": "Model Creator",
            "hash": "usrmodels",
            "page": {"name": "Model Creator Page", "hash": "pgmodels"},
            "permissions": {"models": "CREATE", "users": "NONE"},
        },
    )
    normal_category = TestEntities.get(
        "CATEGORY", {"name": "Projects", "hash": "projects"}
    )
    users_category = TestEntities.get(
        "USERS", {"name": "Users", "hash": "users", "type": "users"}
    )

    reserved_get.assert_called_once_with("users")
    assert loaded_users_category.kind == "users"
    assert loaded_users_category.required == ["users"]
    assert normal_category.required == ["models", "projects"]
    assert users_category.required == ["users"]
    assert viewer.has_permission(normal_category, Action.VIEW) is True
    assert viewer.has_permission(users_category, Action.VIEW) is False


# @features permissions users
# @dimensions user-page models-scope users-scope
@pytest.mark.unit
def test_user_page_permissions_follow_users_only_or_attached_categories():
    """Users-only pages use Users access; categorized user pages use model/category access."""
    from lagniappe.core.definitions import Action
    from testing.utility.test_entities import TestEntities

    model_creator = TestEntities.get(
        "USER",
        {
            "name": "Model Creator",
            "hash": "usrmodels",
            "page": {"name": "Model Creator Page", "hash": "pgmodels"},
            "permissions": {"models": "CREATE", "users": "NONE"},
        },
    )
    category_viewer = TestEntities.get(
        "USER",
        {
            "name": "Category Viewer",
            "hash": "usrcatview",
            "page": {"name": "Category Viewer Page", "hash": "pgcatview"},
            "permissions": {"catfriends": "VIEW", "users": "NONE"},
        },
    )
    default_user_page = TestEntities.get(
        "PAGE",
        {
            "name": "Default User Page",
            "hash": "pguserdefault",
            "model": {"name": "Users", "hash": "users"},
            "user": {"name": "Default Owner", "hash": "usrdefaultowner"},
        },
    )
    categorized_user_page = TestEntities.get(
        "PAGE",
        {
            "name": "Categorized User Page",
            "hash": "pgusercat",
            "model": {"name": "Users", "hash": "users"},
            "categories": [{"name": "Friends", "hash": "catfriends"}],
            "user": {"name": "Categorized Owner", "hash": "usrcatowner"},
        },
    )

    assert default_user_page.model.kind == "users"
    assert default_user_page.required == ["users", "pguserdefault"]
    assert categorized_user_page.required == [
        "models",
        "users",
        "pgusercat",
        "catfriends",
    ]
    assert model_creator.has_permission(categorized_user_page, Action.VIEW) is True
    assert category_viewer.has_permission(categorized_user_page, Action.VIEW) is True


# @features permissions user-groups
# @dimensions combine-groups highest-permission restricted
@pytest.mark.unit
def test_combine_groups(get_permissions_test_data):
    """Test that combine_group_permissions takes the highest permission level.

    When user is in multiple groups with different permission levels for
    the same resource, they should get the most permissive action.
    """
    from testing.utility.permissions import (
        check_before_permissions,
        check_after_permissions,
        check_user_page_permission,
    )

    with patch("lagniappe.core.mixins.permissions.cache.get_details_by_hash") as mock:
        users, resources = get_permissions_test_data()

        resource_entities = {r.hash: r for r, _ in resources if hasattr(r, "hash")}

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

        mock.side_effect = _details

        for user in users:
            expected = user.test_spec["expected"]

            check_before_permissions(user, resources, expected)

            user.properties.permissions.create()

            check_after_permissions(user, resources, expected)
            check_user_page_permission(user)
