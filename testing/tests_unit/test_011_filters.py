"""
Stored Filter entity: definitions and ``Filter.conditions``.

``Filter.conditions`` builds an ``entity_map`` from ``filter.related`` (production:
entities referenced by saved definitions) and materializes each row via
``Condition.create(definition, entity_map)``.

This is **not** the same as ``test_005*`` / ``test_007*`` (``ProjectFilters`` /
``CategoryFilters`` metadata and child ``to_filter_index``), nor ``test_012*``
(``Condition.set_value`` → ``FilterDefinition`` on a live category/project/form).

Fixtures in ``011_filters.json`` use ``related_hashes`` so each test can populate
``filter.related`` the same way production references condition entities before
reading ``Filter.conditions``.
"""

import hashlib
from datetime import datetime, timezone

import pytest

from lagniappe.core.definitions import Action, Comparator, FieldType, FilterDefinition
from lagniappe.core.entities.condition import Condition
from lagniappe.core.entities.filter import Filter as FilterEntity
from lagniappe.core.properties.filter import FilterTable
from lagniappe.core.tools.filters.build import FilterExpression
from testing.utility.test_entities import TestEntities, TestUser as UtilityTestUser


class _FilterTableEntity:
    entity_kind = "filter"

    def __init__(self, parent, related=()):
        self.parent = parent
        self.related = list(related)


def _prepare_saved_filter(filter_entity, entity_map):
    """Match production: ``related`` supplies hashes for ``Filter.conditions``."""
    hashes = filter_entity.test_spec.get("related_hashes", [])
    filter_entity.properties.related.value = [entity_map[h] for h in hashes]
    filter_entity._conditions = None
    definitions = [
        FilterDefinition.load(d) for d in filter_entity.test_spec["definitions_input"]
    ]
    filter_entity.definitions = definitions
    filter_entity._conditions = None


# @features filters
# @dimensions condition-definition validation
@pytest.mark.unit
def test_condition_requires_field_for_type_and_definition():
    condition = Condition()

    with pytest.raises(ValueError, match="Field not set"):
        _ = condition.field_type

    with pytest.raises(ValueError, match="Field not set"):
        condition._create_definition()


# @pair filter:missing-entity
@pytest.mark.unit
def test_condition_create_skips_missing_entity_reference():
    definition = FilterDefinition(
        "missing-entity",
        "name",
        FieldType.STRING,
        Comparator.EQUALS,
        "Example",
        False,
    )

    assert Condition.create(definition, {}) is None


# @features filter
# @dimensions conditions string
@pytest.mark.unit
def test_filter_conditions_string(get_test_entities):
    """String field: entity, field object, comparator, value from definition."""
    entities = get_test_entities()
    filters = [e for e in entities if e.entity_kind == "filter"]
    entity_map = {e.hash: e for e in entities if e.entity_kind != "filter"}

    for filter_entity in filters:
        _prepare_saved_filter(filter_entity, entity_map)

        for i, expected in enumerate(filter_entity.test_spec["expected_conditions"]):
            cond = filter_entity.conditions[i]

            assert cond.entity is not None
            assert cond.entity.hash == expected["entity_hash"]
            assert cond.entity is entity_map[expected["entity_hash"]]

            assert cond.field is not None
            assert hasattr(cond.field, "filter_key")
            assert cond.field.filter_key == expected["field"]
            assert cond.field is cond.entity.filters.fields[expected["field"]]

            assert isinstance(cond.comparator, Comparator)
            assert cond.comparator.name == expected["comparator"]

            assert cond.value == expected["value"]


# @features filter
# @dimensions conditions boolean
@pytest.mark.unit
def test_filter_conditions_boolean(get_test_entities):
    """Boolean field: comparator only; stored definition omits value."""
    entities = get_test_entities()
    filters = [e for e in entities if e.entity_kind == "filter"]
    entity_map = {e.hash: e for e in entities if e.entity_kind != "filter"}

    for filter_entity in filters:
        _prepare_saved_filter(filter_entity, entity_map)

        for i, expected in enumerate(filter_entity.test_spec["expected_conditions"]):
            cond = filter_entity.conditions[i]

            assert cond.entity is entity_map[expected["entity_hash"]]
            assert cond.field is cond.entity.filters.fields[expected["field"]]

            assert isinstance(cond.comparator, Comparator)
            assert cond.comparator.name == expected["comparator"]

            assert cond.value is None


# @features filter
# @dimensions conditions entity-valued
@pytest.mark.unit
def test_filter_conditions_entity_valued(get_test_entities):
    """Entity-valued list field: value hash(es) resolvable from ``related`` map."""
    entities = get_test_entities()
    filters = [e for e in entities if e.entity_kind == "filter"]
    entity_map = {e.hash: e for e in entities if e.entity_kind != "filter"}

    for filter_entity in filters:
        _prepare_saved_filter(filter_entity, entity_map)

        for i, expected in enumerate(filter_entity.test_spec["expected_conditions"]):
            cond = filter_entity.conditions[i]

            assert cond.entity is entity_map[expected["entity_hash"]]
            assert cond.field is cond.entity.filters.fields[expected["field"]]
            assert cond.field.is_entity_valued

            assert isinstance(cond.comparator, Comparator)
            assert cond.comparator.name == expected["comparator"]

            assert cond.value == expected["value"]

            value_hashes = cond.value if isinstance(cond.value, list) else [cond.value]
            for h in value_hashes:
                assert h in cond.entity_map, f"Value hash {h} not in entity_map"
                assert cond.entity_map[h] is entity_map[h]


# @features filter
# @dimensions conditions mixed-types
@pytest.mark.unit
def test_filter_conditions_multiple_types(get_test_entities):
    """Mixed string, boolean, and entity-valued rows on one filter."""
    entities = get_test_entities()
    filters = [e for e in entities if e.entity_kind == "filter"]
    entity_map = {e.hash: e for e in entities if e.entity_kind != "filter"}

    for filter_entity in filters:
        _prepare_saved_filter(filter_entity, entity_map)

        for i, expected in enumerate(filter_entity.test_spec["expected_conditions"]):
            cond = filter_entity.conditions[i]

            assert cond.entity is entity_map[expected["entity_hash"]]

            assert cond.field is cond.entity.filters.fields[expected["field"]]

            assert isinstance(cond.comparator, Comparator)
            assert cond.comparator.name == expected["comparator"]

            assert cond.value == expected.get("value")

            if expected.get("is_entity_valued"):
                value_hashes = (
                    cond.value if isinstance(cond.value, list) else [cond.value]
                )
                for h in value_hashes:
                    assert h in cond.entity_map


# @features filters
# @dimensions scalar-list
@pytest.mark.unit
def test_filter_expression_list_contains_accepts_scalar_form_values():
    """List-style contains filters match scalar single-select form submissions."""
    definition = FilterDefinition(
        "form_hash",
        "filter-decision",
        FieldType.LIST,
        Comparator.CONTAINS,
        "approved",
        False,
    )

    expression = FilterExpression([definition]).build()

    assert "@.filter-decision[?(@=='approved')]" in expression
    assert "@.filter-decision == 'approved'" in expression


# @features filter
# @dimensions parent parent-hash
@pytest.mark.unit
def test_filter_parent_sets_parent_hash():
    filter_entity = FilterEntity(testing=True)
    parent = TestEntities.get(
        "PROJECT",
        {"name": "Parent Project", "hash": "parent_project"},
    )
    parent_property = filter_entity.properties.parent

    parent_property.value = parent

    assert parent_property.value is parent
    assert filter_entity.db["parent"] == parent.key
    assert filter_entity.db["parent_hash"] == parent.hash

    parent_property.value = None

    assert parent_property.value is None
    assert "parent" not in filter_entity.db
    assert "parent_hash" not in filter_entity.db


# @features filter
# @dimensions fingerprint parent
@pytest.mark.unit
def test_filter_fingerprint_uses_loaded_parent_fingerprint(monkeypatch):
    filter_entity = FilterEntity(testing=True)
    parent = TestEntities.get(
        "PROJECT",
        {"name": "Fingerprint Parent", "hash": "parent_fingerprint"},
    )
    filter_entity.modified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    filter_entity.parent = parent

    def fail_cache_lookup(*args, **kwargs):
        raise AssertionError("filter fingerprint should use the loaded parent")

    monkeypatch.setattr(
        "lagniappe.core.entities.filter.cache.get_details_by_hash",
        fail_cache_lookup,
    )

    expected = hashlib.md5(
        f"{super(FilterEntity, filter_entity).fingerprint}:{parent.fingerprint}".encode(
            "utf-8"
        )
    ).hexdigest()

    assert filter_entity.fingerprint == expected


# @features filter permissions
# @dimensions saved-filters related-entities
@pytest.mark.unit
def test_filter_related_entities_allowed_checks_referenced_entities():
    filter_entity = FilterEntity(testing=True)
    visible = TestEntities.get("FORM", {"name": "Visible Form", "hash": "visible"})
    hidden = TestEntities.get("FORM", {"name": "Hidden Form", "hash": "hidden"})
    visible.allowed = lambda action, user=None: True
    hidden.allowed = lambda action, user=None: False

    filter_entity.related = [visible]

    assert filter_entity.related_entities_allowed()

    filter_entity.related = [visible, hidden]

    assert not filter_entity.related_entities_allowed()


# @features filter permissions
# @dimensions saved-filters related-entities model-task restricted-access
@pytest.mark.unit
def test_filter_related_entities_allowed_checks_model_task_form_restrictions():
    viewer = UtilityTestUser(
        owner=False, permissions={"models": "VIEW", "forms": "VIEW"}
    )
    project = TestEntities.get(
        "PROJECT", {"name": "Project", "hash": "filter_project"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {
            "name": "Restricted Model",
            "hash": "restricted_model",
            "form": {
                "name": "Restricted Form",
                "hash": "restricted_form",
                "restricted_to": ["restricted_group"],
            },
        },
        project=project,
    )
    _ = model.form
    filter_entity = FilterEntity(testing=True)
    filter_entity.related = [model]

    assert not model.allowed(Action.VIEW, user=viewer)
    assert not filter_entity.related_entities_allowed(viewer)


# @features filter
# @dimensions table category project related-forms
@pytest.mark.unit
def test_filter_table_derives_parent_fields_and_related_forms(get_schema):
    primary_form = TestEntities.get(
        "FORM",
        {"name": "Primary Form", "hash": "primary_table_form"},
    )
    primary_form.schema = get_schema("integration_one_text")
    related_form = TestEntities.get(
        "FORM",
        {"name": "Related Form", "hash": "related_table_form"},
    )
    related_form.schema = get_schema("number_input_only")
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Parent Category", "hash": "filter_category"},
    )
    category.form = primary_form
    project = TestEntities.get(
        "PROJECT",
        {"name": "Parent Project", "hash": "filter_project"},
    )

    category_table = FilterTable(
        entity=_FilterTableEntity(category, related=[related_form])
    )
    project_table = FilterTable(
        entity=_FilterTableEntity(project, related=[related_form])
    )

    assert category_table.kind == "page"
    assert category_table.fields["name"].parent is False
    assert category_table.fields["name"].selected is True
    assert "note" in category_table.fields
    assert "input-numab12" in category_table.fields
    assert category_table.fields["input-numab12"].selected is False

    assert project_table.kind == "task"
    assert project_table.fields["name"].parent is True
    assert project_table.fields["name"].selected is True
    assert "due_date" in project_table.fields
    assert "input-numab12" in project_table.fields
    assert project_table.fields["input-numab12"].selected is False
