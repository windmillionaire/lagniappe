"""E2E coverage for core entity save/delete lifecycle behavior.

These tests use real configured services, but they intentionally stay below the
web/UI layer. They exercise ``Entities.save`` and ``Entities.delete`` directly
and verify the datastore, cache, and storage effects owned by that machinery.
"""

import json
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.cache.core import cache as redis_cache
from lagniappe.core.tools.cache.keys import Search
from lagniappe.core.tools.database.core import DATA
from lagniappe.core.tools.database import get as database_get

pytestmark = pytest.mark.e2e

FIELD_ID = "input-lifecycle-text"


def _name(label):
    return f"test-lifecycle-{label}-{uuid4().hex[:8]}"


def _schema():
    return [
        {
            "id": FIELD_ID,
            "type": "input",
            "input": "text",
            "title": "Lifecycle Text",
        }
    ]


def _create_form(label, form_type="page"):
    form = Entities.FORM.create(
        {
            "name": _name(label),
            "form-type": form_type,
            "schema": _schema(),
        }
    )
    form.save()
    return form


def _create_filter(parent, creator, label):
    entity_filter = Entities.FILTER(parent=parent.key)
    entity_filter.kind = entity_filter.entity_kind
    entity_filter.name = _name(label)
    entity_filter.parent = parent
    entity_filter.creator = creator
    entity_filter.definitions = []
    entity_filter.related = []
    entity_filter.save()
    return entity_filter


def _create_category(label, form=None):
    category = Entities.CATEGORY.create({"name": _name(label), "form": form})
    category.save()
    return category


def _create_page(label, categories, form=None, submission=None):
    page = Entities.PAGE.create(
        {
            "name": _name(label),
            "categories": categories,
            "form": form,
            "submission": submission,
        }
    )
    page.save()
    return page


def _create_file(label, page):
    file = Entities.FILE.create(page=page, data={"name": _name(label)})
    file.save()
    return file


def _save_private_text_asset(entity, label):
    asset = entity.save_asset(f"{label} private text", "text", "text")
    entity.save()
    return asset.definition


def _save_public_image_asset(entity, label):
    image = BytesIO(f"{label} public image".encode("utf-8"))
    asset = entity.save_asset(image, "public_image", "image", visibility="public")
    entity.save()
    return asset.definition


def _save_document(entity, label):
    entity.properties.document.save(
        html=f"<p>{label} document body</p>",
        ydoc=f"{label} ydoc",
    )
    entity.save()
    return dict(entity.assets)


def _blob_exists(definition):
    visibility = definition.get("visibility", "private")
    return DATA.bucket(visibility).blob(definition["path"]).exists()


def _cache_key(entity):
    key_template = Search[entity.kind]
    return key_template.key(entity) if key_template else None


def _assert_saved(entity):
    assert database_get.entity(entity.key) is not None
    cache_key = _cache_key(entity)
    if cache_key:
        assert redis_cache.redis.exists(cache_key)


def _assert_deleted(entity):
    assert database_get.entity(entity.key) is None
    cache_key = _cache_key(entity)
    if cache_key:
        assert not redis_cache.redis.exists(cache_key)
    if entity.hash:
        assert entity.hash not in cache.get_details_by_hash({entity.hash})


def _assert_hash_cached(entity):
    details = cache.get_details_by_hash({entity.hash})
    assert details[entity.hash]["id"] == entity.urlsafe_key


# @matrix entities : cache database dependent-owner process-state save
def test_entity_save_persists_relations_process_payloads_and_cache():
    form = _create_form("save-form")
    category = _create_category("save-category", form=form)
    page = Entities.PAGE.create(
        {
            "name": _name("save-page"),
            "categories": [category],
            "form": form,
            "submission": {FIELD_ID: "persisted submission"},
        }
    )

    page.get_process("lifecycle-save")["status"] = "queued"
    assets = _save_document(page, "save")
    raw_page = database_get.entity(page.key)

    _assert_saved(form)
    _assert_saved(category)
    _assert_saved(page)
    _assert_hash_cached(page)

    assert json.loads(raw_page["lifecycle-save"]) == {"status": "queued"}
    assert category in page.page_list_owners
    assert _blob_exists(assets["document"])
    assert _blob_exists(assets["snapshot"])

    history = database_get.document_history(page)
    assert len(history) == 1
    assert history[0]["type"] == "document_history"
    assert database_get.entity(history[0].key) is not None

    reloaded = Entities.fetch_one(page.key, request=Fetch.direct())
    assert reloaded.name == page.name
    assert reloaded.form.key == form.key
    assert {c.key for c in reloaded.categories} == {category.key}
    assert reloaded.submission[FIELD_ID] == "persisted submission"


# @matrix entities : assets cache cascade database delete
def test_entity_delete_cascades_dependents_assets_and_cache():
    creator = _create_page("category-filter-creator", [])
    page_form = _create_form("category-page-form")
    task_form = _create_form("category-task-form", form_type="task")
    doomed_category = _create_category("doomed-category", form=page_form)
    survivor_category = _create_category("survivor-category")
    category_filter = _create_filter(
        doomed_category, creator, "doomed-category-filter"
    )

    doomed_page = _create_page(
        "doomed-page",
        [doomed_category],
        form=page_form,
        submission={FIELD_ID: "deleted page value"},
    )
    doomed_page_private = _save_private_text_asset(doomed_page, "deleted-page")
    doomed_page_public = _save_public_image_asset(doomed_page, "deleted-page")

    survivor_page = _create_page(
        "survivor-page",
        [doomed_category, survivor_category],
        form=page_form,
        submission={FIELD_ID: "survivor page value"},
    )

    task = Entities.TASK.create(
        {
            "page": doomed_page,
            "form": task_form,
            "name": _name("doomed-task"),
            "submission": {FIELD_ID: "task value"},
        }
    )
    task.completed = True
    task.completed_on = datetime.now(timezone.utc)
    task_history = task.create_history_entry()
    task.save()

    doomed_file = _create_file("doomed-file", doomed_page)
    doomed_file_asset = _save_private_text_asset(doomed_file, "doomed-file")

    survivor_file = _create_file("survivor-file", doomed_page)
    survivor_file.properties.pages.add(survivor_page)
    survivor_file_asset = _save_private_text_asset(survivor_file, "survivor-file")

    assert _blob_exists(doomed_page_private)
    assert _blob_exists(doomed_page_public)
    assert _blob_exists(doomed_file_asset)
    assert _blob_exists(survivor_file_asset)

    Entities.delete(doomed_category)

    for entity in [
        doomed_category,
        category_filter,
        doomed_page,
        task,
        task_history,
        doomed_file,
    ]:
        _assert_deleted(entity)

    assert not database_get.filters(doomed_category.key)
    assert not database_get.page_tasks_with_history(doomed_page)
    assert not database_get.page_files(doomed_page.key)

    for definition in [
        doomed_page_private,
        doomed_page_public,
        doomed_file_asset,
    ]:
        assert not _blob_exists(definition)

    _assert_saved(survivor_category)
    _assert_saved(survivor_page)
    _assert_saved(survivor_file)
    assert _blob_exists(survivor_file_asset)

    reloaded_page = Entities.fetch_one(survivor_page.key, request=Fetch.direct())
    assert {c.key for c in reloaded_page.categories} == {survivor_category.key}

    reloaded_file = Entities.fetch_one(survivor_file.key, request=Fetch.direct())
    assert {p.key for p in reloaded_file.pages} == {survivor_page.key}


# @matrix entities : cache cascade database delete forms
def test_entity_delete_project_cascades_models_forms_filters_and_cache():
    creator = _create_page("project-filter-creator", [])
    model_only_project = Entities.PROJECT.create(
        {
            "name": _name("model-only-project"),
            "description": "Project deleted by entity lifecycle tests.",
        }
    )
    model_only_project.save()
    project_filter = _create_filter(
        model_only_project, creator, "doomed-project-filter"
    )

    shared_project = Entities.PROJECT.create(
        {
            "name": _name("shared-form-project"),
            "description": "Project deleted while preserving a shared form.",
        }
    )
    shared_project.save()

    model_only_form = _create_form("model-only-form", form_type="task")
    shared_form = _create_form("shared-model-form", form_type="task")
    shared_category = _create_category("shared-form-category", form=shared_form)

    model_only = Entities.MODEL_TASK.create(
        model_only_project,
        {"name": _name("model-only-task"), "form": model_only_form},
    )
    model_shared = Entities.MODEL_TASK.create(
        shared_project,
        {"name": _name("model-shared-task"), "form": shared_form},
    )
    model_only.save()
    model_shared.save()

    for entity in [
        model_only_project,
        shared_project,
        project_filter,
        model_only_form,
        shared_form,
        shared_category,
        model_only,
        model_shared,
    ]:
        _assert_saved(entity)

    assert {m.key for m in database_get.model_tasks(model_only_project)} == {
        model_only.key
    }
    assert {m.key for m in database_get.model_tasks(shared_project)} == {
        model_shared.key
    }

    Entities.delete(model_only_project)
    Entities.delete(shared_project)

    for entity in [
        model_only_project,
        shared_project,
        project_filter,
        model_only,
        model_shared,
        model_only_form,
    ]:
        _assert_deleted(entity)

    assert not database_get.filters(model_only_project.key)
    assert not database_get.model_tasks(model_only_project)
    assert not database_get.model_tasks(shared_project)

    _assert_saved(shared_form)
    _assert_saved(shared_category)
    assert database_get.entity(shared_form.key) is not None
    assert database_get.entity(shared_category.key) is not None
