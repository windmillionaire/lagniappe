"""Filter condition representation.

filter_key must be consistent across: entity.to_filter_index() (cache write),
FilterDefinition.field (stored query), and frontend form input names.
For most fields id == filter_key; EntityForm is the exception (id="form-{hash}"
but filter_key="form").
"""

from flask_login import current_user
from ..definitions import Comparator, Fetch, FieldType, FilterDefinition
from ..entities import Entities
from ..properties.form_select import CategoricalElement
from ..tools import cache


# @testable true
# @tests tests_unit/test_011_filters.py::test_filter_conditions_multiple_types
# @tests tests_unit/test_011_filters.py::test_condition_create_skips_missing_entity_reference
# @features filter
# @dimensions conditions mixed-types missing-entity
class Condition:
    """A single filter condition: entity + field + comparator + value.

    Created from a FilterDefinition. The field (a FilterMixin property)
    determines the available comparators, value transformation, and
    whether values are entity hashes requiring lookup.
    """

    def __init__(self, definition=None):
        self._entity = None
        self._definition = definition
        self._field = None
        self._entity_map = {}
        self._condition_value = None

    @property
    def hashes(self):
        hashes = set()
        definition = self.definition
        if not definition:
            return hashes

        hashes.add(definition.entity_hash)
        if definition.is_entity_valued and isinstance(definition.value, list):
            hashes.update(definition.value)
        elif definition.is_entity_valued and isinstance(definition.value, str):
            hashes.add(definition.value)

        return hashes

    @classmethod
    def create(cls, definition, entity_map):
        """Populate entity, field, comparator, and value from a loaded entity hash map."""
        condition = cls(definition)

        if not condition.entity:
            entity_hash = definition.entity_hash
            entity = entity_map.get(entity_hash)
            if not entity:
                return None
            condition.entity = entity

        if definition.field in condition.entity.filters.fields:
            condition.field = definition.field
        elif definition.value in condition.entity.filters.entity_fields:
            condition.field = definition.value

        if not condition.entity or not condition.field:
            return None

        condition.comparator = definition.comparator.name
        condition.entity_map = entity_map
        condition._condition_value = definition.value
        return condition

    @property
    def description(self):
        description = self._definition.description if self._definition else {}
        return description

    @property
    def contract_condition(self):
        """Return the explicit v1 DTO without client-controlled type metadata."""
        if not self._definition:
            return {}
        from ..tools.filters.contract import condition_contract

        return condition_contract(self._definition)

    @property
    def definition(self):
        return self._definition

    @property
    def options(self):
        return self.field.field_options

    @property
    def entity(self):
        return self._entity

    @entity.setter
    def entity(self, entity):
        self._entity = entity
        self.entity_map[entity.hash] = entity

    @property
    def entity_map(self):
        return self._entity_map

    @entity_map.setter
    def entity_map(self, entity_map):
        self._entity_map = entity_map

    @property
    def value(self):
        return self._condition_value

    @property
    def value_list(self):
        return self.value if isinstance(self.value, list) else [self.value]

    @value.setter
    def value(self, value_list):
        normalized = []
        for v in [v for v in value_list if v]:
            if self.field.is_entity_valued or getattr(
                self.field, "_is_categorical", False
            ):
                normalized.append(v)
            else:
                self.field.value = v
                normalized.append(self.field.filter_value)

        normalized = sorted(normalized)

        if not normalized:
            self._condition_value = None
        elif self.field_type == FieldType.LIST and len(normalized) > 1:
            self._comparator = Comparator.CONTAINS_ANY
            self._condition_value = normalized
        elif self.field_type == FieldType.LIST and len(normalized) == 1:
            self._comparator = Comparator.CONTAINS
            self._condition_value = normalized[0]
        elif self.field_type == FieldType.STRING and len(normalized) > 1:
            self._comparator = Comparator.IN
            self._condition_value = normalized
        elif self.field_type != FieldType.LIST and len(normalized) == 1:
            self._condition_value = normalized[0]
        else:
            self._condition_value = normalized

    @property
    def details(self):
        if getattr(self, "_details", None):
            return self._details

        load_entities = set(self.value_list) - set(self.entity_map.keys())
        if self.field.is_entity_valued and load_entities:
            details = cache.get_details_by_hash(load_entities)
            entities = [
                Entities.fetch_one(d["id"], request=Fetch.direct())
                for d in details.values()
            ]
            self.entity_map.update({e.hash: e for e in entities})

        self._details = self.field.filter_details(self)

        return self._details

    # @testable true
    # @tests tests_unit/test_012_category_conditions.py::*
    # @tests tests_unit/test_012a_project_conditions.py::*
    # @tests tests_unit/test_012b_form_conditions.py::*
    # @features filters
    # @dimensions condition-definition string boolean timestamp entity-valued model-task number categorical select multiple
    def set_value(self, form_values, default_comparator=None):
        """Set condition value from form input and create the FilterDefinition."""
        form_values = form_values if isinstance(form_values, list) else [form_values]

        if not self.field:
            raise ValueError("Field not set")

        if self.field_type == FieldType.BOOLEAN:
            self._comparator = Comparator[form_values[0]]
        else:
            self.value = form_values

        if not getattr(self, "_comparator", None) and default_comparator:
            self._comparator = Comparator[default_comparator]

        self._create_definition()

    @property
    def choices(self):
        return self.field.choices

    @property
    def field(self):
        return self._field

    @field.setter
    def field(self, name):
        if self.entity.filters.fields.get(name):
            field = self.entity.filters.fields[name]
        elif hasattr(self.entity, "table_fields") and name in self.entity.table_fields:
            field = self.entity.table_fields[name]
        elif self.entity.filters.visible_entity_fields.get(name):
            field = self.entity.filters.visible_entity_fields[name]
            field.user = current_user
        else:
            raise ValueError("Field not found: " + name)

        self._field = field
        if isinstance(field, CategoricalElement):
            field.multiple = True

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_condition_requires_field_for_type_and_definition
    # @features filters
    # @dimensions condition-definition validation
    @property
    def field_type(self):
        if not self.field:
            raise ValueError("Field not set")
        return self.field.field_type

    @property
    def comparator(self):
        return getattr(self, "_comparator", Comparator.EQUALS)

    @comparator.setter
    def comparator(self, name):
        self._comparator = Comparator[name]

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_condition_requires_field_for_type_and_definition
    # @features filters
    # @dimensions condition-definition validation
    def _create_definition(self):
        if not self.field:
            raise ValueError("Field not set")

        self._definition = FilterDefinition(
            self.entity.hash,
            self.field.filter_key,
            self.field_type,
            self.comparator,
            self.value,
            self.field.is_entity_valued,
        )
