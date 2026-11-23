"""Filter condition representation.

filter_key must be consistent across: entity.to_filter_index() (cache write),
FilterDefinition.field (stored query), and frontend form input names.
For most fields id == filter_key; EntityForm is the exception (id="form-{hash}"
but filter_key="form").
"""

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import TYPE_CHECKING, Never, Self, cast

from flask_login import current_user
from ..definitions import Comparator, Fetch, FieldType, FilterDefinition
from ..entities import Entities
from ..properties.form_select import CategoricalElement
from ..tools import cache


if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison
    from ..mixins import FilterMixin
    from ..tools.filters.contract import FilterCondition
    from .category import Category
    from .entity import Entity
    from .form import Form
    from .project import Project

    type FilterSource = Category | Form | Project


# @testable true
# @tests tests_unit/test_011_filters.py::test_filter_conditions_multiple_types
# @tests tests_unit/test_011_filters.py::test_condition_create_skips_missing_entity_reference
# @matrix filter : conditions missing-entity mixed-types
class Condition:
    """A single filter condition: entity + field + comparator + value.

    Created from a FilterDefinition. The field (a FilterMixin property)
    determines the available comparators, value transformation, and
    whether values are entity hashes requiring lookup.
    """

    _contract_parent: Entity | None

    def __init__(self, definition: FilterDefinition | None = None) -> None:
        self._entity: FilterSource | None = None
        self._definition = definition
        self._field: FilterMixin | None = None
        self._entity_map: dict[str, Entity] = {}
        self._condition_value: object = None

    @property
    def hashes(self) -> set[str]:
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
    def create(cls, definition: FilterDefinition, entity_map: dict[str, Entity]) -> Self | None:
        """Populate entity, field, comparator, and value from a loaded entity hash map."""
        condition = cls(definition)

        source = condition.entity
        if not source:
            entity = entity_map.get(definition.entity_hash)
            if not entity:
                return None
            # Filter definitions address the Category, Project or Form that supplies the field.
            source = cast("FilterSource", entity)
            condition.entity = source

        if definition.field in source.filters.fields:
            condition.field = definition.field
        elif definition.value in source.filters.entity_fields:
            condition.field = cast(str, definition.value)

        if not condition.entity or not condition.field:
            return None

        condition.comparator = definition.comparator.name
        condition.entity_map = entity_map
        condition._condition_value = definition.value
        return condition

    @property
    def description(self) -> list[object] | dict[str, Never]:
        return self._definition.description if self._definition else {}

    @property
    def contract_condition(self) -> FilterCondition | dict[str, Never]:
        """Return the explicit v1 DTO without client-controlled type metadata."""
        if not self._definition:
            return {}
        from ..tools.filters.contract import condition_contract

        return condition_contract(self._definition)

    @property
    def definition(self) -> FilterDefinition | None:
        return self._definition

    @property
    def _selected_field(self) -> FilterMixin:
        if self.field is None:
            raise AttributeError("No field selected for this condition")
        return self.field

    @property
    def options(self) -> type[Enum] | None:
        return self._selected_field.field_options

    @property
    def entity(self) -> FilterSource | None:
        return self._entity

    @entity.setter
    def entity(self, entity: Entity) -> None:
        self._entity = cast("FilterSource", entity)
        self.entity_map[entity.hash] = entity

    @property
    def entity_map(self) -> dict[str, Entity]:
        return self._entity_map

    @entity_map.setter
    def entity_map(self, entity_map: dict[str, Entity]) -> None:
        self._entity_map = entity_map

    @property
    def value(self) -> object:
        return self._condition_value

    @property
    def value_list(self) -> list[object]:
        return self.value if isinstance(self.value, list) else [self.value]

    @value.setter
    def value(self, value_list: Iterable[object]) -> None:
        normalized: list[object] = []
        for v in [v for v in value_list if v]:
            field = self._selected_field
            if field.is_entity_valued or getattr(
                field, "_is_categorical", False
            ):
                normalized.append(v)
            else:
                # Non-categorical filter inputs normalize values through their concrete setter.
                setattr(field, "value", v)  # noqa: B010 -- filter fields have heterogeneous value setters.
                normalized.append(field.filter_value)

        # One field normalizes its inputs to the same sortable scalar type.
        normalized = list(sorted(cast("Iterable[SupportsRichComparison]", normalized)))

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
    def details(self) -> dict[str, object]:
        if getattr(self, "_details", None):
            return self._details

        load_entities = set(self.value_list) - set(self.entity_map.keys())
        if self._selected_field.is_entity_valued and load_entities:
            details = cache.get_details_by_hash(cast("set[str]", load_entities))
            entities = [
                Entities.fetch_one(cast("Mapping[str, str]", d)["id"], request=Fetch.direct())
                for d in details.values()
            ]
            loaded: dict[str, Entity] = {}
            for entity in entities:
                if entity is None:
                    raise AttributeError("Missing referenced filter entity")
                loaded[entity.hash] = entity
            self.entity_map.update(loaded)

        self._details = self._selected_field.filter_details(self)

        return self._details

    # @testable true
    # @tests tests_unit/test_012_category_conditions.py::*
    # @tests tests_unit/test_012a_project_conditions.py::*
    # @tests tests_unit/test_012b_form_conditions.py::*
    # @matrix filters : boolean categorical condition-definition entity-valued model-task multiple number select string timestamp
    def set_value(self, form_values: object, default_comparator: str | None = None) -> None:
        """Set condition value from form input and create the FilterDefinition."""
        form_values = form_values if isinstance(form_values, list) else [form_values]

        if not self.field:
            raise ValueError("Field not set")

        if self.field_type == FieldType.BOOLEAN:
            self._comparator = Comparator[cast(str, form_values[0])]
        else:
            self.value = form_values

        if not getattr(self, "_comparator", None) and default_comparator:
            self._comparator = Comparator[default_comparator]

        self._create_definition()

    @property
    def choices(self) -> dict[str, str] | None:
        return self._selected_field.choices

    @property
    def field(self) -> FilterMixin | None:
        return self._field

    @field.setter
    def field(self, name: str) -> None:
        source = self.entity
        if source is None:
            raise AttributeError("No source selected for this condition")
        if source.filters.fields.get(name):
            field = source.filters.fields[name]
        elif hasattr(source, "table_fields") and name in (table_fields := cast("Mapping[str, FilterMixin]", source.table_fields)):
            field = table_fields[name]
        elif source.filters.visible_entity_fields.get(name):
            field = source.filters.visible_entity_fields[name]
            field.user = current_user
        else:
            raise ValueError("Field not found: " + name)

        self._field = field
        if isinstance(field, CategoricalElement):
            field.multiple = True

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_condition_requires_field_for_type_and_definition
    # @matrix filters : condition-definition validation
    @property
    def field_type(self) -> FieldType:
        if not self.field:
            raise ValueError("Field not set")
        return self.field.field_type

    @property
    def comparator(self) -> Comparator:
        return getattr(self, "_comparator", Comparator.EQUALS)

    @comparator.setter
    def comparator(self, name: str) -> None:
        self._comparator = Comparator[name]

    # @testable true
    # @tests tests_unit/test_011_filters.py::test_condition_requires_field_for_type_and_definition
    # @matrix filters : condition-definition validation
    def _create_definition(self) -> None:
        if not self.field:
            raise ValueError("Field not set")

        if self.entity is None:
            raise AttributeError("No source selected for this condition")
        self._definition = FilterDefinition(
            self.entity.hash,
            self.field.filter_key,
            self.field_type,
            self.comparator,
            self.value,
            self.field.is_entity_valued,
        )
