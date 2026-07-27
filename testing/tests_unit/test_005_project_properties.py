"""Unit tests for Project entity properties exercised via TestEntity harness.

Covers common mixins wired on ``Project`` in ``lagniappe/core/entities/project.py``:
Description, Document, IsPublic, Attributes, and ``ProjectFilters`` (conditions,
``entity_fields`` from attached model tasks/forms, and task ``to_filter_index``).

``ProjectFilters`` and ``ModelTasks`` live in ``lagniappe/core/properties/project.py``.
Production ``ModelTasks`` loads from the database; these tests inject ``model_tasks``
through the test entity JSON (see ``005_project_properties.json``).

``ModelTaskProject`` and ``ModelTaskForm`` in ``properties/project.py`` are used on
ModelTask entities; they are not asserted here—see task / model-task test modules.

Out of scope for this file: ``public_id``, ``ai_generated``, ``update`` / ``save`` /
``index``, and the production ``database.get.model_tasks`` path
(covered elsewhere or in e2e).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from google.cloud import datastore
import pytest

from lagniappe import CONFIG
from lagniappe.core.definitions import Action, Fetch, MutationEffectType, MutationOperation
from lagniappe.core.entities import Entities
from lagniappe.core.entities.model_task import ModelTask
from lagniappe.core.entities.project import Project
from lagniappe.core.mutations import plan_mutation

from testing.utility.test_entities import TestEntities, TestUser as UtilityTestUser


# @features project
# @dimensions description cache column ai-value filter-value html-stripping
@pytest.mark.unit
def test_project_description(get_test_entities):
    """Test Description property with CacheMixin, ColumnMixin, AIMixin, FilterMixin.

    Description has special behavior:
    - Setter strips HTML tags via utility.strip_tags
    - filter_value is lowercase
    - sort_value is boolean (True if has description)
    - cache_key is "desc"
    - ai_key is "Description" for PROJECT (uses label)
    """
    for project in get_test_entities():
        raw_value = project.test_spec.get("description")

        if "attributes" in project.test_spec:
            project.db["attributes"] = project.test_spec["attributes"]

        if raw_value:
            project.description = raw_value

            # Value should have HTML stripped (if any)
            # For plain text, value equals input
            # For HTML, tags are removed
            assert project.description == project.properties.description.value
            assert "<" not in (project.description or "")  # No HTML tags

            # FilterMixin - filter_value is lowercase
            assert (
                project.to_filter_index()["description"]
                == project.description
            )

            # sort_value is True when description exists
            assert project.properties.description.sort_value is True

            # CacheMixin - cache_key is "desc"
            assert project.to_cache["desc"] == project.description

            # AIMixin - default ai_key is the property id
            assert project.to_ai()["description"] == project.description

            # ColumnMixin - column_value returns entity.description
            assert project.column("description").column_value == project.description

        else:
            # No description case
            assert project.description is None
            assert project.properties.description.filter_value is None
            assert project.properties.description.sort_value is False
            assert project.properties.description.cache_value is None


# @features project
# @dimensions document cache ai-value filter-value
@pytest.mark.unit
def test_project_document(get_test_entities):
    """Test Document property with CacheMixin, FilterMixin, AIMixin.

    Document has special behavior:
    - filter_value is boolean (True if entity.assets has "document")
    - cache_value and ai_value use entity.text_for_cache("document")
    - cache_key is "doc"
    - filter_key is "has_document"
    """
    for project in get_test_entities():
        if "attributes" in project.test_spec:
            project.db["attributes"] = project.test_spec["attributes"]
        document_text = project.text_for_cache("document")

        # FilterMixin - filter_value is boolean
        if document_text:
            assert project.to_filter_index()["has_document"] is True
            # CacheMixin
            assert project.to_cache.get("doc") == document_text
            # AIMixin
            assert project.to_ai()["project_document"] == document_text
        else:
            assert project.to_filter_index()["has_document"] is False


# @features project
# @dimensions document-state markup-fallback
@pytest.mark.unit
def test_project_document_state_uses_markup_when_no_ydoc():
    """Project document state falls back to saved HTML when no YDoc snapshot exists."""
    project = Project(testing=True)
    project.modified = datetime(2026, 6, 30, tzinfo=timezone.utc)
    project.allowed = lambda *_args, **_kwargs: True
    document = project.properties.document
    document._ydoc = None
    document._html = "<p>Readonly project document content marker</p>"

    state = project.state("project:document")

    assert state["ydoc"] is None
    assert state["markup"] == "<p>Readonly project document content marker</p>"


# @features project
# @dimensions public filter-value
@pytest.mark.unit
def test_project_is_public(get_test_entities):
    """Test IsPublic property with FilterMixin.

    IsPublic has:
    - filter_value is boolean
    - filter_key is "is_public"
    - Value reads from entity.db["public"]
    """
    for project in get_test_entities():
        is_public = project.test_spec.get("public", False)

        # Set public in db if specified in test_spec
        if "public" in project.test_spec:
            project.db["public"] = is_public

        # property value
        assert project.properties.is_public.value == project.is_public == is_public

        # Filter index
        assert project.to_filter_index()["is_public"] is is_public


# @features project
# @dimensions attributes defaults
@pytest.mark.unit
def test_project_attributes(get_test_entities):
    """Test Attributes property with FilterMixin.

    Attributes has:
    - filter_value is boolean
    - filter_key is "attributes"
    - Value reads from entity.db["attributes"]
    """
    for project in get_test_entities():
        if "attributes" in project.test_spec:
            project.db["attributes"] = project.test_spec["attributes"]
        else:
            assert project.has("tasks") is True
            assert project.has("document") is True
            continue

        assert project.has("tasks") == ("tasks" in project.db["attributes"])
        assert project.has("document") == ("document" in project.db["attributes"])


# @features project
# @dimensions attributes blank-persistence
@pytest.mark.unit
def test_project_attributes_empty_list_stays_persisted():
    """An explicit empty attributes list is distinct from missing attributes."""
    project = TestEntities.get(
        "PROJECT",
        {
            "name": "No attributes",
            "hash": "proj_attrs_empty",
            "attributes": [],
        },
    )

    project.attributes = []

    assert [a.name for a in project.attributes if a.active] == []
    assert project.db["attributes"] == []
    assert project.has("tasks") is False
    assert project.has("document") is False


# @features project filters task
# @dimensions conditions entity-fields filter-value
@pytest.mark.unit
def test_project_filters(get_test_entities, get_schema):
    """Test ProjectFilters produces filter conditions and tasks have correct filter values.

    ProjectFilters filter fields: Name, Categories, AssignedTo, DueDate,
    Completed, HasSignature, HasStatus.
    Plus AttachedModelTask and AttachedForm for each model_task.

    Tests both the project.filters.conditions structure and that tasks attached
    to the project produce correct filter_key/filter_value pairs.
    """
    entities = get_test_entities()
    projects = [e for e in entities if e.entity_kind == "project"]
    tasks = [e for e in entities if e.entity_kind == "task"]

    # set schema on model task forms
    for project in projects:
        project.name = project.test_spec.get("name")
        for model in project.model_tasks:
            if model.form:
                model.form.schema = get_schema(model.test_spec["form"]["schema"])

    model_tasks = {
        model.hash: model for project in projects for model in project.model_tasks
    }

    # set task properties and schemas on task forms
    for task in tasks:
        task.name = task.test_spec.get("name")
        if "model" in task.test_spec:
            task.properties.model._value = model_tasks.get(
                task.test_spec["model"]["hash"]
            )
        if "completed" in task.test_spec:
            task.db["completed"] = task.test_spec["completed"]
        if task.form and "form" in task.test_spec:
            task.form.schema = get_schema(task.test_spec["form"]["schema"])

    for project in projects:
        # attach all tasks to this project
        for task in tasks:
            task.properties.project._value = project

        # verify project.filters.conditions structure
        conditions = project.filters.conditions
        # Base: 7 (Name, Categories, AssignedTo, DueDate, Completed,
        # HasSignature, HasStatus)
        # Plus: 1 AttachedModelTask per model + 1 AttachedForm per model with form
        model_count = len(project.model_tasks)
        form_count = len([m for m in project.model_tasks if m.form])
        expected_count = 7 + model_count + form_count
        assert len(conditions) == expected_count

        base_keys = {"field", "label", "kind", "icon"}
        entity_keys = base_keys | {"hash", "key"}
        for cond in conditions:
            assert cond.keys() in (base_keys, entity_keys), (
                f"Unexpected condition keys: {set(cond.keys())}"
            )

        # verify set_field_attributes modifications
        name_field = project.filters.fields["name"]
        assert name_field.filter_label == "Task Name"
        assert name_field.filter_kind == "task"

        signature_field = project.filters.fields["has_signature"]
        assert signature_field.filter_label == "Has Signature"
        assert signature_field.filter_kind == "task"

        status_field = project.filters.fields["has_status"]
        assert status_field.filter_label == "Has Status"
        assert status_field.filter_kind == "task"

        completed_field = project.filters.fields["completed"]
        assert completed_field.filter_label == "Completed"
        assert completed_field.filter_kind == "task"

        # verify model tasks in entity_fields (keyed by entity hash)
        for model in project.model_tasks:
            assert model.hash in project.filters.entity_fields
            model_field = project.filters.entity_fields[model.hash]
            assert model_field.filter_label == model.name

            if model.form:
                assert model.form.hash in project.filters.entity_fields
                form_field = project.filters.entity_fields[model.form.hash]
                assert form_field.filter_label == model.form.name

        # test filter values on tasks
        for task in tasks:
            task_index = task.to_filter_index()

            for f in project.properties.filters.conditions:
                field_key = f["field"]
                if "hash" in f:
                    # entity-valued condition (model or form)
                    if field_key == "model" and task.model:
                        assert task_index["model"] == task.properties.model.filter_value
                    elif field_key == "form" and task.form:
                        assert task_index["form"] == task.properties.form.filter_value
                elif field_key == "categories":
                    assert task_index.get(field_key, []) == [
                        c.hash for c in task.categories
                    ]
                elif field_key in project.filters.fields:
                    property_id = project.filters.fields[field_key].id
                    if task.properties.get(property_id) and field_key in task_index:
                        assert (
                            task_index[field_key]
                            == task.properties[property_id].filter_value
                        )


# @features project filters permissions
# @dimensions conditions entity-fields view-access
@pytest.mark.unit
def test_project_filter_conditions_include_only_viewable_entity_fields(monkeypatch):
    viewer = UtilityTestUser(
        owner=False, permissions={"models": "VIEW", "forms": "VIEW"}
    )
    monkeypatch.setattr(CONFIG, "TEST_CURRENT_USER", viewer)

    project = Project(testing=True)
    project._key = datastore.Key("models", "filter-project", project="test")
    project.db.update(
        {"name": "Filter Project", "hash": "filter_project", "type": "project"}
    )

    visible_form = TestEntities.get(
        "FORM", {"name": "Visible Form", "hash": "visible_form"}
    )
    hidden_form = TestEntities.get(
        "FORM",
        {
            "name": "Hidden Form",
            "hash": "hidden_form",
            "restricted_to": ["restricted_group"],
        },
    )

    visible_model = ModelTask(testing=True)
    visible_model._key = datastore.Key("models", "visible-model", project="test")
    visible_model.db.update(
        {"name": "Visible Model", "hash": "visible_model", "type": "model"}
    )
    visible_model.project = project
    visible_model.form = visible_form

    hidden_model = ModelTask(testing=True)
    hidden_model._key = datastore.Key("models", "hidden-model", project="test")
    hidden_model.db.update(
        {"name": "Hidden Model", "hash": "hidden_model", "type": "model"}
    )
    hidden_model.project = project
    hidden_model.form = hidden_form

    project.properties.model_tasks._value = [visible_model, hidden_model]

    entity_hashes = {
        condition["hash"]
        for condition in project.filters.conditions
        if "hash" in condition
    }

    assert visible_model.hash in entity_hashes
    assert visible_form.hash in entity_hashes
    assert hidden_model.hash not in entity_hashes
    assert hidden_form.hash not in entity_hashes


# @features project model-task permissions
# @dimensions attached-form restricted-access
@pytest.mark.unit
def test_model_task_allowed_inherits_attached_form_restrictions():
    viewer = UtilityTestUser(
        owner=False, permissions={"models": "VIEW", "forms": "VIEW"}
    )
    project = TestEntities.get(
        "PROJECT", {"name": "Restricted Form Project", "hash": "restricted_project"}
    )
    restricted_form = TestEntities.get(
        "FORM",
        {
            "name": "Restricted Form",
            "hash": "restricted_form",
            "restricted_to": ["restricted_group"],
        },
    )
    model = ModelTask(testing=True)
    model._key = datastore.Key("models", "restricted-model", project="test")
    model.db.update(
        {"name": "Restricted Model", "hash": "restricted_model", "type": "model"}
    )
    model.project = project
    model.form = restricted_form

    assert model.restricted_to == ["restricted_group", "owner"]
    assert not model.allowed(Action.VIEW, user=viewer)


# @features project
# @dimensions model-tasks db-load relation-attach ordering
@pytest.mark.unit
def test_model_tasks_load_attach_and_order_from_database():
    """ModelTasks lazy-loads project children, attaches parent, and orders appends."""
    project = Project(testing=True)
    project._key = "prj005a"
    project.db.update({"hash": "prj005a", "name": "Project"})
    model_one = ModelTask(testing=True)
    model_one._key = "mdl005a"
    model_one.db.update({"name": "One", "hash": "mdl005a", "type": "model"})
    model_two = ModelTask(testing=True)
    model_two._key = "mdl005b"
    model_two.db.update({"name": "Two", "hash": "mdl005b", "type": "model"})
    non_model = TestEntities.get("PAGE", {"name": "Not a model", "hash": "pg005a"})
    model_one.db["project"] = project.key

    with patch(
        "lagniappe.core.properties.project.database.get.model_tasks",
        return_value=["model-key", "page-key"],
    ) as get_model_tasks:
        def load_entities(*args, **kwargs):
            model_one.attach({project.key: project})
            return [model_one, non_model]

        with patch(
            "lagniappe.core.properties.project.Entities.fetch",
            side_effect=load_entities,
        ) as load:
            models = project.model_tasks

    get_model_tasks.assert_called_once_with(project)
    load.assert_called_once_with(
        "model-key", "page-key", project, request=Fetch.direct()
    )
    assert models == [model_one]
    assert model_one.project is project
    assert project.properties.model_tasks.value is models

    project.properties.model_tasks.add(model_two)

    assert project.model_tasks == [model_one, model_two]
    assert model_two.order == 2


# @features project
# @dimensions update identity attributes description
@pytest.mark.unit
def test_project_update_sets_identity_description_and_attributes():
    """Project.update owns identity, description normalization, and attributes."""
    project = Project(testing=True)

    project.update(
        {
            "name": "Updated Project",
            "description": "<p>Safe <strong>description</strong></p>",
            "attributes": ["tasks"],
        }
    )

    assert project.name == "Updated Project"
    assert project.description == "Safe description"
    assert project.db["attributes"] == ["tasks"]
    assert project.has("tasks")
    assert not project.has("document")


# @features project model-task
# @dimensions create update relation-save ordering
@pytest.mark.unit
def test_model_task_entity_create_update_order_and_save_relations():
    """ModelTask.create/update/order/save remain focused on model-task relations."""
    project = Project(testing=True)
    project._key = "prj005b"
    project.db.update({"hash": "prj005b", "name": "Project"})
    form = TestEntities.get("FORM", {"name": "Task Form", "hash": "frm005b"})
    created_db = {}

    with patch(
        "lagniappe.core.entities.entity.database.create_key",
        return_value=SimpleNamespace(parent=project.key),
    ):
        with patch("lagniappe.core.entities.entity.database.get.entity", return_value=None):
            with patch(
                "lagniappe.core.entities.entity.database.create_entity",
                return_value=created_db,
            ):
                model = ModelTask.create(
                    project,
                    {"name": "Inspection", "form": form},
                )

    assert model.kind == "model"
    assert model.project is project
    assert model.name == "Inspection"
    assert model.form is form
    assert project.model_tasks == [model]
    assert model.order == 1
    assert model.db["order"] == 1

    model.order = "4"
    model.update({"name": "Updated Inspection", "form": None})

    assert model.order == 4
    assert model.name == "Updated Inspection"
    assert model.form is None

    model.form = form
    with patch("lagniappe.core.entities.entity.Entities.save") as save:
        model.save()

    save.assert_called_once_with(model)

    model._key = "model-task-plan-key"
    plan = plan_mutation(MutationOperation.SAVE, model, registry=Entities)
    writes = {
        effect.entity.key: effect
        for effect in plan.effects
        if effect.effect is MutationEffectType.UPSERT
    }
    assert writes[model.key].property_mask is None
    assert writes[project.key].property_mask == ("modified",)
    assert writes[form.key].property_mask == ("modified",)


# @features project
# @dimensions model-task-parent details attach
@pytest.mark.unit
def test_model_task_project_parent_details_and_attach():
    """ModelTaskProject resolves stored project keys for details/attach."""
    project = Project(testing=True)
    project._key = "prj005c"
    project._urlsafe_key = "project-url"
    project.db.update(
        {"hash": "prj005c", "name": "Parent Project", "type": "project"}
    )
    model = ModelTask(testing=True)
    model._key = "mdl005c"
    model._urlsafe_key = "model-url"
    model.db.update(
        {
            "hash": "mdl005c",
            "name": "Model Task",
            "project": project.key,
            "type": "model",
        }
    )

    model.properties.project.attach({project.key: project})

    assert model.project is project
    assert model.properties.project.details_key == "parent"
    assert model.details["parent"] == project.reference_details

    unlinked_model = ModelTask(testing=True)
    unlinked_model.properties.project.attach({project.key: project})

    assert unlinked_model.project is None
