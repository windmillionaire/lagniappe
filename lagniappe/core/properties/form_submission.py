from typing import TYPE_CHECKING

from lagniappe.core.tools.forms.definitions import require_mutable_submission

from .base_db import DBProperty
from .base_submission import SubmissionProperty
from .form_links import Link, LinkValue
from .form_special import HTML
from .form_table import Table
from .schema import SchemaField, SchemaFields

if TYPE_CHECKING:
    from ..entities.history import TaskHistory
    from ..entities.page import Page
    from ..entities.task import Task


# @testable false
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.value
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.fields
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.tables
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.links
# @reason behavior is owned by focused submission projection properties and methods
class FormSubmission(SubmissionProperty, DBProperty[dict[str, object], "Page | Task | TaskHistory"]):  # pyright: ignore[reportIncompatibleMethodOverride] -- db_value is a read-only projection over submission fields.
    """Full form submission for an entity with a user-created form.

    Persists the submission dict in entity.db["submission"] as JSON.
    Fields are constructed from the entity's form schema on first access
    and populated with stored values.

    Get:
        fields (dict): {field_id: SchemaProperty field} from the form schema.
        tables (list): Table field instances from the submission.

    ``ai_value``, ``filter_value``, and ``form_value`` inherit
    ``SubmissionProperty`` behavior: per-field aggregation, with table fields
    merging column-level filter dicts into the submission-level index.
    ``entity.to_ai`` explicitly merges ``submission.ai_value`` after collecting
    other AI-backed properties on the entity.
    """

    json = True
    _id = "submission"
    _fields: dict[str, SchemaField] | None

    # @testable true
    # @tests tests_unit/test_015_ai_tools.py::test_get_task_history_returns_dates_submissions_and_files
    # @matrix submission task-completion : ai missing-schema raw-values
    @property
    def ai_value(self) -> dict[str, object] | None:
        if self.entity.submission_schema_error:
            return {"Saved answers (original labels unavailable)": self.value}
        value = super().ai_value
        return value or None

    def __init__(
        self,
        *args: object,
        entity: Page | Task | TaskHistory | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self._set_submission(self.entity.db.get("submission"))

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_value
    # @tests tests_unit/test_003_submission.py::test_submission_save
    # @matrix submission : db-value save
    # @pair submission:schema-version
    @property
    def value(self) -> dict[str, object]:
        return super().value

    @value.setter
    def value(self, value: object) -> None:
        require_mutable_submission(self.entity)
        self._set_submission(value)
        self._write_db_value(self._submission)

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_fields
    # @tests tests_unit/test_004c_form_submission_integration.py::test_submission_fields_stale_when_db_submission_changes
    # @tests tests_unit/test_003a_submission_basic.py::test_submission_text_input_empty_column_value_is_blank
    # @tests tests_unit/test_004e_submission_behavior.py::test_missing_stored_checkbox_is_unset_and_omitted
    # @tests tests_unit/test_004e_submission_behavior.py::test_stored_explicit_checkbox_false_survives_load_save
    # @tests tests_unit/test_004e_submission_behavior.py::test_stored_null_checkbox_normalizes_away_on_resave
    # @matrix submission : cache column empty-field empty-value fields load-save missing-field normalization projection stale-db stored-false stored-null unset
    @property
    def fields(self) -> dict[str, SchemaField]:
        if cached := getattr(self, "_fields", None):
            return cached
        schema = self.entity.submission_schema
        fields = [SchemaFields.create_field(f, self.entity) for f in schema]
        self._fields = {f.id: f for f in fields if f is not None}

        for field_id, field in self._fields.items():
            if not isinstance(field, HTML):
                if field_id in self.value:
                    field.db_value = self.value[field_id]
                else:
                    field.unset()

        return self._fields

    def column(self, column_id: str) -> SchemaField | None:
        if column_id in self.fields:
            return self.fields[column_id]

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_patch
    # @pair submission:patch
    def patch(self, field_id: str, value: object) -> SchemaField:
        require_mutable_submission(self.entity)
        field = self.fields[field_id]
        field.validate_submission(value)
        return field

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_is_visible
    # @pair submission:visibility
    def is_visible(self, field_id: str) -> bool:
        visibility = self.fields[field_id].visibility

        if not visibility:
            return True

        condition_groups = {}

        for condition in [visibility] if isinstance(visibility, dict) else visibility:
            ref_id = condition.get("id")
            if not isinstance(ref_id, str) or not ref_id:
                return False
            condition_groups.setdefault(ref_id, []).append(condition)

        for ref_id, condition_group in condition_groups.items():
            field = self.fields.get(ref_id)
            if not field:
                return False

            if not any(
                self.condition_matches(condition, require_visible=False)
                for condition in condition_group
            ):
                return False

        return True

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_is_visible
    # @tests tests_unit/test_003c_submission_complex.py::test_submission_status
    # @matrix status submission : condition-matching
    def condition_matches(
        self, condition: dict[str, object], require_visible: bool = True
    ) -> bool:
        """Return whether a schema condition matches the referenced field."""
        ref_id = condition.get("id")
        if not isinstance(ref_id, str) or not ref_id:
            return False

        field = self.fields.get(ref_id)
        if not field:
            return False

        if require_visible and not self.is_visible(ref_id):
            return False

        if condition.get("type") == "checkbox":
            expected = condition.get("value", condition.get("checked", True))
            return bool(field.db_value) is bool(expected)

        field_value = field.db_value
        condition_value = condition.get("value", condition.get("checked"))

        if isinstance(field_value, list):
            if isinstance(condition_value, list):
                return any(value in field_value for value in condition_value)
            return condition_value in field_value

        return field_value == condition_value

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_tables
    # @pair submission:tables
    @property
    def tables(self) -> list[Table]:
        return [t for t in self.fields.values() if isinstance(t, Table)]

    # @testable true
    # @tests tests_unit/test_004c_form_submission_integration.py::test_submission_links_internal_top_level_and_table_row
    # @matrix submission : internal links row-submission
    @property
    def links(self) -> list[LinkValue | None]:
        links = [
            f.value
            for f in self.fields.values()
            if isinstance(f, Link) and f.is_entity_valued
        ]
        for t in self.tables:
            links.extend([link.value for link in t.links])
        return links
