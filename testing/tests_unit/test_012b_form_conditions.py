"""
``Condition.set_value`` → ``FilterDefinition`` when the filtered **entity** is a **Form**.

Uses ``get_schema`` for schema-driven filter fields (string, boolean, number,
select, radio). Status is asserted separately as a computed non-filter field.
Category/project surfaces that attach forms are covered in ``012`` /
``012a``; this module isolates the form-as-target case. Saved ``Filter.conditions``:
``test_011_filters``.
"""

import json

import pytest

from lagniappe.core.definitions import FilterDefinition
from lagniappe.core.entities.condition import Condition
from lagniappe.core.entities.filter import Filter
from testing.utility.test_entities import TestEntities


# @matrix filters : condition-definition number round-trip zero
@pytest.mark.unit
@pytest.mark.parametrize("comparator, serialized", [
    ("EQUALS", "eq"), ("LESS_THAN", "lt"), ("GREATER_THAN", "gt"),
])
def test_zero_number_condition_survives_saved_filter_serialization(comparator, serialized):
    form = TestEntities.get("FORM", {"name": "Amounts", "hash": "amount-form"})
    form.schema = [{"id": "amount", "type": "input", "input": "number", "title": "Amount"}]
    condition = Condition()
    condition.entity = form
    condition.field = "amount"
    condition.set_value("0", default_comparator=comparator)
    assert condition.value == 0.0

    saved_filter = Filter(testing=True)
    saved_filter.definitions = [condition.definition]
    stored = json.loads(saved_filter.db["definitions"])
    assert stored == [["amount-form", "amount", "number", serialized, 0.0]]
    restored = Condition.create(FilterDefinition.load(stored[0]), {form.hash: form})
    assert restored.value == 0.0
    assert restored.comparator.value == serialized


# @matrix filters : condition-definition string
@pytest.mark.unit
def test_form_string_filters(get_test_entities, get_schema, test_condition_definition):
    """Test STRING form fields (TextInput) with SUBSTRING and EQUALS comparators."""
    entities = get_test_entities()
    form = entities[0]
    form.schema = get_schema(form.test_spec["schema"])
    test_condition_definition(form)


# @matrix filters : boolean condition-definition
@pytest.mark.unit
def test_form_boolean_filters(get_test_entities, get_schema, test_condition_definition):
    """Test BOOLEAN form fields (Checkbox) with IS_TRUE and IS_FALSE comparators."""
    entities = get_test_entities()
    form = entities[0]
    form.schema = get_schema(form.test_spec["schema"])
    test_condition_definition(form)


# @matrix filters : condition-definition timestamp
@pytest.mark.unit
def test_form_timestamp_filters(
    get_test_entities, get_schema, test_condition_definition, monkeypatch
):
    """Test TIMESTAMP form fields (DateInput, TimeInput) with date comparators."""
    import time

    # TimeInput uses naive datetime.timestamp(); isolate the process timezone.
    # DateInput separately uses the shared fixture's fixed Chicago clock.
    with monkeypatch.context() as environment:
        environment.setenv("TZ", "UTC")
        time.tzset()
        try:
            form = get_test_entities()[0]
            form.schema = get_schema(form.test_spec["schema"])
            test_condition_definition(form)
        finally:
            environment.undo()
            time.tzset()


# @matrix filters : condition-definition entity-valued
@pytest.mark.unit
def test_form_internal_link_filters(
    get_test_entities, get_schema, test_condition_definition
):
    """Test internal Link fields with single and multiple entity-valued hashes."""
    entities = get_test_entities()
    form = entities[0]
    form.schema = get_schema(form.test_spec["schema"])
    entity_map = {entity.hash: entity for entity in entities[1:]}
    test_condition_definition(form, entity_map=entity_map)


# @matrix filters : condition-definition number
@pytest.mark.unit
def test_form_number_filters(get_test_entities, get_schema, test_condition_definition):
    """Test NUMBER form fields (NumberInput) with EQUALS, LT, GT, BETWEEN comparators."""
    entities = get_test_entities()
    form = entities[0]
    form.schema = get_schema(form.test_spec["schema"])
    test_condition_definition(form)


# @matrix filters : categorical condition-definition
@pytest.mark.unit
def test_form_categorical_filters(
    get_test_entities, get_schema, test_condition_definition
):
    """Test categorical form fields (Radio) with single and multiple values."""
    entities = get_test_entities()
    form = entities[0]
    form.schema = get_schema(form.test_spec["schema"])
    test_condition_definition(form)


# @matrix filters status : form-filters status-excluded
@pytest.mark.unit
def test_form_status_filters(get_test_entities, get_schema):
    """Status fields are computed columns, not form-level filter conditions."""
    entities = get_test_entities()
    assert entities
    for form in entities:
        form.schema = get_schema(form.test_spec["schema"])
        status_ids = [
            field["id"] for field in form.schema if field.get("type") == "status"
        ]

        assert status_ids
        for status_id in status_ids:
            assert status_id not in form.properties.filters.fields

        condition_fields = {
            condition["field"] for condition in form.properties.filters.conditions
        }
        assert not condition_fields.intersection(status_ids)


# @matrix filters select : condition-definition multiple select
@pytest.mark.unit
def test_form_select_filters(get_test_entities, get_schema, test_condition_definition):
    """Test Select form fields - single-select (STRING) and multi-select (LIST)."""
    entities = get_test_entities()
    assert entities
    for form in entities:
        form.schema = get_schema(form.test_spec["schema"])
        test_condition_definition(form)
