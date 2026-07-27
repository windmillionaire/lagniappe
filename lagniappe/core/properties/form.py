"""Form-related properties for form type filtering and display."""

import hashlib
import json

from ..definitions import Ordering
from ..mixins import (
    AIMixin,
    CacheMixin,
    ColumnMixin,
    DetailsMixin,
    FilterMixin,
)

# from ..tools import cache
from .base_db import DBProperty
from .base_filters import Filters
from .form_table import Table


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_form_type
# @features form-type
# @dimensions property, column, details, cache
class FormType(AIMixin, ColumnMixin, DetailsMixin, CacheMixin, DBProperty):
    """Form type classification (e.g. "page", "task").

    Set:
        value (str): Form type identifier.

    Get:
        value (str): Form type identifier.
        sort_value (dict): {Capitalized: value} for categorical ordering.
    """

    # Property Attributes
    _id = "form_type"
    _label = "Form Type"
    _icon = "form"

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    @property
    def sort_value(self):
        return {self.value.capitalize(): self.value} if self.value else None

    @property
    def ai_key(self):
        return self.id

    # Cache Attributes
    @property
    def cache_value(self):
        return self.value

    @property
    def cache_key(self):
        return "type"


# @testable false
# @covered-by lagniappe/core/properties/form.py::FormFilters.fields
# @covered-by lagniappe/core/properties/form.py::FormFilters.conditions
class FormFilters(Filters):
    _filter_fields = []

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_filters
    # @features form, filters
    # @dimensions schema-fields
    @property
    def fields(self):
        return {
            k: v
            for k, v in self.entity.fields.items()
            if isinstance(v, FilterMixin) and not isinstance(v, Table)
        }

    def _condition(self, field):
        return {
            "field": field.filter_key,
            "label": field.label,
            "kind": field.kind,
            "icon": field.icon,
        }

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_filters
    # @features form, filters
    # @dimensions conditions, schema-fields, exclude-table-fields
    @property
    def conditions(self):
        if getattr(self, "_conditions", None):
            return self._conditions

        self._conditions = [self._condition(field) for field in self.fields.values()]
        return self._conditions


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_schema_version_update_changes_when_schema_changes
# @features form
# @dimensions schema-version, update
class SchemaVersion(DBProperty):
    _id = "version"

    def update(self):
        schema_hash = super().value

        new_schema_hash = hashlib.md5(
            json.dumps(self.entity.schema, sort_keys=True).encode()
        ).hexdigest()

        if schema_hash != new_schema_hash:
            self.value = new_schema_hash
            return schema_hash

        return False
