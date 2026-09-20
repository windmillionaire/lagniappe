"""Unit tests for UserGroup and PublicGroup permissions."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.cloud import datastore
import pytest

from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch, General, Levels, Site
from lagniappe.core.entities import entity as entity_module
from lagniappe.core.entities import group as group_module
from lagniappe.core.entities.group import PublicGroup, UserGroup
from lagniappe.core.entities.user import User
from testing.utility.test_entities import TestEntities


def _public_group_entity(active=True, public_level=Levels.TRUE.name):
    entity = datastore.Entity(key=datastore.Key("models", "public", project="test"))
    entity.update(
        {
            "type": "group",
            "name": "public",
            "active": active,
            "permissions": {Site.PUBLIC.value: public_level},
        }
    )
    return entity


def _member_user(key, group, public=False):
    page = TestEntities.get("PAGE", {"name": f"{key} Page", "hash": f"{key}-page"})
    user = User(testing=True)
    user._key = key
    user.kind = "user"
    user.name = key
    user.email = f"{key}@example.test"
    user.is_public = public
    user.properties.page._value = page
    user.db["page"] = page.key
    page.user = user
    user.properties.groups._value = [group]
    user.properties.groups._cache_attached_entities()
    user.db["groups"] = [group.key]
    return user


# @matrix permissions user-groups : form-data restricted views
@pytest.mark.unit
def test_group_permissions(get_permissions_test_data):
    """``GroupPermissions.create(form_data)``, ``views`` index, RESTRICTED pruning.

    Entity-level cases that lived under ``test_009c`` (users without groups) are
    covered here for groups—the same ``create_permissions`` / pruning rules apply.
    """
    with patch("lagniappe.core.mixins.permissions.Entities.fetch") as mock_load:
        groups, resources = get_permissions_test_data()
        assert groups and resources
        resource_entities = {r.hash: r for r, _ in resources if hasattr(r, "hash")}

        for group in groups:
            form_data = group.test_spec["form_data"]
            mock_load.return_value = [
                e for e in resource_entities.values() if e.hash in form_data
            ]
            expected = group.test_spec["expected"]

            group.properties.permissions.create(form_data, user=CONFIG.TEST_CURRENT_USER)

            expected_permissions = {
                **expected["permissions"],
                **{key: "RESTRICTED" for key in expected.get("restricted", [])},
            }
            assert group.permissions == expected_permissions
            assert json.loads(group.db.get("permissions", "{}")) == expected_permissions
            assert group.db["views"] == expected["views"]


# @matrix permissions public-groups : active permissions public
@pytest.mark.unit
def test_public_permissions(get_permissions_test_data):
    """Test PublicPermissions.create() sets public key based on active state.

    - Active group: sets public: TRUE
    - Inactive group: sets public: FALSE
    """
    with patch("lagniappe.core.mixins.permissions.Entities.fetch", return_value=[]):
        groups, _ = get_permissions_test_data()
        assert groups
        for group in groups:
            expected = group.test_spec["expected"]
            group.properties.permissions.create(
                group.test_spec["form_data"], user=CONFIG.TEST_CURRENT_USER
            )
            expected_permissions = {
                **expected["permissions"], "forms": "VIEW", "public": expected["public"]
            }
            assert group.permissions == expected_permissions
            assert json.loads(group.db.get("permissions", "{}")) == expected_permissions
            assert group.db["views"] == ["models"]


# @matrix permissions public-groups user-groups : default-denial form-data permission-form
@pytest.mark.unit
def test_general_forms_none_round_trips_for_default_view_permission():
    user = CONFIG.TEST_CURRENT_USER

    with patch("lagniappe.core.mixins.permissions.Entities.fetch") as mock_load:
        mock_load.return_value = []

        group = UserGroup(testing=True)
        group.properties.permissions.create(
            {
                General.MODELS.value: Levels.NONE.name,
                General.FORMS.value: Levels.NONE.name,
            },
            user=user,
        )

    assert group.permissions == {General.FORMS.value: Levels.NONE.name}

    public = PublicGroup(testing=True)
    public.permissions = {General.FORMS.value: Levels.NONE.name}

    form = public.properties.permissions.permissions_form()
    assert form["sections"][General.MODELS.value]["levels"] == ["NONE", "VIEW"]
    assert form["sections"][General.FORMS.value]["levels"] == ["NONE", "VIEW"]
    assert (
        form["sections"][General.FORMS.value]["permission"]["level"]
        == Levels.NONE.name
    )


# @matrix permissions public-groups : default-forms-view explicit-none storage
@pytest.mark.unit
def test_public_permissions_default_forms_view_is_stored():
    user = CONFIG.TEST_CURRENT_USER

    with patch("lagniappe.core.mixins.permissions.Entities.fetch", return_value=[]):
        public = PublicGroup(testing=True)
        public.properties.permissions.create(
            {Site.PUBLIC.value: Levels.TRUE.name},
            user=user,
        )

        assert public.permissions[General.FORMS.value] == Levels.VIEW.name
        assert (
            json.loads(public.db["permissions"])[General.FORMS.value]
            == Levels.VIEW.name
        )

        explicit_none = PublicGroup(testing=True)
        explicit_none.properties.permissions.create(
            {
                Site.PUBLIC.value: Levels.TRUE.name,
                General.FORMS.value: Levels.NONE.name,
            },
            user=user,
        )

    assert explicit_none.permissions[General.FORMS.value] == Levels.NONE.name


# @matrix user-groups : create permissions reserved-name save
@pytest.mark.unit
def test_user_group_create_rejects_public_and_initializes_permissions():
    with pytest.raises(ValueError, match="reserved group name"):
        UserGroup.create("public")

    allocated_key = object()
    with (
        patch.object(
            entity_module.database_utility, "create_key", return_value=allocated_key
        ),
        patch.object(
            group_module.user_groups.GroupPermissions,
            "create",
            autospec=True,
        ) as create_permissions,
    ):
        group = UserGroup.create("Editors")

    assert group.name == "Editors"
    assert group.kind == "group"
    assert group.key is allocated_key
    create_permissions.assert_called_once_with(group.properties.permissions)

    with patch.object(entity_module.Entities, "save") as save:
        group.save()

    save.assert_called_once_with(group)


# @matrix permissions public-groups user-groups : cache-invalidation member-refresh permission-update
@pytest.mark.unit
def test_save_permissions_refreshes_member_users_with_current_group():
    form_data = {General.MODELS.value: Levels.VIEW.name}
    group = UserGroup(testing=True)
    group._key = "refresh-group-key"
    group.kind = "group"
    group.name = "Refresh Group"
    group.db["hash"] = "refresh-group"
    group.permissions = {General.MODELS.value: Levels.VIEW.name}
    group.properties.permissions.create = MagicMock()

    stale_group = UserGroup(testing=True)
    stale_group._key = group.key
    stale_group.kind = "group"
    stale_group.name = "Stale Group"
    stale_group.db["hash"] = group.hash
    stale_group.permissions = {General.MODELS.value: Levels.NONE.name}

    user = _member_user("regular-refresh-user", stale_group)

    def load_regular(*entities, request):
        user.properties.groups.attach({group.key: group})
        return [group, user]

    with (
        patch.object(
            group_module.database_get,
            "users",
            return_value=SimpleNamespace(results=[user]),
        ) as get_users,
        patch.object(group_module.Entities, "fetch", side_effect=load_regular) as load,
        patch.object(group_module.Entities, "save") as save,
    ):
        refreshed = group.save_permissions(form_data)

    get_users.assert_called_once_with(group=group.key, limit=None)
    load.assert_called_once()
    assert load.call_args.args == (group, user)
    save.assert_called_once_with(user, group)
    group.properties.permissions.create.assert_called_once_with(form_data)
    assert refreshed == [user]
    assert user.groups == [group]
    assert user.permissions[General.MODELS.value] == Levels.VIEW.name
    assert user.invalidate_cache is True

    public_form_data = {Site.PUBLIC.value: Levels.TRUE.name}
    public_group = PublicGroup(testing=True)
    public_group._key = "public-refresh-key"
    public_group.kind = "public_group"
    public_group.name = "public"
    public_group.db["hash"] = "public-refresh"
    public_group.active = True
    public_group.permissions = {
        Site.PUBLIC.value: Levels.TRUE.name,
        General.MODELS.value: Levels.VIEW.name,
    }
    public_group.properties.permissions.create = MagicMock()

    stale_public_group = PublicGroup(testing=True)
    stale_public_group._key = public_group.key
    stale_public_group.kind = "public_group"
    stale_public_group.name = "public"
    stale_public_group.db["hash"] = public_group.hash
    stale_public_group.active = True
    stale_public_group.permissions = {
        Site.PUBLIC.value: Levels.TRUE.name,
        General.MODELS.value: Levels.NONE.name,
    }

    public_user = _member_user("public-refresh-user", stale_public_group, public=True)

    def load_public(*entities, request):
        public_user.properties.groups.attach({public_group.key: public_group})
        return [public_group, public_user]

    with (
        patch.object(
            group_module.database_get,
            "users",
            return_value=SimpleNamespace(results=[public_user]),
        ),
        patch.object(
            group_module.Entities,
            "fetch",
            side_effect=load_public,
        ) as load_public_mock,
        patch.object(group_module.Entities, "save") as save_public,
        patch(
            "lagniappe.core.properties.user_permissions.Entities.PUBLIC_GROUP.get",
            return_value=stale_public_group,
        ) as get_public_group,
    ):
        public_group.save_permissions(public_form_data)

    load_public_mock.assert_called_once_with(
        public_group, public_user, request=Fetch.direct()
    )
    save_public.assert_called_once_with(public_user, public_group)
    public_group.properties.permissions.create.assert_called_once_with(public_form_data)
    get_public_group.assert_not_called()
    assert public_user.groups == [public_group]
    assert public_user.permissions[General.MODELS.value] == Levels.VIEW.name
    assert public_user.invalidate_cache is True


# @matrix permissions user-groups : admin unauthenticated
@pytest.mark.unit
def test_group_permissions_require_admin_and_handle_anonymous():
    anonymous = SimpleNamespace(is_authenticated=False, is_owner=False)
    non_owner = SimpleNamespace(is_authenticated=True, is_owner=False)

    group = UserGroup(testing=True)
    group.properties.permissions.create(user=anonymous)
    assert "permissions" not in group.db

    with pytest.raises(PermissionError, match="only site owner"):
        group.properties.permissions.create(user=non_owner)

    public = PublicGroup(testing=True)
    public.properties.permissions.create(user=anonymous)
    assert public.permissions == {
        General.FORMS.value: Levels.VIEW.name,
        Site.PUBLIC.value: Levels.FALSE.name,
    }

    with pytest.raises(PermissionError, match="only site owner"):
        public.properties.permissions.create(user=non_owner)

    admin = SimpleNamespace(is_authenticated=True, is_owner=False, is_admin=True)
    with patch("lagniappe.core.mixins.permissions.Entities.fetch", return_value=[]):
        group.properties.permissions.create({"models": "VIEW"}, user=admin)
        public.properties.permissions.create({"public": "TRUE"}, user=admin)
    assert group.permissions == {"models": "VIEW"}
    assert public.permissions == {"forms": "VIEW", "public": "TRUE"}


# @matrix public-groups : create enabled get permissions
@pytest.mark.unit
def test_public_group_get_create_and_enabled_state():
    existing = _public_group_entity()
    with patch.object(group_module.database_get, "public_group", return_value=existing):
        group = PublicGroup.get()

    assert isinstance(group, PublicGroup)
    assert group.name == "public"
    assert group.properties.permissions.enabled is True

    created = object()
    with patch.object(PublicGroup, "new", return_value=created) as new:
        assert PublicGroup.create() is created
    new.assert_called_once_with("public")

    with (
        patch.object(group_module.database_get, "public_group", return_value=None),
        patch.object(PublicGroup, "create", return_value=created) as create,
    ):
        assert PublicGroup.get() is created
    create.assert_called_once_with()

    inactive = _public_group_entity(active=False, public_level=Levels.TRUE.name)
    public_disabled = _public_group_entity(
        active=True,
        public_level=Levels.FALSE.name,
    )

    with patch.object(group_module.database_get, "public_group", return_value=inactive):
        assert PublicGroup.enabled() is False
    with patch.object(
        group_module.database_get,
        "public_group",
        return_value=public_disabled,
    ):
        assert PublicGroup.enabled() is False
    with patch.object(group_module.database_get, "public_group", return_value=None):
        assert PublicGroup.enabled() is False
