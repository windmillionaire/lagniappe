"""Unit tests for User entity properties."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from google.cloud.datastore import Entity, Key
import pytest

from lagniappe.core.definitions import Fetch, General, Levels
from lagniappe.core.entities.page import Page
from lagniappe.core.tools import database
from lagniappe.core.tools.database.defaults import DEFAULT_USER_SCHEMA
from lagniappe.core.entities.user import User
from lagniappe.core.properties.user_related import Starred

from testing.utility.test_entities import TestEntities


# @features user
# @dimensions email column sort
@pytest.mark.unit
def test_user_email(get_test_entities):
    """Test Email property with ColumnMixin.

    Email has special behavior:
    - sort_value returns True if email exists, False otherwise
    - column_value returns the email string
    """
    for user in get_test_entities():
        test_value = user.test_spec.get("email")
        user.email = test_value

        # property value
        assert user.email == test_value
        assert user.properties.email.value == test_value

        # ColumnMixin - column_value is the email
        assert user.column("email").column_value == test_value

        # sort_value is True if email exists, False otherwise
        expected_sort = True if test_value else False
        assert user.properties.email.sort_value == expected_sort


# @features user
# @dimensions last-login date column
@pytest.mark.unit
def test_user_last_login(get_test_entities):
    """Test LastLogin property with DateMixin, ColumnMixin.

    LastLogin stores datetime in UTC but displays in user timezone.
    """
    for user in get_test_entities():
        tz_name = user.test_spec.get("timezone", "America/Chicago")
        test_tz = ZoneInfo(tz_name)

        with patch("lagniappe.core.tools.dates.user_timezone", return_value=test_tz):
            # Set a datetime in UTC
            utc_dt = datetime(2024, 6, 15, 19, 30, 0, tzinfo=timezone.utc)
            user.last_login = utc_dt

            # property value - stored in UTC
            assert user.last_login == utc_dt
            assert user.properties.last_login.value == utc_dt

            # ColumnMixin - column_value converts to user timezone
            column_val = user.column("last_login").column_value
            assert column_val == utc_dt.astimezone(test_tz)


# @features user cache
# @dimensions invalidation test-user
@pytest.mark.unit
def test_user_invalidate_cache(get_test_entities):
    """Test InvalidateCache property.

    Test users follow the same invalidation flag semantics as normal users.
    """
    for user in get_test_entities():
        user.is_test_user = True
        user.invalidate_cache = True
        assert user.invalidate_cache is True
        assert user.db["invalidate_cache"] is True

        user.is_test_user = False
        assert user.invalidate_cache is True

        user.invalidate_cache = False
        assert user.invalidate_cache is False


# @features user
# @dimensions public
@pytest.mark.unit
def test_user_is_public(get_test_entities):
    """Test IsPublic property with FilterMixin.

    IsPublic stores boolean in db["public"].
    """
    for user in get_test_entities():
        # Test setting to True
        user.is_public = True
        assert user.is_public is True
        assert user.properties.is_public.value is True
        assert user.db["public"] is True

        # Test setting to False
        user.is_public = False
        assert user.is_public is False
        assert user.properties.is_public.value is False

        with pytest.raises(TypeError, match="public must be a boolean"):
            user.is_public = "yes"


# @features user
# @dimensions owner property
@pytest.mark.unit
def test_user_is_owner(get_test_entities):
    """Test IsOwner property.

    IsOwner stores boolean in db["owner"].
    """
    for user in get_test_entities():
        # Test setting to True
        user.is_owner = True
        assert user.is_owner is True
        assert user.properties.is_owner.value is True
        assert user.db["owner"] is True

        # Test setting to False
        user.is_owner = False
        assert user.is_owner is False
        assert user.properties.is_owner.value is False


# @features user
# @dimensions profile-photo default-image asset-lifecycle google-download
@pytest.mark.unit
def test_user_profile_photo_value_asset_lifecycle_and_google_download():
    """ProfilePhoto handles fallback image, asset save/delete, and Google import."""
    user = User(testing=True)
    user.save_asset = MagicMock(return_value=SimpleNamespace(url="/saved-photo.png"))
    user.delete_asset = MagicMock()

    assert user.photo == "/images/anonymous.png"

    user.photo = b"photo-bytes"

    user.save_asset.assert_called_once_with(b"photo-bytes", "photo", "image")
    assert user.photo == "/saved-photo.png"

    user.photo = None

    user.delete_asset.assert_called_once_with("photo")
    assert user.photo == "/images/anonymous.png"

    user.db["photo"] = "https://example.test/google-photo.jpg"
    with patch(
        "lagniappe.core.properties.user_entity.utility.download_image",
        return_value={"success": False},
    ) as download:
        user.properties.photo.save_google_photo()

    download.assert_called_once_with("https://example.test/google-photo.jpg")
    assert user.save_asset.call_count == 1

    with patch(
        "lagniappe.core.properties.user_entity.utility.download_image",
        return_value={"success": True, "file": b"downloaded-photo"},
    ):
        user.properties.photo.save_google_photo()

    assert user.save_asset.call_args.args == (b"downloaded-photo", "photo", "image")


# @features user-groups
# @dimensions membership-change relation-storage permission-recalc
@pytest.mark.unit
def test_user_groups_membership_changes_recalculate_permissions():
    """User group changes persist keys and recalculate permissions once per change."""
    user = User(testing=True)
    group_one = TestEntities.get("USER_GROUP", {"name": "One", "hash": "grp009a"})
    group_two = TestEntities.get("USER_GROUP", {"name": "Two", "hash": "grp009b"})
    create_permissions = MagicMock()
    user.properties.permissions.create = create_permissions

    user.groups = [group_one]

    assert user.groups == [group_one]
    assert user.db["groups"] == [group_one.key]
    create_permissions.assert_called_once_with()

    user.groups = [group_one]

    create_permissions.assert_called_once_with()

    user.properties.groups.add(group_two)

    assert user.groups == [group_two, group_one]
    assert user.db["groups"] == [group_two.key, group_one.key]
    assert create_permissions.call_count == 2

    user.properties.groups.add(group_two)

    assert user.groups == [group_two, group_one]
    assert create_permissions.call_count == 2


# @features user-groups
# @dimensions relation-storage validation
@pytest.mark.unit
def test_user_groups_reject_invalid_relation_inputs():
    user = User(testing=True)
    user.properties.permissions.create = MagicMock()

    with pytest.raises(TypeError, match="Value must be a list"):
        user.groups = {}

    with pytest.raises(ValueError, match="Value must have a key"):
        user.groups = [SimpleNamespace()]

    with pytest.raises(ValueError, match="Value must have a key"):
        user.properties.groups.add(SimpleNamespace())

    with pytest.raises(ValueError, match="Value must have a key"):
        user.properties.groups.remove(SimpleNamespace())


# @features user-groups
# @dimensions public-user public-group-only sync
@pytest.mark.unit
def test_public_user_groups_force_public_group_only():
    user = User(testing=True)
    normal_group = TestEntities.get(
        "USER_GROUP",
        {"name": "Editors", "hash": "grp009c"},
    )
    public_group = TestEntities.get(
        "PUBLIC_GROUP",
        {"name": "public", "hash": "pub009a"},
    )
    create_permissions = MagicMock()
    user.properties.permissions.create = create_permissions

    with patch(
        "lagniappe.core.properties.user_related.Entities.PUBLIC_GROUP.get",
        return_value=public_group,
    ):
        user.is_public = True
        user.groups = [normal_group]

        assert user.groups == [public_group]
        assert user.db["groups"] == [public_group.key]
        create_permissions.assert_called_once_with()

        user.properties.groups.add(normal_group)

        assert user.groups == [public_group]
        assert user.db["groups"] == [public_group.key]
        create_permissions.assert_called_once_with()

        user.properties.groups._value = [normal_group]
        user.db["groups"] = [normal_group.key]

        assert user.groups == [public_group]
        assert user.db["groups"] == [public_group.key]


# @features public-users permissions
# @dimensions public-group-defaults own-page no-group-mutation
@pytest.mark.unit
def test_public_user_permissions_inherit_public_group_defaults_without_mutating_group():
    page = TestEntities.get(
        "PAGE",
        {"name": "Public User Page", "hash": "pgpubperm"},
    )
    public_group = TestEntities.get(
        "PUBLIC_GROUP",
        {
            "name": "public",
            "hash": "pubperm",
            "permissions": {"public": "TRUE"},
        },
    )
    user = User(testing=True)
    user.db.update({"name": "Public User", "email": "public@example.test"})
    user.is_public = True
    user.properties.page._value = page
    user.db["page"] = page.key
    user.properties.groups._value = [public_group]
    user.db["groups"] = [public_group.key]

    with patch(
        "lagniappe.core.properties.user_permissions.Entities.PUBLIC_GROUP.get",
        return_value=public_group,
    ):
        user.properties.permissions.create()

    assert user.permissions[General.FORMS.value] == Levels.VIEW.name
    assert user.permissions[page.hash] == Levels.EDIT.name
    assert page.hash not in public_group.permissions
    assert page.hash not in public_group.db["permissions"]


# @pairs user-settings:email-edit user-settings:ai-access user-settings:owner-own-page
# @pairs user-settings:owner-other-page user-settings:page-preservation
# @pair user-settings:page-reassign
# @pair permissions:permission-recalc
@pytest.mark.unit
def test_page_update_user_authorization_rules():
    group = TestEntities.get("USER_GROUP", {"name": "Editors", "hash": "grp009u"})
    users_model = TestEntities.get(
        "USERS", {"name": "Users", "hash": "users", "type": "users"}
    )

    owner_page = Page(testing=True)
    owner_page._key = "owner-page"
    owner_page.model = users_model
    owner = User(testing=True)
    owner._key = "owner-user"
    owner.name = "Owner"
    owner.email = "owner@example.test"
    owner.is_owner = True
    owner.page = owner_page
    owner.properties.groups._value = [group]

    owner_page.user = owner
    owner_page.update_user(
        {
            "name": "Owner Renamed",
            "email": "owner-hacked@example.test",
            "groups": [],
            "ai_access": "NONE",
        },
        user=owner,
    )

    assert owner.name == "Owner Renamed"
    assert owner.email == "owner@example.test"
    assert owner.groups == [group]
    assert owner.ai_access == "NONE"

    other_page = Page(testing=True)
    other_page._key = "other-page"
    other_page.model = users_model
    other_user = User(testing=True)
    other_user._key = "other-user"
    other_user.name = "Other User"
    other_user.email = "other@example.test"
    other_user.page = other_page
    other_user.properties.permissions.create = MagicMock()
    other_page.user = other_user

    other_page.update_user(
        {
            "name": "Other Renamed",
            "email": "other-updated@example.test",
            "groups": [group],
            "ai_access": "ASK",
        },
        user=owner,
    )

    assert other_user.name == "Other Renamed"
    assert other_user.email == "other-updated@example.test"
    assert other_user.groups == [group]
    assert other_user.ai_access == "ASK"
    assert other_user.page is other_page

    other_user.properties.permissions.create.reset_mock()
    reassigned_page = Page(testing=True)
    reassigned_page._key = "reassigned-page"
    reassigned_page.model = users_model
    uncategorized = TestEntities.get(
        "CATEGORY",
        {"name": "Uncategorized", "hash": "uncategorized-reassign"},
    )
    with (
        patch(
            "lagniappe.core.entities.page.Entities.USERS.get",
            return_value=users_model,
        ),
        patch(
            "lagniappe.core.entities.page.Entities.CATEGORY.get_uncategorized_pages",
            return_value=uncategorized,
        ),
    ):
        other_page.update_user(
            {
                "name": other_user.name,
                "reassign-page": reassigned_page,
            },
            user=owner,
        )

    assert other_user.page is reassigned_page
    assert reassigned_page.user is other_user
    assert other_page.user is None
    other_user.properties.permissions.create.assert_called_once_with()

    public_page = Page(testing=True)
    public_page._key = "public-page"
    public_page.model = users_model
    public_user = User(testing=True)
    public_user._key = "public-user"
    public_user.name = "Public User"
    public_user.email = "public@example.test"
    public_user.is_public = True
    public_user.page = public_page
    public_page.user = public_user

    public_page.update_user(
        {
            "name": "Public Renamed",
            "email": "public-hacked@example.test",
        },
        user=public_user,
    )

    assert public_user.name == "Public Renamed"
    assert public_user.email == "public@example.test"
    assert public_user.ai_access == "NONE"

    with pytest.raises(PermissionError, match="Only the owner"):
        public_page.update_user(
            {
                "name": "Forged Public Name",
                "ai_access": "CREATE",
            },
            user=public_user,
        )
    assert public_user.name == "Public Renamed"
    assert public_user.ai_access == "NONE"

    public_page.update_user(
        {
            "name": "Public Owner View",
            "email": "public-owner@example.test",
            "ai_access": "CREATE",
        },
        user=owner,
    )

    assert public_user.name == "Public Owner View"
    assert public_user.ai_access == "CREATE"
    assert public_user.email == "public-owner@example.test"
    assert public_user.page is public_page


# @features user-settings
# @dimensions default-form email-canonical submission-preservation
@pytest.mark.unit
def test_user_page_default_form_submission_keeps_email_on_user():
    users_model = TestEntities.get(
        "USERS",
        {"name": "Users", "hash": "users", "type": "users", "reserved": True},
    )
    default_form = TestEntities.get(
        "FORM",
        {"name": "User", "hash": "default-user-form", "reserved": True},
    )
    default_form.schema = DEFAULT_USER_SCHEMA

    page = Page(testing=True)
    page._key = "default-user-page"
    page.db["hash"] = "default-user-page"
    page.model = users_model
    page.form = default_form

    user = User(testing=True)
    user._key = "default-user"
    user.name = "Default User"
    user.email = "default@example.test"
    user.page = page

    page.form_submission({"name": "Default User Updated"})

    submission = json.loads(page.db["submission"])
    assert user.email == "default@example.test"
    assert submission["email"] == "default@example.test"

    user.email = None
    page.form_submission(
        {"name": "Default User Updated", "email": "submitted@example.test"}
    )

    assert user.email == "submitted@example.test"

    custom_form = TestEntities.get(
        "FORM", {"name": "Custom User Profile", "hash": "custom-user-form"}
    )
    custom_form.schema = DEFAULT_USER_SCHEMA
    page.form = custom_form
    user.email = "canonical@example.test"

    page.form_submission(
        {"name": "Custom User Profile", "email": "form-only@example.test"}
    )

    submission = json.loads(page.db["submission"])
    assert user.email == "canonical@example.test"
    assert submission["email"] == "form-only@example.test"


# @features user public-users
# @dimensions personal-page auto-create lazy-load owner-link public-user limited-attrs
@pytest.mark.unit
def test_user_page_auto_create_lazy_load_and_owner_link():
    """UserPage auto-creates missing pages and links loaded pages back to the user."""
    user = User(testing=True)
    user._key = "usr009page"
    user.name = "Page Owner"
    model = TestEntities.get(
        "USERS", {"name": "Users", "hash": "users", "type": "users"}
    )
    created_page = TestEntities.get("PAGE", {"name": "Page Owner", "hash": "pg009a"})

    with (
        patch(
            "lagniappe.core.properties.user_related.Entities.USERS.get",
            return_value=model,
        ) as get_model,
        patch(
            "lagniappe.core.properties.user_related.Entities.PAGE.create",
            return_value=created_page,
        ) as create_page,
    ):
        user.page = None

    get_model.assert_called_once_with()
    create_page.assert_called_once_with(
        {"model": model, "user": user, "name": "Page Owner"}
    )
    assert user.page is created_page
    assert user.db["page"] == created_page.key
    assert created_page.user is user
    assert created_page.model is model

    public_user = User(testing=True)
    public_user._key = "usr009publicpage"
    public_user.name = "Public Page Owner"
    public_user.is_public = True
    public_page = TestEntities.get(
        "PAGE", {"name": "Public Page Owner", "hash": "pg009public"}
    )

    with (
        patch(
            "lagniappe.core.properties.user_related.Entities.USERS.get",
            return_value=model,
        ),
        patch(
            "lagniappe.core.properties.user_related.Entities.PAGE.create",
            return_value=public_page,
        ) as create_public_page,
    ):
        public_user.page = None

    public_page_data = create_public_page.call_args.args[0]
    assert set(public_page_data["attributes"]) == {"tasks", "document", "notes"}
    assert "photo" not in public_page_data["attributes"]
    assert "files" not in public_page_data["attributes"]
    assert public_user.page is public_page
    assert public_page.user is public_user

    existing_user = User(testing=True)
    existing_user._key = "usr009existing"
    existing_user.name = "Existing Page Owner"
    friends = TestEntities.get("CATEGORY", {"name": "Friends", "hash": "friends"})
    peers = TestEntities.get("CATEGORY", {"name": "Peers", "hash": "peers"})
    existing_page = TestEntities.get("PAGE", {"name": "Existing", "hash": "pg009c"})
    existing_page.model = friends
    existing_page.categories = [friends, peers]

    with patch(
        "lagniappe.core.properties.user_related.Entities.USERS.get",
        return_value=model,
    ):
        existing_user.page = existing_page

    assert existing_page.user is existing_user
    assert existing_page.model is model
    assert [category.hash for category in existing_page.categories] == [
        "friends",
        "peers",
    ]
    assert existing_page.db["categories"] == [friends.key, peers.key]

    loaded_user = User(testing=True)
    loaded_user._key = "usr009loaded"
    loaded_user.db["page"] = "stored-page-key"
    loaded_page = TestEntities.get("PAGE", {"name": "Loaded Page", "hash": "pg009b"})

    with patch(
        "lagniappe.core.properties.user_related.Entities.fetch_one",
        return_value=loaded_page,
    ) as get_page:
        page = loaded_user.page

    get_page.assert_called_once_with("stored-page-key", request=Fetch.direct())
    assert page is loaded_page
    assert loaded_page.user is loaded_user


# @features user
# @dimensions personal-page validation
@pytest.mark.unit
def test_user_page_missing_key_raises_runtime_error():
    user = User(testing=True)

    with pytest.raises(RuntimeError, match="User page key not found"):
        _ = user.page


# @features starred
# @dimensions stale-cleanup
@pytest.mark.unit
def test_user_starred_cleanup_removes_stale_keys():
    user = SimpleNamespace(
        db={"starred": ["keep-before", "stale-page", "keep-after", "stale-project"]}
    )
    starred = Starred(entity=user, user=object())

    starred.delete_starred_keys(["stale-page", "stale-project"])

    assert user.db["starred"] == ["keep-before", "keep-after"]


# @features user
# @dimensions entity-lifecycle create owner page groups save load search-cache page-canonical
@pytest.mark.unit
def test_user_entity_create_save_load_owner_page_and_groups():
    """User create/save/load handles owner, page, groups, photo import, and reuse."""
    with patch("lagniappe.core.entities.user.database.get.user") as get_user:
        with pytest.raises(ValueError, match="name is required"):
            User.create({"email": "missing-name@example.com"})
    get_user.assert_not_called()

    with patch("lagniappe.core.entities.user.database.get.user") as get_user:
        with pytest.raises(ValueError, match="email is required"):
            User.create({"name": "Missing Email"})
    get_user.assert_not_called()

    existing_key = Key("users", "existing", project="test")
    existing = Entity(existing_key)
    existing.update({"type": "user", "email": "exists@example.com", "page": "pg009c"})

    with patch(
        "lagniappe.core.entities.user.database.get.user",
        return_value=existing,
    ):
        with patch("lagniappe.core.entities.entity.database.create_key") as create_key:
            reused = User.create(
                {"name": "Existing User", "email": "exists@example.com"}
            )

    create_key.assert_not_called()
    assert isinstance(reused, User)
    assert reused.db is existing

    page = TestEntities.get(
        "PAGE",
        {
            "name": "Admin Page",
            "hash": "pg009d",
            "model": {"name": "Admin Page Category", "hash": "cat009user"},
        },
    )
    page_category = page.categories[0]
    users_model = TestEntities.get(
        "USERS", {"name": "Users", "hash": "users", "type": "users"}
    )
    group = TestEntities.get("USER_GROUP", {"name": "Editors", "hash": "grp009c"})
    new_key = Key("users", "new", project="test")
    new_entity = Entity(new_key)

    with patch(
        "lagniappe.core.entities.user.CONFIG",
        SimpleNamespace(ADMIN_EMAIL="admin@example.com"),
    ):
        with patch(
            "lagniappe.core.entities.user.database.get.user",
            return_value=None,
        ):
            with patch(
                "lagniappe.core.entities.entity.database.create_key",
                return_value=new_key,
            ):
                with patch(
                    "lagniappe.core.entities.entity.database.get.entity",
                    return_value=None,
                ):
                    with patch(
                        "lagniappe.core.entities.entity.database.create_entity",
                        return_value=new_entity,
                    ):
                        with patch(
                            "lagniappe.core.properties.user_permissions.UserPermissions.create"
                        ) as create_permissions:
                            with patch(
                                "lagniappe.core.properties.user_related.Entities.USERS.get",
                                return_value=users_model,
                            ):
                                created = User.create(
                                    {
                                        "name": "Admin User",
                                        "email": "admin@example.com",
                                        "page": page,
                                        "picture": "https://example.test/photo.jpg",
                                        "groups": [group],
                                        "is_public": False,
                                        "test_user": True,
                                    }
                                )

    assert created.kind == "user"
    assert created.name == "Admin User"
    assert created.email == "admin@example.com"
    assert created.page is page
    assert page.user is created
    assert page.model is users_model
    assert [category.hash for category in page.categories] == [
        page_category.hash
    ] == ["cat009user"]
    assert created.db["photo"] == "https://example.test/photo.jpg"
    assert created.is_owner is True
    assert created.ai_access == "CREATE"
    assert created.is_public is False
    assert created.is_test_user is True
    assert created.groups == [group]
    assert created.db["groups"] == [group.key]
    assert created.urlsafe_key == database.get.urlsafe_key(created.key)
    assert created.urlsafe_key != page.urlsafe_key
    assert created.details["id"] == page.urlsafe_key
    assert created.to_cache == {}
    assert page.to_cache["id"] == page.urlsafe_key
    assert page.to_cache["kind"] == "user"
    assert page.to_cache["details_key"] == page.hash
    assert "details" not in page.to_cache
    assert create_permissions.called

    created.get_asset = MagicMock(return_value=None)
    created.properties.photo.save_google_photo = MagicMock()
    with patch("lagniappe.core.entities.entity.Entities.save") as save:
        created.save()

    created.properties.photo.save_google_photo.assert_called_once_with()
    save.assert_called_once_with(created)

    loaded = TestEntities.get(
        "USER",
        {
            "name": "Loaded User",
            "hash": "usr009d",
            "email": "loaded@example.com",
            "page": {"name": "Loaded Page", "hash": "pg009e"},
        },
    )
    raw = SimpleNamespace(key=loaded.key)

    with patch(
        "lagniappe.core.entities.user.database.get.user",
        return_value=raw,
    ) as get_user:
        with patch(
            "lagniappe.core.entities.user.Entities.fetch_one",
            return_value=loaded,
        ) as get_entity:
            result = User.load("loaded@example.com")

    get_user.assert_called_once_with("loaded@example.com")
    get_entity.assert_called_once_with(raw, request=Fetch.direct())
    assert result is loaded


# @pair user:create
# @pair user:cache-invalidation
@pytest.mark.unit
def test_user_create_does_not_leave_initial_cache_invalidation():
    page = TestEntities.get(
        "PAGE",
        {
            "name": "Initial Cache Page",
            "hash": "initial-cache-page",
            "model": {"name": "Initial Cache Category", "hash": "initial-cache-cat"},
        },
    )
    users_model = TestEntities.get(
        "USERS", {"name": "Users", "hash": "users", "type": "users"}
    )
    new_key = Key("users", "initial-cache-user", project="test")
    new_entity = Entity(new_key)

    with patch(
        "lagniappe.core.entities.user.CONFIG",
        SimpleNamespace(ADMIN_EMAIL="initial-cache@example.test"),
    ):
        with patch(
            "lagniappe.core.entities.user.database.get.user",
            return_value=None,
        ):
            with patch(
                "lagniappe.core.entities.entity.database.create_key",
                return_value=new_key,
            ):
                with patch(
                    "lagniappe.core.entities.entity.database.get.entity",
                    return_value=None,
                ):
                    with patch(
                        "lagniappe.core.entities.entity.database.create_entity",
                        return_value=new_entity,
                    ):
                        with patch(
                            "lagniappe.core.properties.user_related.Entities.USERS.get",
                            return_value=users_model,
                        ):
                            user = User.create(
                                {
                                    "name": "Initial Cache User",
                                    "email": "initial-cache@example.test",
                                    "page": page,
                                }
                            )

    assert user.is_owner is True
    assert user.ai_access == "CREATE"
    assert user.invalidate_cache is False


# @features user public-users
# @dimensions create public-user public-group personal-page limited-attrs
@pytest.mark.unit
def test_user_create_public_user_assigns_public_group():
    page = TestEntities.get("PAGE", {"name": "Public Page", "hash": "pg009f"})
    users_model = TestEntities.get(
        "USERS", {"name": "Users", "hash": "users", "type": "users"}
    )
    normal_group = TestEntities.get(
        "USER_GROUP",
        {"name": "Editors", "hash": "grp009d"},
    )
    public_group = TestEntities.get(
        "PUBLIC_GROUP",
        {"name": "public", "hash": "pub009b"},
    )
    new_key = Key("users", "public-new", project="test")
    new_entity = Entity(new_key)

    with patch(
        "lagniappe.core.entities.user.database.get.user",
        return_value=None,
    ):
        with patch(
            "lagniappe.core.entities.entity.database.create_key",
            return_value=new_key,
        ):
            with patch(
                "lagniappe.core.entities.entity.database.get.entity",
                return_value=None,
            ):
                with patch(
                    "lagniappe.core.entities.entity.database.create_entity",
                    return_value=new_entity,
                ):
                    with patch(
                        "lagniappe.core.entities.user.Entities.PUBLIC_GROUP.get",
                        return_value=public_group,
                    ):
                        with patch(
                            "lagniappe.core.properties.user_related.Entities.PUBLIC_GROUP.get",
                            return_value=public_group,
                        ):
                            with patch(
                                "lagniappe.core.properties.user_permissions.UserPermissions.create"
                            ) as create_permissions:
                                with patch(
                                    "lagniappe.core.properties.user_related.Entities.USERS.get",
                                    return_value=users_model,
                                ):
                                    created = User.create(
                                        {
                                            "name": "Public User",
                                            "email": "public@example.com",
                                            "page": page,
                                            "groups": [normal_group],
                                            "is_public": True,
                                            "test_user": True,
                                        }
                                    )

    assert created.is_public is True
    assert created.ai_access == "NONE"
    assert page.model is users_model
    assert created.groups == [public_group]
    assert created.db["groups"] == [public_group.key]
    assert set(page.db["attributes"]) == {"tasks", "document", "notes"}
    assert create_permissions.called
