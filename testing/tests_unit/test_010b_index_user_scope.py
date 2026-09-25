"""Index visibility follows the supplied viewer independently of ambient identity."""

from types import SimpleNamespace

import pytest

from lagniappe import CONFIG
from lagniappe.core.entities import index
from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities


@pytest.fixture
def index_boundaries(monkeypatch):
    monkeypatch.setattr(index, "url_for", lambda *_args, **_kwargs: "/next")
    details = MockRestrictions(
        kind_overrides={
            key: {"hash": key, "kind": "group", "id": key} for key in ("grp-a", "grp-b")
        }
    )
    monkeypatch.setattr(index.cache, "get_details_by_hash", details.get_details_by_hash)


def _viewer(suffix, permissions):
    return TestEntities.get(
        "USER",
        {
            "hash": f"viewer-{suffix}",
            "page": {"hash": f"viewer-page-{suffix}"},
            "requires": ["users", f"grp-{suffix}"],
            "permissions": permissions,
        },
    )


# @matrix task-index : explicit-user permissions
@pytest.mark.unit
@pytest.mark.parametrize("viewer_suffix", ["a", "b"])
@pytest.mark.parametrize("undated", [False, True])
def test_task_index_visibility_uses_explicit_viewer(
    monkeypatch,
    index_boundaries,
    viewer_suffix,
    undated,
):
    tasks = [
        TestEntities.get(
            "TASK",
            {
                "hash": f"task-{suffix}",
                "page": {"hash": f"page-{suffix}"},
                "enforce_allowed": True,
            },
        )
        for suffix in ("a", "b")
    ]
    viewers = {
        suffix: _viewer(suffix, {f"page-{suffix}": "VIEW"}) for suffix in ("a", "b")
    }
    viewer = viewers[viewer_suffix]
    monkeypatch.setattr(
        CONFIG, "TEST_CURRENT_USER", viewers["b" if viewer_suffix == "a" else "a"]
    )
    queries = []

    def query(**kwargs):
        queries.append(kwargs)
        return SimpleNamespace(results=[task.key for task in tasks], next_cursor=None)

    monkeypatch.setattr(
        index.database_get,
        "tasks_without_due_dates" if undated else "tasks_with_due_dates",
        query,
    )
    monkeypatch.setattr(index.Entities, "fetch", lambda *_args, **_kwargs: tasks)

    result = index.TaskIndex(user=viewer, undated=undated).tasks

    assert [task.hash for task in result] == [f"task-{viewer_suffix}"]
    assert queries[0]["hashes"] == [f"page-{viewer_suffix}"]
    assert queries[0]["assigned_to"] is viewer.page


# @matrix pages : explicit-user permissions
@pytest.mark.unit
@pytest.mark.parametrize("viewer_suffix", ["a", "b"])
def test_page_index_visibility_uses_explicit_viewer(
    monkeypatch, index_boundaries, viewer_suffix
):
    category = TestEntities.get("CATEGORY", {"hash": "cat-root"})
    pages = [
        TestEntities.get("PAGE", {"hash": f"page-{suffix}", "enforce_allowed": True})
        for suffix in ("a", "b")
    ]
    viewers = {
        suffix: _viewer(suffix, {f"page-{suffix}": "VIEW"}) for suffix in ("a", "b")
    }
    monkeypatch.setattr(
        CONFIG, "TEST_CURRENT_USER", viewers["b" if viewer_suffix == "a" else "a"]
    )
    monkeypatch.setattr(
        index.database_get,
        "pages",
        lambda *_args, **_kwargs: SimpleNamespace(
            results=[page.key for page in pages],
            next_cursor="next-page",
        ),
    )
    monkeypatch.setattr(index.Entities, "fetch", lambda *_args, **_kwargs: pages)

    listing = index.PageIndex(entity=category, user=viewers[viewer_suffix])

    assert [page.hash for page in listing.pages] == [f"page-{viewer_suffix}"]
    assert listing.cursor == "next-page"


# @matrix forms : explicit-user permissions
@pytest.mark.unit
@pytest.mark.parametrize("viewer_suffix", ["a", "b"])
def test_form_index_visibility_uses_explicit_viewer(
    monkeypatch, index_boundaries, viewer_suffix
):
    forms = [
        TestEntities.get(
            "FORM",
            {
                "hash": f"form-{suffix}",
                "restricted_to": [f"grp-{suffix}"],
                "enforce_allowed": True,
            },
        )
        for suffix in ("a", "b")
    ]
    viewers = {suffix: _viewer(suffix, {"forms": "VIEW"}) for suffix in ("a", "b")}
    monkeypatch.setattr(
        CONFIG, "TEST_CURRENT_USER", viewers["b" if viewer_suffix == "a" else "a"]
    )
    monkeypatch.setattr(
        index.database_get,
        "forms",
        lambda **_kwargs: SimpleNamespace(
            results=[form.key for form in forms],
            next_cursor=None,
        ),
    )
    monkeypatch.setattr(index.database_get, "form_users", lambda *_args: [])
    monkeypatch.setattr(index.Entities, "fetch", lambda *_args, **_kwargs: forms)

    assert [
        form.hash for form in index.FormIndex(user=viewers[viewer_suffix]).forms
    ] == [f"form-{viewer_suffix}"]


# @matrix forms : explicit-user related-entities
@pytest.mark.unit
@pytest.mark.parametrize("viewer_suffix", ["a", "b"])
def test_form_index_related_models_use_explicit_viewer(
    monkeypatch, index_boundaries, viewer_suffix
):
    # Use the production Form: the fixture subclass rebuilds .projects on read.
    form = index.Entities.FORM(testing=True)
    form._key = "form-shared"
    form.db.update(type="form", hash="form-shared", requires=["forms"])
    categories = [
        TestEntities.get("CATEGORY", {"hash": f"cat-{suffix}"}) for suffix in ("a", "b")
    ]
    projects = [
        TestEntities.get("PROJECT", {"hash": f"proj-{suffix}"}) for suffix in ("a", "b")
    ]
    models = [
        TestEntities.get("MODEL_TASK", {"hash": f"model-{suffix}"}, project=project)
        for suffix, project in zip(("a", "b"), projects)
    ]
    for category in categories:
        category.forms = [form]
    for model in models:
        model.form = form
    viewers = {
        suffix: _viewer(
            suffix,
            {
                "forms": "VIEW",
                f"cat-{suffix}": "VIEW",
                f"proj-{suffix}": "VIEW",
            },
        )
        for suffix in ("a", "b")
    }
    monkeypatch.setattr(
        CONFIG, "TEST_CURRENT_USER", viewers["b" if viewer_suffix == "a" else "a"]
    )
    monkeypatch.setattr(
        index.database_get,
        "forms",
        lambda **_kwargs: SimpleNamespace(results=[form.key], next_cursor=None),
    )
    monkeypatch.setattr(index.database_get, "form_users", lambda *_args: [])
    monkeypatch.setattr(
        index.Entities, "fetch", lambda *_args, **_kwargs: [form, *categories, *models]
    )

    result = index.FormIndex(user=viewers[viewer_suffix]).forms

    assert result == [form]
    assert [category.hash for category in form.categories] == [f"cat-{viewer_suffix}"]
    assert [project.hash for project in form.projects] == [f"proj-{viewer_suffix}"]


# @matrix user-index : explicit-user groups permissions
@pytest.mark.unit
@pytest.mark.parametrize("viewer_suffix", ["a", "b"])
def test_user_index_groups_use_explicit_viewer(
    monkeypatch, index_boundaries, viewer_suffix
):
    groups = [
        TestEntities.get("USER_GROUP", {"hash": f"grp-{suffix}"})
        for suffix in ("a", "b")
    ]
    viewers = {
        suffix: _viewer(suffix, {f"grp-{suffix}": "VIEW"}) for suffix in ("a", "b")
    }
    monkeypatch.setattr(
        CONFIG, "TEST_CURRENT_USER", viewers["b" if viewer_suffix == "a" else "a"]
    )
    monkeypatch.setattr(
        index.database_get, "groups", lambda **_kwargs: [group.key for group in groups]
    )
    monkeypatch.setattr(index.Entities, "fetch", lambda *_args, **_kwargs: groups)

    assert [
        group.hash for group in index.UserIndex(user=viewers[viewer_suffix]).groups
    ] == [f"grp-{viewer_suffix}"]
