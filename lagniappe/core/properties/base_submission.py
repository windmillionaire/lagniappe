import json
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from ..mixins import AIMixin, FilterMixin, SearchMixin
from .form_special import HTML

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..mixins.field_host import FieldUser
    from .schema import SchemaField


# @testable false
# @covered-by lagniappe/core/properties/base_submission.py::SubmissionProperty.search_value
# @reason private normalization helper for the submission search-value collector
def _search_items(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Iterable):
        return [value] if value != "" else []
    return [item for item in value if item is not None and item != ""]


# @testable false
# @covered-by lagniappe/core/properties/base_submission.py::SubmissionProperty.db_value
# @covered-by lagniappe/core/properties/form_table.py::Table.db_value
# @reason private blank-value helper used by submission projection collectors
def _is_blank_value(value: object) -> bool:
    return value is None or value == [] or value == {}


# @testable infrastructure
class SubmissionProperty:
    """Base mixin for form submission data.

    Stores the raw submission dict and provides computed views
    for AI, filtering, and search. Concrete subclasses (FormSubmission,
    RowSubmission) define how ``fields`` are constructed from a schema.

    Set:
        value (dict | str | None): Raw submission data. Accepts a dict
            or JSON string; None clears the submission.

    Get:
        value (dict): {field_id: db_value}, excluding None values.
        ai_value (dict): {ai_key: ai_value} for AIMixin fields.
        filter_value (dict): {filter_key: filter_value} for FilterMixin fields.
        search_value (dict): {"keys": [...], "values": [...]} for SearchMixin fields,
            or empty dict if none.
        form_value (dict): {field_id: form_value}, excluding HTML and None values.
    """

    _submission: dict[str, object] | None = None
    if TYPE_CHECKING:
        @property
        def fields(self) -> Mapping[str, SchemaField]: ...
        @property
        def user(self) -> FieldUser: ...
        @user.setter
        def user(self, value: FieldUser) -> None: ...

    @property
    def value(self) -> dict[str, object]:
        return self._submission or {}

    @value.setter
    def value(self, value: object) -> None:
        self._set_submission(value)

    def _set_submission(self, value: object) -> None:
        if not value:
            self._submission = None
        elif isinstance(value, dict):
            self._submission = value
        elif isinstance(value, str):
            self._submission = json.loads(value)

    # @testable true
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_db_value_omits_unset_number_field
    # @matrix submission : db-value empty-field
    @property
    def db_value(self) -> dict[str, object]:
        submission = {
            field_id: field.db_value
            for field_id, field in self.fields.items()
            if getattr(field, "is_set", True)
        }
        return {k: v for k, v in submission.items() if not _is_blank_value(v)}

    @property
    def ai_value(self) -> dict[str, object] | None:
        values = {}
        for field in [f for f in self.fields.values() if isinstance(f, AIMixin)]:
            field.user = self.user
            values[field.ai_key] = field.ai_value
        return {k: v for k, v in values.items() if v is not None}

    @property
    def filter_value(self) -> dict[str, object]:
        values = {}
        for field in [f for f in self.fields.values() if isinstance(f, FilterMixin)]:
            field.user = self.user
            value = field.filter_value
            if isinstance(value, dict):
                values.update(value)
            else:
                values[field.filter_key] = value
        return values

    # @testable true
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_search_value_merges_table_column_labels
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_search_value_accepts_scalar_boolean_values
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_search_value_omits_blank_search_fields
    # @matrix form-table submission : search-value
    @property
    def search_value(self) -> dict[str, list[object]]:
        keys, values = [], []
        for field in [f for f in self.fields.values() if isinstance(f, SearchMixin)]:
            key, value = field.search_key, field.search_value
            key_items = _search_items(key)
            value_items = _search_items(value)
            if key_items and value_items:
                keys.extend(key_items)
                values.extend(value_items)
        if keys and values:
            return {"keys": keys, "values": values}
        return {}

    @property
    def form_value(self) -> dict[str, object]:
        submission = {
            field_id: field.form_value
            for field_id, field in self.fields.items()
            if not isinstance(field, HTML)
        }
        # Only a top-level submission has an entity name and description to inherit.
        owner: Entity | None = getattr(self, "entity", None)
        if owner is not None and "name" in self.fields and not submission.get("name"):
            submission["name"] = owner.name
        if owner is not None and "description" in self.fields and not submission.get("description"):
            submission["description"] = owner.description
        return {k: v for k, v in submission.items() if v is not None}
