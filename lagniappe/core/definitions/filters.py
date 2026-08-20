"""Filter field types, comparators, options, and serializable definitions."""

from enum import Enum
import json


# @testable infrastructure
# @covered-by lagniappe/core/entities/condition.py::Condition.set_value
# @covered-by lagniappe/core/entities/filter.py::Filter.conditions
class FieldType(Enum):
    """Data types for filter fields. Determines available comparators."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    TIMESTAMP = "timestamp"
    LIST = "list"


# @testable infrastructure
# @covered-by lagniappe/core/entities/condition.py::Condition.set_value
# @covered-by lagniappe/core/entities/filter.py::Filter.conditions
class Comparator(Enum):
    """Comparison operators for filter conditions."""

    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    EQUALS = "eq"
    NOT_EQUALS = "ne"
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    GREATER_EQUAL = "gte"
    LESS_EQUAL = "lte"
    CONTAINS = "contains"
    IN = "in"
    NOT_IN = "not_in"
    SUBSTRING = "substring"
    CONTAINS_ANY = "contains_any"
    BETWEEN = "between"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class DateOptions(Enum):
    """UI display labels for date comparators."""

    LESS_THAN = "is before"
    LESS_EQUAL = "is on or before"
    EQUALS = "is on"
    GREATER_THAN = "is after"
    GREATER_EQUAL = "is on or after"
    BETWEEN = "is between"


class TimeOptions(Enum):
    """UI display labels for time comparators."""

    LESS_THAN = "is before"
    EQUALS = "is at"
    GREATER_THAN = "is after"
    BETWEEN = "is between"


class StringOptions(Enum):
    """UI display labels for string comparators."""

    SUBSTRING = "contains"
    EQUALS = "matches"
    IN = "is in"
    NOT_IN = "is not in"


class FormOptions(Enum):
    """UI display labels for form comparators."""

    IN = "is in"
    EQUALS = "matches"


class ListOptions(Enum):
    """UI display labels for list comparators."""

    CONTAINS = "contains"
    CONTAINS_ANY = "contains any"
    IN = "is in"
    NOT_IN = "is not in"


class NumberOptions(Enum):
    """UI display labels for number comparators."""

    LESS_THAN = "is less than"
    LESS_EQUAL = "is less than or equal to"
    EQUALS = "equals"
    GREATER_THAN = "is greater than"
    GREATER_EQUAL = "is greater than or equal to"
    BETWEEN = "is between"


class CompletedOptions(Enum):
    """UI display labels for task completion status."""

    IS_TRUE = "completed"
    IS_FALSE = "in progress"


class DocumentOptions(Enum):
    """UI display labels for document existence."""

    IS_TRUE = "document"
    IS_FALSE = "no document"


class ImageOptions(Enum):
    """UI display labels for image existence."""

    IS_TRUE = "image"
    IS_FALSE = "no image"


class NotesOptions(Enum):
    """UI display labels for notes existence."""

    IS_TRUE = "notes"
    IS_FALSE = "no notes"


class TasksOptions(Enum):
    """UI display labels for task existence."""

    IS_TRUE = "active tasks"
    IS_FALSE = "no active tasks"


class PublicOptions(Enum):
    """UI display labels for public visibility."""

    IS_TRUE = "public"
    IS_FALSE = "not public"


class SignatureOptions(Enum):
    """UI display labels for signature status."""

    IS_TRUE = "signed"
    IS_FALSE = "not signed"


class StatusOptions(Enum):
    """UI display labels for computed form status."""

    IS_TRUE = "status"
    IS_FALSE = "no status"


class CheckboxOptions(Enum):
    """UI display labels for checkbox status."""

    IS_TRUE = "checked"
    IS_FALSE = "not checked"


# @testable infrastructure
# @covered-by lagniappe/core/entities/condition.py::Condition.set_value
# @covered-by lagniappe/core/properties/form.py::FormFilters.conditions
class FilterOptions(Enum):
    """Maps field types to their available comparator option enums."""

    DATE = DateOptions
    TIME = TimeOptions
    STRING = StringOptions
    FORM = FormOptions
    LIST = ListOptions
    NUMBER = NumberOptions
    COMPLETED = CompletedOptions
    DOCUMENT = DocumentOptions
    IMAGE = ImageOptions
    NOTES = NotesOptions
    TASKS = TasksOptions
    PUBLIC = PublicOptions
    SIGNATURE = SignatureOptions
    STATUS = StatusOptions
    CHECKBOX = CheckboxOptions


# @testable false
# @covered-by lagniappe/core/entities/condition.py::Condition.set_value
# @covered-by lagniappe/core/entities/filter.py::Filter.conditions
# @reason serialized filter definitions are owned by condition creation workflows
class FilterDefinition:
    """Serializable filter condition (entity_hash, field, type, comparator, value).

    Stored as a compact list via ``description`` and restored via ``load()``.
    Boolean fields omit value; entity-valued fields include ``is_entity_valued``.
    """

    def __init__(
        self, entity_hash, field, field_type, comparator, value, is_entity_valued
    ):
        self.entity_hash = entity_hash
        self.field = field
        self.field_type = FieldType(field_type)
        self.comparator = Comparator(comparator)
        self.value = value
        self.is_entity_valued = is_entity_valued

    def __str__(self):
        return f"{self.entity_hash} {self.field} {self.field_type.value} {self.comparator.value} {self.value} {self.is_entity_valued}"

    @property
    def description(self):
        """Serializable list representation for storage."""
        if self.is_entity_valued:
            return [
                self.entity_hash,
                self.field,
                self.field_type.value,
                self.comparator.value,
                self.value,
                self.is_entity_valued,
            ]
        elif self.value:
            return [
                self.entity_hash,
                self.field,
                self.field_type.value,
                self.comparator.value,
                self.value,
            ]
        else:
            return [
                self.entity_hash,
                self.field,
                self.field_type.value,
                self.comparator.value,
            ]

    @classmethod
    def load(cls, definition):
        """Create from a serialized description (JSON string or list)."""
        attrs = json.loads(definition) if isinstance(definition, str) else definition
        return cls(
            *attrs[0:4],
            attrs[4] if len(attrs) > 4 else None,
            attrs[5] if len(attrs) > 5 else False,
        )
