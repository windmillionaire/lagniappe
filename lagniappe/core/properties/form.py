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
# @matrix form-type : cache column details property
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


# @testable true
# @tests tests_unit/test_012b_form_conditions.py::test_form_status_filters
# @matrix filters status : form-filters status-excluded
class FormFilters(Filters):
    _filter_fields = []

    # @testable true
    # @tests tests_unit/test_004_form_properties.py::test_form_filters
    # @matrix filters form : schema-fields
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
    # @matrix filters form : conditions exclude-table-fields schema-fields
    @property
    def conditions(self):
        if getattr(self, "_conditions", None):
            return self._conditions

        self._conditions = [self._condition(field) for field in self.fields.values()]
        return self._conditions


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_schema_version_update_changes_when_schema_changes
# @matrix form : schema-version update
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
