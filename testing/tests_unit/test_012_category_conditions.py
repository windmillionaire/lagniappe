"""
``Condition.set_value`` → ``FilterDefinition`` on **Category** entities (``CategoryFilters``).

Exercises field binding, comparators, and ``filter_details`` for the page-filter field
surface. For **stored** saved filters and ``Condition.create``, see ``test_011_filters``.
For **project** and **form** field surfaces, see ``test_012a_project_conditions`` and
``test_012b_form_conditions``. For which fields exist on the model and child
``to_filter_index`` values, see ``test_007_category_properties``.
"""

import pytest


# @features category filters
# @dimensions condition-definition string
@pytest.mark.unit
def test_category_string_filters(get_test_entities, test_condition_definition):
    """Test STRING fields (name, description) with SUBSTRING and EQUALS comparators."""
    for entity in get_test_entities():
        test_condition_definition(entity)


# @features category filters
# @dimensions condition-definition boolean
@pytest.mark.unit
def test_category_boolean_filters(get_test_entities, test_condition_definition):
    """Test BOOLEAN fields (has_document, has_image, is_public) with IS_TRUE and IS_FALSE."""
    for entity in get_test_entities():
        test_condition_definition(entity)


# @features category filters
# @dimensions condition-definition timestamp
@pytest.mark.unit
def test_category_timestamp_filters(get_test_entities, test_condition_definition):
    """Test TIMESTAMP field (modified) with LESS_THAN, EQUALS, GREATER_THAN comparators."""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    with patch(
        "lagniappe.core.tools.dates.user_timezone", return_value=ZoneInfo("UTC")
    ):
        for entity in get_test_entities():
            test_condition_definition(entity)


# @features category filters
# @dimensions condition-definition entity-valued
@pytest.mark.unit
def test_category_entity_filters(get_test_entities, test_condition_definition):
    """Test entity-valued LIST field (categories) with single and multiple values."""
    entities = get_test_entities()
    # First entity is the condition entity (category being filtered)
    # Remaining entities are the filter value entities (categories to filter by)
    category = entities[0]
    filter_entities = entities[1:]

    # Build entity_map for the fixture
    entity_map = {e.hash: e for e in filter_entities}

    test_condition_definition(category, entity_map=entity_map)
