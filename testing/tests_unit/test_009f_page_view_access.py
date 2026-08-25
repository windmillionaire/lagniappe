"""Page ``view_access`` (disclosure) vs ``restricted_access`` / task visibility."""

from unittest.mock import patch

import pytest

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities.task import Task

from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities


# @matrix page : owner view-access
@pytest.mark.unit
def test_page_view_access_owner_stored_only(get_test_entities):
    """Stored ``restricted_to`` containing ``owner`` yields no group disclosure list."""
    page = get_test_entities()[0]
    assert page.view_access == []


# @matrix page : attached-groups view-access
@pytest.mark.unit
def test_page_view_access_returns_attached_groups(get_test_entities):
    """When the page has attached groups, ``view_access`` returns them (not DB lookup)."""
    page = get_test_entities()[0]
    groups = page.groups
    assert groups
    assert [g.hash for g in page.view_access] == [g.hash for g in groups] == [
        "grpedit",
        "grpview",
    ]


# @matrix page : db-load group-views view-access
@pytest.mark.unit
def test_page_view_access_from_group_views(get_test_entities):
    """No attached groups: load groups whose ``views`` index hits ``page.required``."""
    page = get_test_entities()[0]
    g1 = TestEntities.get(
        "USER_GROUP",
        {"name": "Via views", "hash": "grpv1", "permissions": {"models": "VIEW"}},
    )
    g1.db["views"] = ["pgdb1", "cat001", "models"]

    with (
        patch(
            "lagniappe.core.entities.page.database.get.group_view_access",
            return_value=[g1.key],
        ) as mock_gva,
        patch(
            "lagniappe.core.entities.page.Entities.fetch",
            return_value=[g1],
        ) as mock_load,
    ):
        out = page.view_access

    mock_gva.assert_called_once()
    mock_load.assert_called_once()
    assert out == [g1]


# @matrix page permissions users : models-scope user-page view-access
@pytest.mark.unit
def test_user_page_uses_users_permissions_not_models_permissions():
    """Users-only pages use Users access; attached categories still grant page access."""
    model_creator = TestEntities.get(
        "USER",
        {
            "name": "Model Creator",
            "hash": "usrmodels2",
            "page": {"name": "Model Creator Page", "hash": "pgmodels2"},
            "permissions": {"models": "CREATE", "users": "NONE"},
        },
    )
    category_viewer = TestEntities.get(
        "USER",
        {
            "name": "Category Viewer",
            "hash": "usrcatview2",
            "page": {"name": "Category Viewer Page", "hash": "pgcatview2"},
            "permissions": {"catfriends": "VIEW", "users": "NONE"},
        },
    )
    default_page = TestEntities.get(
        "PAGE",
        {
            "name": "User Page",
            "hash": "pguserscope",
            "model": {"name": "Users", "hash": "users"},
            "user": {"name": "Page Owner", "hash": "usrpageowner2"},
        },
    )
    categorized_page = TestEntities.get(
        "PAGE",
        {
            "name": "Categorized User Page",
            "hash": "pgusercat2",
            "model": {"name": "Users", "hash": "users"},
            "categories": [{"name": "Friends", "hash": "catfriends"}],
            "user": {"name": "Categorized Owner", "hash": "usrcatowner2"},
        },
    )

    assert default_page.model.kind == "users"
    assert default_page.required == ["users", "pguserscope"]
    assert categorized_page.required == [
        "models",
        "users",
        "pgusercat2",
        "catfriends",
    ]
    assert default_page.allowed(Action.VIEW, user=model_creator) is False
    assert categorized_page.allowed(Action.VIEW, user=model_creator) is True
    assert default_page.allowed(Action.VIEW, user=category_viewer) is False
    assert categorized_page.allowed(Action.VIEW, user=category_viewer) is True

    with (
        patch(
            "lagniappe.core.entities.page.database.get.group_view_access",
            return_value=[],
        ) as mock_gva,
        patch("lagniappe.core.entities.page.Entities.fetch", return_value=[]),
    ):
        assert default_page.view_access == []

    mock_gva.assert_called_once_with(["users", "pguserscope"])


# @matrix page permissions user-groups : group-match restricted-access
@pytest.mark.unit
def test_page_restricted_access_group_match(get_test_entities):
    """``restricted_access`` uses intersection of page restriction and user's groups."""
    entities = get_test_entities()
    page = entities[0]
    member = entities[1]
    outsider = entities[2]

    with MockRestrictions().patch_cache():
        assert page.restricted_access(member) is False
        assert page.allowed(Action.VIEW, user=member) is True

        assert page.restricted_access(outsider) is True
        assert page.allowed(Action.VIEW, user=outsider) is False


# @matrix page permissions : no-category-expansion shallow-page stored-requires
@pytest.mark.unit
def test_page_allowed_uses_stored_requirements_without_loading_categories():
    page = TestEntities.get(
        "PAGE",
        {"name": "Shallow Permission Page", "hash": "shallow-permission-page"},
    )
    page.db["model"] = "unloaded-model"
    page.db["requires"] = ["models", "shallow-permission-page"]
    page.properties.model.unset()
    page.properties.categories.unset()
    page.restricted_access = lambda _user: False
    viewer = TestEntities.get(
        "USER",
        {
            "name": "Shallow Page Viewer",
            "hash": "shallow-page-viewer",
            "page": {"name": "Viewer Page", "hash": "viewer-page"},
            "permissions": {"models": "NONE"},
        },
    )

    assert page.allowed(Action.EDIT, user=viewer) is False
    assert page.properties.model.is_set is False
    assert page.properties.categories.is_set is False


# @pair page:view-owner-short-circuit
@pytest.mark.unit
def test_page_view_does_not_require_loaded_owner(monkeypatch):
    """View checks do not load the owner needed only by privileged mutations."""
    page = TestEntities.get(
        "PAGE",
        {
            "name": "Shallow Owner Page",
            "hash": "shallow-owner-page",
            "user": {"name": "Page Owner", "hash": "shallow-page-owner"},
        },
    )
    viewer = TestEntities.get(
        "USER",
        {"name": "Site Owner", "hash": "shallow-view-owner", "owner": True},
    )
    page.properties.user.unset()
    page.restricted_access = lambda _user: False
    monkeypatch.setattr(
        "lagniappe.core.mixins.related.capture_unloaded_relation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("view permission loaded the page owner")
        ),
    )

    assert page.allowed(Action.VIEW, user=viewer) is True


# @matrix page permissions task : restricted-access task-visibility
@pytest.mark.unit
def test_page_tasks_filtered_by_task_allowed(get_test_entities, monkeypatch):
    """``Page._load_tasks`` keeps only tasks where ``task.allowed(VIEW)`` is true."""
    entities = get_test_entities()
    page = entities[0]
    t_show = entities[1]
    t_hide = entities[2]

    keys = [t_show.key, t_hide.key]

    def _allowed(self, action, user=None):
        if self.key == t_hide.key:
            return False
        return True

    monkeypatch.setattr(Task, "allowed", _allowed)

    with (
        patch(
            "lagniappe.core.entities.page.database.get.page_tasks",
            return_value=keys,
        ),
        patch(
            "lagniappe.core.entities.page.Entities.fetch",
            return_value=[t_hide, t_show],
        ) as fetch,
    ):
        page._tasks = None
        page._completed = None
        visible = page.tasks

    assert visible == [t_show]
    fetch.assert_called_once_with(*keys, page, request=Fetch.direct())
