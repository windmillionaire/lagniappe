"""
``Condition.set_value`` → ``FilterDefinition`` on **Project** entities (``ProjectFilters``).

Covers task filter fields including model-task entity-valued rows. Complements
``test_012_category_conditions`` (category/pages) and ``test_012b_form_conditions`` (form
schema fields). Stored filter hydration is ``test_011_filters``; filter UI shape and
``to_filter_index`` on tasks are ``test_005_project_properties``.
"""

import pytest


# @features filters
# @dimensions condition-definition string
@pytest.mark.unit
def test_project_string_filters(get_test_entities, test_condition_definition):
    """Test STRING fields (name) with SUBSTRING and EQUALS comparators."""
    entities = get_test_entities()
    project = entities[0]
    test_condition_definition(project)


# @features filters
# @dimensions condition-definition timestamp
@pytest.mark.unit
def test_project_timestamp_filters(get_test_entities, test_condition_definition):
    """Test TIMESTAMP field (due_date) with various date comparators."""
    from unittest.mock import patch
    from zoneinfo import ZoneInfo

    with patch(
        "lagniappe.core.tools.dates.user_timezone", return_value=ZoneInfo("UTC")
    ):
        entities = get_test_entities()
        project = entities[0]
        test_condition_definition(project)


# @features filters
# @dimensions condition-definition entity-valued
@pytest.mark.unit
def test_project_entity_filters(get_test_entities, test_condition_definition):
    """Test entity-valued fields (categories, assigned_to) with single and multiple values."""
    entities = get_test_entities()
    project = entities[0]

    # Build entity_map from test entities for entity-valued field lookups
    entity_map = {e.hash: e for e in entities[1:]}

    test_condition_definition(project, entity_map=entity_map)


# @features filters
# @dimensions condition-definition model-task
@pytest.mark.unit
def test_project_model_filters(get_test_entities, test_condition_definition):
    """Test AttachedModelTask entity-valued field (one-to-one relation)."""
    entities = get_test_entities()
    project = entities[0]

    # Build entity_map from project's model_tasks
    entity_map = {m.hash: m for m in project.model_tasks}

    test_condition_definition(project, entity_map=entity_map)
