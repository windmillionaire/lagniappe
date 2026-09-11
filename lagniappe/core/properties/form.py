"""Form-related properties for form type filtering and display."""

import hashlib
import json

from ..definitions import Ordering
from ..exceptions import ValidationError
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
# @tests tests_unit/test_004_form_properties.py::test_submission_conversion_requires_changes_to_existing_values
# @tests tests_unit/test_004_form_properties.py::test_submission_conversion_preserves_presentation_and_additions
# @tests tests_unit/test_004_form_properties.py::test_submission_conversion_ignores_fields_without_answers_and_unused_link_setting
# @matrix form : generation value-conversion
def requires_submission_conversion(previous_schema, proposed_schema):
    """Compare normalized definitions for changes that affect existing values.

    Labels, presentation, ordering and additions leave saved values readable.
    Removed identities and changed field representations need migration first.
    """
    proposed_fields = {field["id"]: field for field in proposed_schema or []}
    for previous in previous_schema or []:
        if previous.get("type") in {"html", "status"}:
            continue
        proposed = proposed_fields.get(previous["id"])
        if proposed is None or previous.get("type") != proposed.get("type"):
            return True
        kind = previous.get("type")
        if kind == "input" and (
            previous.get("input", "text") != proposed.get("input", "text")
        ):
            return True
        if kind == "select" and (
            bool(previous.get("multiple")) != bool(proposed.get("multiple"))
        ):
            return True
        if kind == "link" and (
            previous.get("location", "out") != proposed.get("location", "out")
        ):
            return True
        if kind in {"select", "radio"}:
            option_values = {option["value"] for option in proposed.get("options", [])}
            if any(
                option["value"] not in option_values
                for option in previous.get("options", [])
            ):
                return True
        if kind == "table" and requires_submission_conversion(
            previous.get("columns", []), proposed.get("columns", []),
        ):
            return True
    return False


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_form_generation_defaults_to_zero_without_reinterpreting_legacy_versions
# @tests tests_unit/test_004_form_properties.py::test_form_generation_stores_nonnegative_integers
# @matrix form : generation defaults validation
class FormGeneration(DBProperty):
    """Submission representation generation, advanced explicitly at publication.

    Missing generations start at zero, independently of older version fields.
    """

    _id = "generation"

    @property
    def value(self):
        value = super().value
        return 0 if value is None else value

    @value.setter
    def value(self, value):
        if type(value) is not int or value < 0:
            raise ValidationError("Form generation must be a nonnegative integer.")
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_schema_version_update_changes_when_schema_changes
# @tests tests_unit/test_004_form_properties.py::test_schema_version_tracks_metadata_and_static_content
# @tests tests_unit/test_004_form_properties.py::test_schema_version_ignores_name_storage_paths_and_unrelated_assets
# @tests tests_unit/test_004_form_properties.py::test_schema_version_requires_static_content_fingerprints
# @matrix form : schema-version update content-fingerprint
class SchemaVersion(DBProperty):
    """Content fingerprint used to invalidate cached Form presentations."""

    _id = "version"

    def update(self):
        """Refresh the schema and published HTML/image fingerprint."""
        previous_version = super().value
        html_ids = {
            field["id"] for field in self.entity.schema if field.get("type") == "html"
        }
        assets = {
            name: {key: asset.get(key) for key in ("type", "fingerprint")}
            for name, asset in self.entity.assets.items()
            if name in html_ids or any(
                name.startswith(f"image_{field_id}_") for field_id in html_ids
            )
        }
        if any(
            not isinstance(asset["fingerprint"], str) or not asset["fingerprint"]
            for asset in assets.values()
        ):
            raise ValidationError("Form content requires a fingerprint before publication.")
        next_version = hashlib.md5(
            json.dumps({
                "schema": self.entity.schema,
                "form_type": self.entity.form_type,
                "assets": assets,
            }, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if previous_version == next_version:
            return False
        self.value = next_version
        return previous_version
