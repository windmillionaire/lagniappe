"""Unit tests for User restrictions property."""

from flask import Flask, session
import pytest

from lagniappe.core.definitions import Restriction
from lagniappe.core.properties import user_restrictions as user_restrictions_module
from lagniappe.core.properties.base_property import UNSET
from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities


def _expected(value):
    return Restriction.UNRESTRICTED if value is False else value


def _has_access(value):
    return Restriction.is_unrestricted(value) or bool(value)


def _reset_restrictions(user):
    restrictions = user.properties.restrictions
    restrictions.unset()
    restrictions._state = None
    restrictions._permission_details = {}
    restrictions._value_details = {}
    return restrictions


def _app():
    app = Flask(__name__)
    app.secret_key = "testing-secret"
    return app


# @pairs restrictions:search permissions:search
# @pairs restrictions:assign permissions:assign
# @pairs restrictions:facets permissions:facets
# @pair restrictions:page-list
# @pairs restrictions:category-edit permissions:category-edit
@pytest.mark.unit
def test_restrictions(get_permissions_test_data):
    """Test restrictions property for various user permission configurations.

    Covers:
    - Site owner gets ["forms", "models", "users"] and search returns False
    - User with general permissions gets those in restrictions
    - User with specific permissions only gets those hashes
    - Mixed general and specific permissions
    - can_assign with USERS ASSIGN or group ASSIGN

    Entity details for facet resolution come from :class:`MockRestrictions`
    (same shape as ``cache.get_details_by_hash``), reusable in e2e.
    """
    with MockRestrictions().patch_cache():
        users, _ = get_permissions_test_data()

        for user in users:
            expected = user.test_spec["expected"]

            restrictions = user.properties.restrictions.value
            assert sorted(restrictions) == sorted(expected["restrictions"]), (
                f"{user.name}: restrictions = {restrictions}, "
                f"expected {expected['restrictions']}"
            )

            assert user.properties.restrictions.search == _expected(
                expected["search"]
            ), (
                f"{user.name}: search = {user.properties.restrictions.search}, "
                f"expected {expected['search']}"
            )

            user_assign_val = user.properties.restrictions.user_assign_restrictions
            exp_user_assign = _expected(expected["user_assign"])
            assert _has_access(user_assign_val) == expected["can_assign"], (
                f"{user.name}: user_assign access = {_has_access(user_assign_val)}, "
                f"expected {expected['can_assign']}"
            )
            if isinstance(user_assign_val, list) and isinstance(exp_user_assign, list):
                assert sorted(user_assign_val) == sorted(exp_user_assign), (
                    f"{user.name}: user_assign = {user_assign_val}, "
                    f"expected {exp_user_assign}"
                )
            else:
                assert user_assign_val == exp_user_assign, (
                    f"{user.name}: user_assign = {user_assign_val}, "
                    f"expected {exp_user_assign}"
                )
            category_edit_val = user.properties.restrictions.category_edit_restrictions
            exp_category_edit = _expected(expected["category_edit"])
            assert _has_access(category_edit_val) == expected["can_create_pages"], (
                f"{user.name}: category_edit access = {_has_access(category_edit_val)}, "
                f"expected {expected['can_create_pages']}"
            )
            if isinstance(category_edit_val, list) and isinstance(
                exp_category_edit, list
            ):
                assert sorted(category_edit_val) == sorted(exp_category_edit), (
                    f"{user.name}: category_edit = {category_edit_val}, "
                    f"expected {exp_category_edit}"
                )
            else:
                assert category_edit_val == exp_category_edit, (
                    f"{user.name}: category_edit = {category_edit_val}, "
                    f"expected {exp_category_edit}"
                )
            task_val = user.properties.restrictions.task
            exp_task = _expected(expected["task"])
            if isinstance(task_val, list) and isinstance(exp_task, list):
                assert sorted(task_val) == sorted(exp_task), (
                    f"{user.name}: task = {task_val}, expected {exp_task}"
                )
            else:
                assert task_val == exp_task, (
                    f"{user.name}: task = {task_val}, expected {exp_task}"
                )

            page_val = user.properties.restrictions.page
            exp_page = _expected(expected["page"])
            if isinstance(page_val, list) and isinstance(exp_page, list):
                assert sorted(page_val) == sorted(exp_page), (
                    f"{user.name}: page = {page_val}, expected {exp_page}"
                )
            else:
                assert page_val == exp_page, (
                    f"{user.name}: page = {page_val}, expected {exp_page}"
                )

            form_val = user.properties.restrictions.form
            exp_form = _expected(expected["form"])
            if isinstance(form_val, list) and isinstance(exp_form, list):
                assert sorted(form_val) == sorted(exp_form), (
                    f"{user.name}: form = {form_val}, expected {exp_form}"
                )
            else:
                assert form_val == exp_form, (
                    f"{user.name}: form = {form_val}, expected {exp_form}"
                )

            users_val = user.properties.restrictions.users
            exp_users = _expected(expected["users"])
            if isinstance(users_val, list) and isinstance(exp_users, list):
                assert sorted(users_val) == sorted(exp_users), (
                    f"{user.name}: users = {users_val}, expected {exp_users}"
                )
            else:
                assert users_val == exp_users, (
                    f"{user.name}: users = {users_val}, expected {exp_users}"
                )


# @features restrictions permissions
# @dimensions session-blob stale-session empty-access
@pytest.mark.unit
def test_restrictions_session_blob_and_fingerprint(monkeypatch):
    user = TestEntities.get(
        "USER",
        {
            "name": "Session Restricted User",
            "hash": "session-user",
            "page": {"name": "Session Page", "hash": "session-page"},
            "permissions": {
                "cat001": "RESTRICTED",
                "page001": "EDIT",
                "session-page": "EDIT",
            },
        },
    )
    monkeypatch.setattr(user_restrictions_module, "current_user", user)

    with _app().test_request_context("/"):
        session["restrictions"] = ["invalid-current-blob"]

        with MockRestrictions(
            kind_overrides={
                "page001": {
                    "hash": "page001",
                    "kind": "page",
                    "requires": ["cat001"],
                },
                "session-page": {
                    "hash": "session-page",
                    "kind": "page",
                    "requires": [],
                },
            }
        ).patch_cache() as details:
            restrictions = user.properties.restrictions
            assert restrictions.value == ["page001", "session-page"]
            assert restrictions.unrestricted_pages(
                TestEntities.get("CATEGORY", {"name": "Cat", "hash": "cat001"})
            ) == ["page001"]

        blob = session["restrictions"]
        assert blob["version"] == restrictions._session_version
        assert blob["task"] == ["page001", "session-page"]
        assert blob["belongs_to"] == []
        assert "fingerprint" in blob
        assert "ai_action_capabilities" not in blob
        assert "can_use_ai_tools" not in blob
        assert "can_assign" not in blob
        assert "can_create_pages" not in blob
        assert details.call_count == 1

        _reset_restrictions(user)
        monkeypatch.setattr(
            user_restrictions_module.cache,
            "get_details_by_hash",
            lambda *_args, **_kwargs: pytest.fail("session blob should hydrate"),
        )

        assert user.properties.restrictions.task == ["page001", "session-page"]

        session["restrictions"]["fingerprint"] = "stale"
        user.permissions = {**user.permissions, "cat002": "VIEW"}
        _reset_restrictions(user)

        with MockRestrictions().patch_cache():
            assert user.properties.restrictions.value == [
                "cat002",
                "page001",
                "session-page",
            ]
        assert session["restrictions"]["fingerprint"] != "stale"


# @pair restrictions:root-fetch
# @pair permissions:stored-requires
# @pair permissions:group-membership
@pytest.mark.unit
def test_restrictions_builds_group_membership_from_stored_requires(monkeypatch):
    user = TestEntities.get(
        "USER",
        {
            "name": "Root Loaded Group User",
            "hash": "root-group-user",
            "requires": ["users", "group-one"],
            "permissions": {"page-one": "VIEW"},
        },
    )
    monkeypatch.setattr(user_restrictions_module, "current_user", user)

    groups = user.properties.groups
    monkeypatch.setattr(
        type(groups),
        "value",
        property(lambda _self: pytest.fail("group relation must not be read")),
    )

    with _app().test_request_context("/"):
        with MockRestrictions().patch_cache():
            assert user.properties.restrictions.belongs_to == ["group-one"]


# @features restrictions permissions
# @dimensions empty-access loaded-state
@pytest.mark.unit
def test_restrictions_empty_list_is_loaded_state():
    user = TestEntities.get(
        "USER",
        {
            "name": "No Access User",
            "hash": "no-access",
            "page": {"name": "No Access Page", "hash": "no-access-page"},
            "permissions": {},
        },
    )

    with MockRestrictions().patch_cache() as details:
        restrictions = user.properties.restrictions
        assert restrictions.value == []
        assert restrictions.task == []
        assert restrictions.form == []
        assert restrictions.users == []

    assert restrictions.is_set
    assert restrictions._value == []
    assert restrictions._state is not None
    assert restrictions.value == []
    assert restrictions._value is not UNSET
    assert details.call_count == 0


# @features restrictions permissions
# @dimensions clear session-blob
@pytest.mark.unit
def test_restrictions_clear_removes_session_blob():
    user = TestEntities.get(
        "USER",
        {
            "name": "Clear Session User",
            "hash": "clear-user",
            "page": {"name": "Clear Page", "hash": "clear-page"},
            "permissions": {},
        },
    )

    with _app().test_request_context("/"):
        session["restrictions"] = {"version": 2}

        user.properties.restrictions.clear()

        assert "restrictions" not in session
