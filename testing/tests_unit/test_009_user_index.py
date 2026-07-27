from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lagniappe.core.definitions import Fetch, Restriction
from testing.utility.test_entities import TestEntities


# @features user-index
# @dimensions table columns
@pytest.mark.unit
def test_user_index(get_test_entities):
    """Test UserTable produces correct column structure for UI.

    UserTable has columns: Name, Email, Groups, LastLogin, Modified.
    Verifies entity.column(field_id) returns correct column_value for each.
    """
    from lagniappe.core.entities.index import UserIndex

    users = get_test_entities()

    # Set properties that need to be set via setter
    for user in users:
        user.name = user.test_spec.get("name")
        if "email" in user.test_spec:
            user.db["email"] = user.test_spec["email"]

    user_index = UserIndex()
    user_index._users = users

    table = user_index.table

    # 5 columns; metadata includes link/parent for the table renderer
    assert len(table.columns) == 5
    column_keys = {
        "field",
        "title",
        "icon",
        "ordering",
        "selected",
        "link",
        "parent",
        "schema",
    }
    for col in table.columns:
        assert column_keys == col.keys()

    # Verify column field order
    expected_fields = ["name", "email", "groups", "last_login", "modified"]
    assert [c["field"] for c in table.columns] == expected_fields

    # All selected by default
    assert table.selected == expected_fields

    # Verify entity.column() returns correct column_value for each user
    for user in users:
        # name - returns entity details dict
        name_col = user.column("name")
        assert name_col.column_value == user.details

        # email - returns email string
        email_col = user.column("email")
        assert email_col.column_value == user.test_spec.get("email")

        # groups - returns list of group details
        groups_col = user.column("groups")
        expected_groups = [g.reference_details for g in user.groups]
        assert groups_col.column_value == expected_groups

        # last_login - column exists (value tested elsewhere due to timezone context)
        assert user.column("last_login") is not None

        # modified - column exists (value tested elsewhere due to timezone context)
        assert user.column("modified") is not None


# @features user-index
# @dimensions pagination restrictions groups public-group
@pytest.mark.unit
def test_user_index_loads_users_groups_public_group_and_append_cursor():
    """UserIndex loads restricted users/groups and public-group state."""
    from lagniappe.core.entities.index import UserIndex

    index_user = SimpleNamespace(
        properties=SimpleNamespace(restrictions=SimpleNamespace(users=["grp001"]))
    )
    visible_user = TestEntities.get(
        "USER",
        {
            "name": "Visible User",
            "hash": "usr001",
            "page": {"name": "Visible Page", "hash": "pgusr001"},
        },
    )
    hidden_user = TestEntities.get(
        "USER",
        {
            "name": "Hidden User",
            "hash": "usr002",
            "page": {"name": "Hidden Page", "hash": "pgusr002"},
        },
    )
    allowed_group = TestEntities.get(
        "USER_GROUP",
        {"name": "Allowed Group", "hash": "grp001"},
    )
    denied_group = TestEntities.get(
        "USER_GROUP",
        {"name": "Denied Group", "hash": "grp002"},
    )
    public_group = TestEntities.get(
        "PUBLIC_GROUP",
        {"name": "public", "hash": "public", "public": True},
    )
    visible_user.allowed = lambda action: True
    hidden_user.allowed = lambda action: False
    allowed_group.allowed = lambda action: True
    denied_group.allowed = lambda action: False

    def fake_url_for(endpoint, **kwargs):
        pieces = [endpoint]
        pieces.extend(f"{key}={value}" for key, value in sorted(kwargs.items()))
        return "/" + "&".join(pieces)

    with patch("lagniappe.core.entities.index.url_for", side_effect=fake_url_for):
        with patch(
            "lagniappe.core.entities.index.database.get.users",
            return_value=SimpleNamespace(
                results=["usr-key-1", "usr-key-2"], next_cursor="next-users"
            ),
        ) as user_query:
            with patch(
                "lagniappe.core.entities.index.database.get.groups",
                return_value=["grp-key-1", "grp-key-2"],
            ) as group_query:
                with patch(
                    "lagniappe.core.entities.index.cache.get_details_by_hash",
                    return_value={
                        "grp001": {"kind": "group", "id": "grp-key-1"},
                        "usr001": {"kind": "user", "id": "usr-key-1"},
                    },
                ) as details:
                    with patch(
                        "lagniappe.core.entities.index.Entities.fetch",
                        side_effect=[
                            [visible_user, hidden_user],
                            [allowed_group, denied_group],
                        ],
                    ) as load:
                        with patch(
                            "lagniappe.core.entities.index.Entities.PUBLIC_GROUP.get",
                            return_value=public_group,
                        ) as get_public_group:
                            index = UserIndex(
                                cursor="users-cursor",
                                limit=5,
                                user=index_user,
                            )

                            users = index.users
                            groups = index.groups
                            public = index.public_group

    user_query.assert_called_once_with(
        start_cursor="users-cursor",
        hashes=["grp001"],
        limit=5,
    )
    group_query.assert_called_once_with(hashes=["grp-key-1"])
    details.assert_called_once_with(["grp001"])
    assert load.call_args_list[0].args == ("usr-key-1", "usr-key-2")
    assert load.call_args_list[1].args == ("grp-key-1", "grp-key-2")
    assert load.call_args_list[0].kwargs == {"request": Fetch.direct()}
    assert load.call_args_list[1].kwargs == {"request": Fetch.direct()}
    get_public_group.assert_called_once_with()
    assert users == [visible_user]
    assert groups == [allowed_group]
    assert public is public_group
    assert index.cursor == "next-users"
    assert index.append == "/users.rows&cursor=next-users"
    assert index.users is users
    assert index.groups is groups
    assert index.public_group is public_group


# @features user-index
# @dimensions regular-mode public-users mode
@pytest.mark.unit
def test_user_index_regular_mode_excludes_public_users():
    """Default user index mode keeps public users out of the regular table."""
    from lagniappe.core.entities.index import UserIndex

    index_user = SimpleNamespace(
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(users=Restriction.UNRESTRICTED)
        )
    )
    regular_user = TestEntities.get(
        "USER",
        {
            "name": "Regular User",
            "hash": "usr003",
            "page": {"name": "Regular Page", "hash": "pgusr003"},
        },
    )
    public_user = TestEntities.get(
        "USER",
        {
            "name": "Public User",
            "hash": "usr004",
            "public": True,
            "page": {"name": "Public Page", "hash": "pgusr004"},
        },
    )
    regular_user.allowed = lambda action: True
    public_user.allowed = lambda action: True

    def fake_url_for(endpoint, **kwargs):
        pieces = [endpoint]
        pieces.extend(f"{key}={value}" for key, value in sorted(kwargs.items()))
        return "/" + "&".join(pieces)

    with patch("lagniappe.core.entities.index.url_for", side_effect=fake_url_for):
        with patch(
            "lagniappe.core.entities.index.database.get.users",
            return_value=SimpleNamespace(
                results=["usr-key-3", "usr-key-4"], next_cursor="next-regular"
            ),
        ) as user_query:
            with patch(
                "lagniappe.core.entities.index.Entities.fetch",
                return_value=[regular_user, public_user],
            ):
                index = UserIndex(user=index_user)
                users = index.users

    user_query.assert_called_once_with(
        start_cursor=None,
        hashes=Restriction.UNRESTRICTED,
        limit=25,
    )
    assert index.mode == "regular"
    assert users == [regular_user]
    assert index.append == "/users.rows&cursor=next-regular"


# @features user-index public-users
# @dimensions public-mode pagination mode
@pytest.mark.unit
def test_user_index_public_mode_loads_public_group_users_and_preserves_append_mode():
    """Public user index mode queries the public group and preserves mode in append."""
    from lagniappe.core.entities.index import UserIndex

    index_user = SimpleNamespace(
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(users=Restriction.UNRESTRICTED)
        )
    )
    public_group = TestEntities.get(
        "PUBLIC_GROUP",
        {"name": "public", "hash": "pub001", "public": True},
    )
    public_user = TestEntities.get(
        "USER",
        {
            "name": "Public Visible",
            "hash": "usr005",
            "public": True,
            "page": {"name": "Public Visible Page", "hash": "pgusr005"},
        },
    )
    regular_user = TestEntities.get(
        "USER",
        {
            "name": "Regular Hidden",
            "hash": "usr006",
            "page": {"name": "Regular Hidden Page", "hash": "pgusr006"},
        },
    )
    hidden_public_user = TestEntities.get(
        "USER",
        {
            "name": "Public Hidden",
            "hash": "usr007",
            "public": True,
            "page": {"name": "Public Hidden Page", "hash": "pgusr007"},
        },
    )
    public_user.allowed = lambda action: True
    regular_user.allowed = lambda action: True
    hidden_public_user.allowed = lambda action: False

    def fake_url_for(endpoint, **kwargs):
        pieces = [endpoint]
        pieces.extend(f"{key}={value}" for key, value in sorted(kwargs.items()))
        return "/" + "&".join(pieces)

    with patch("lagniappe.core.entities.index.url_for", side_effect=fake_url_for):
        with patch(
            "lagniappe.core.entities.index.Entities.PUBLIC_GROUP.enabled",
            return_value=True,
        ) as enabled:
            with patch(
                "lagniappe.core.entities.index.Entities.PUBLIC_GROUP.get",
                return_value=public_group,
            ) as get_public_group:
                with patch(
                    "lagniappe.core.entities.index.database.get.users",
                    return_value=SimpleNamespace(
                        results=["usr-key-5", "usr-key-6", "usr-key-7"],
                        next_cursor="next-public",
                    ),
                ) as user_query:
                    with patch(
                        "lagniappe.core.entities.index.Entities.fetch",
                        return_value=[public_user, regular_user, hidden_public_user],
                    ):
                        index = UserIndex(
                            mode="public",
                            cursor="public-cursor",
                            limit=5,
                            user=index_user,
                        )
                        users = index.users

    enabled.assert_called_once_with()
    get_public_group.assert_called_once_with()
    user_query.assert_called_once_with(
        start_cursor="public-cursor", group=public_group.key, limit=5
    )
    assert index.mode == "public"
    assert users == [public_user]
    assert index.append == "/users.rows&cursor=next-public&mode=public"


# @features user-index public-users
# @dimensions public-mode public-users disabled enabled
@pytest.mark.unit
def test_user_index_public_mode_returns_empty_when_public_users_disabled():
    """Public user index mode is empty when public login is not enabled."""
    from lagniappe.core.entities.index import UserIndex

    index_user = SimpleNamespace(
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(users=Restriction.UNRESTRICTED)
        )
    )

    with patch(
        "lagniappe.core.entities.index.Entities.PUBLIC_GROUP.enabled",
        return_value=False,
    ) as enabled:
        with patch(
            "lagniappe.core.entities.index.database.get.users",
        ) as user_query:
            index = UserIndex(mode="public", user=index_user)
            users = index.users

    enabled.assert_called_once_with()
    user_query.assert_not_called()
    assert users == []
    assert index.public_users_enabled is False
