"""Page restriction sources, resource access, and task visibility."""

from unittest.mock import patch

import pytest

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities.task import Task

from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities


# @source lagniappe/core/properties/common_entity.py::RestrictedTo.value
# @source lagniappe/core/properties/common_entity.py::RestrictedTo.materialize
# @matrix permissions : local-restrictions source-clauses no-extra-read
@pytest.mark.unit
def test_page_restrictions_keep_local_storage_separate_from_form_without_reads():
    page = TestEntities.get("PAGE", {
        "name": "Inherited restriction", "hash": "inheritpage",
        "form": {"name": "Restricted form", "hash": "inheritform", "groups": [
            {"name": "Form team", "hash": "formteam", "permissions": {}},
        ]},
    })
    form = page.form
    form.properties.groups.unset()
    with (
        patch(
            "lagniappe.core.entities.page.database_get.group_view_access",
            side_effect=AssertionError("Restriction properties must not query groups"),
        ),
        patch(
            "lagniappe.core.entities.page.Entities.fetch",
            side_effect=AssertionError("Restriction properties must not fetch entities"),
        ),
    ):
        assert page.restricted_to == {"page_form": ["formteam"]}
        assert page.properties.restricted_to.stored == []
        assert form.properties.groups.is_set is False

        local = TestEntities.get("USER_GROUP", {
            "name": "Local team", "hash": "localteam", "permissions": {},
        })
        page.groups = [local]
        page.properties.restricted_to.materialize(admin_only=False)
        assert page.properties.restricted_to.stored == ["localteam"]
        assert page.restricted_to == {"page": ["localteam"], "page_form": ["formteam"]}

        page.properties.restricted_to.materialize(admin_only=True)
        assert page.properties.restricted_to.stored == ["admin"]
        assert page.restricted_to == {"page": ["admin"], "page_form": ["formteam"]}

        page.groups = []
        page.properties.restricted_to.materialize(admin_only=False)
        form.properties.restricted_to.materialize(admin_only=True)
        assert page.properties.restricted_to.stored == []
        assert page.restricted_to == {"page_form": ["admin"]}

    form.groups = []
    form.properties.restricted_to.materialize(admin_only=False)
    assert page.restricted_to == {}


# @source lagniappe/core/entities/page.py::Page.allowed
# @matrix page permissions users : models-scope user-page
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

# @matrix page permissions user-groups : group-match restricted-access
@pytest.mark.unit
def test_page_restricted_access_group_match(get_test_entities):
    """The viewer must match a group in the Page restriction."""
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
            "lagniappe.core.entities.page.database_get.page_tasks",
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
    fetch.assert_called_once_with(
        *keys, page,
        request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
    )
