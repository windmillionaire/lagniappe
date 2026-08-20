from .form_special import HTML
from .form_table import Table
from .form_links import Link
from .base_submission import SubmissionProperty
from .base_db import DBProperty
from .schema import SchemaFields


# @testable false
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.value
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.fields
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.tables
# @covered-by lagniappe/core/properties/form_submission.py::FormSubmission.links
# @reason behavior is owned by focused submission projection properties and methods
class FormSubmission(SubmissionProperty, DBProperty):
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

    @property
    def ai_value(self):
        value = super().ai_value
        return value or None

    def __init__(self, *args, entity=None, **kwargs):
        super().__init__(*args, entity=entity, **kwargs)
        self.value = self.entity.db.get("submission")

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_value
    # @tests tests_unit/test_003_submission.py::test_submission_save
    # @features submission
    # @dimensions db-value, save
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        SubmissionProperty.value.fset(self, value)
        DBProperty.value.fset(self, self._submission)

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_fields
    # @tests tests_unit/test_004c_form_submission_integration.py::test_submission_fields_stale_when_db_submission_changes
    # @tests tests_unit/test_003a_submission_basic.py::test_submission_text_input_empty_column_value_is_blank
    # @tests tests_unit/test_004e_submission_behavior.py::test_missing_stored_checkbox_is_unset_and_omitted
    # @tests tests_unit/test_004e_submission_behavior.py::test_stored_explicit_checkbox_false_survives_load_save
    # @tests tests_unit/test_004e_submission_behavior.py::test_stored_null_checkbox_normalizes_away_on_resave
    # @features submission
    # @dimensions fields, cache, stale-db, empty-field, missing-field, unset, projection, stored-false, load-save, stored-null, normalization
    @property
    def fields(self):
        if getattr(self, "_fields", None):
            return self._fields
        elif not getattr(self.entity, "form", None):
            return {}

        schema = self.entity.form.schema
        fields = [SchemaFields.create_field(f, self.entity) for f in schema]
        self._fields = {f.id: f for f in fields if f is not None}

        for field_id, field in self._fields.items():
            if not isinstance(field, HTML):
                if field_id in self.value:
                    field.db_value = self.value[field_id]
                else:
                    field.unset()

        return self._fields

    def column(self, column_id):
        if column_id in self.fields:
            return self.fields[column_id]

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_patch
    # @features submission
    # @dimensions patch
    def patch(self, field_id, value):
        field = self.fields[field_id]
        field.validate_submission(value)
        return field

    # @testable true
    # @tests tests_unit/test_003_submission.py::test_submission_is_visible
    # @features submission
    # @dimensions visibility
    def is_visible(self, field_id):
        visibility = self.fields[field_id].visibility

        if not visibility:
            return True

        condition_groups = {}

        for condition in visibility:
            ref_id = condition.get("id")
            if not ref_id:
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
    # @features submission, status
    # @dimensions condition-matching
    def condition_matches(self, condition, require_visible=True):
        """Return whether a schema condition matches the referenced field."""
        ref_id = condition.get("id")
        if not ref_id:
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
    # @features submission
    # @dimensions tables
    @property
    def tables(self):
        return [t for t in self.fields.values() if isinstance(t, Table)]

    # @testable true
    # @tests tests_unit/test_004c_form_submission_integration.py::test_submission_links_internal_top_level_and_table_row
    # @features submission
    # @dimensions links, internal, row-submission
    @property
    def links(self):
        links = [
            f.value
            for f in self.fields.values()
            if isinstance(f, Link) and f.is_entity_valued
        ]
        for t in self.tables:
            links.extend([link.value for link in t.links])
        return links
