"""Submitter mixin for entities with form submissions."""

from copy import deepcopy
import hashlib
import json

from ..exceptions import ValidationError
from ..entities import Entities
from lagniappe.core.tools.database import get as database_get
from ..tools.auth.references import (
    SubmittedReferenceResolver,
    UNAVAILABLE_REFERENCE_ERROR,
)


# @testable true
# @tests tests_unit/test_003f_submission_normalize_patch.py::test_normalize_skips_keys_not_in_schema
# @tests tests_unit/test_003f_submission_normalize_patch.py::test_normalize_multipart_keys_merge_under_field_id
# @tests tests_unit/test_003f_submission_normalize_patch.py::test_normalize_drops_falsy_entries_in_lists
# @tests tests_unit/test_004d_submitter.py::test_normalize_list_drops_numeric_zero_keeps_string_zero
# @matrix submission : list-filtering multipart normalize unknown-keys zero
def normalize_submission_values(values, fields):
    updated = {}

    for field in values.keys():
        parts = field.split(":", 1)
        schema_id = parts[0]
        part = parts[1] if len(parts) > 1 else None

        if schema_id not in fields:
            continue

        getlist = getattr(values, "getlist", None)
        source_values = getlist(field) if getlist else values.get(field)
        if isinstance(source_values, list):
            update = [v for v in source_values if v]
        else:
            update = [source_values] if source_values else []

        if part:
            updated.setdefault(schema_id, {})[part] = update[0] if update else None
        else:
            updated[schema_id] = update

    return updated


# @testable false
# @covered-by lagniappe/core/mixins/submitter.py::SubmitterMixin.validate_browser_submission_references
# @reason link identifier extraction is exercised through browser submission preflight
def _link_identifier(value):
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        identifier = value.get("id")
        return identifier if isinstance(identifier, str) and identifier else None
    return None


# @testable false
# @covered-by lagniappe/core/mixins/submitter.py::SubmitterMixin.validate_browser_submission_references
# @reason recursive link discovery is exercised through browser submission preflight
def _internal_link_ids(field, value) -> set[str]:
    """Extract internal Link identifiers without resolving or mutating fields."""
    from ..properties.form_links import Link
    from ..properties.form_table import Table

    if isinstance(field, Link):
        if not field.is_entity_valued:
            return set()
        identifier = _link_identifier(value)
        return {identifier} if identifier else set()

    if not isinstance(field, Table):
        return set()

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValidationError(UNAVAILABLE_REFERENCE_ERROR) from error
    if value is None:
        return set()
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("rows", []), list):
        rows = value.get("rows", [])
    else:
        raise ValidationError(UNAVAILABLE_REFERENCE_ERROR)

    internal_columns = {
        field_id
        for field_id, column in field.fields.items()
        if isinstance(column, Link) and column.is_entity_valued
    }
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError(UNAVAILABLE_REFERENCE_ERROR)
        for field_id in internal_columns:
            value = row.get(field_id)
            column = field.fields[field_id]
            if isinstance(value, list) and not column.multiple and value:
                value = value[0]
            identifier = _link_identifier(value)
            if identifier:
                identifiers.add(identifier)
    return identifiers


# @testable infrastructure
# @covered-by lagniappe/core/mixins/submitter.py::SubmitterMixin.form_submission
# @covered-by lagniappe/core/mixins/submitter.py::SubmitterMixin.patch_submission
# @covered-by lagniappe/core/mixins/submitter.py::SubmitterMixin.import_submission
class SubmitterMixin:
    """Adds form submission handling to entities with a Form schema.

    Used by Page and Task entities. Submission data is stored in
    entity.db["submission"] as JSON.

    Provides:
        form_submission(values): Validate and save form data from a web request.
        ai_submission(submission): Validate and save AI-generated field values.
        import_submission(submission): Validate and save CSV-imported field values.
        save_submission(): Persist ``submission.db_value`` and form metadata.
        save_default_field(field_id, submission): Persist one field as a repeating
            default without running the entity's normal save plan.
        fingerprint: MD5 combining the entity fingerprint with the form's cached
            fingerprint (form modification), used when the entity has a form.
    """

    # @testable true
    # @tests tests_unit/test_004e_submission_behavior.py::test_full_form_submit_missing_checkbox_persists_explicit_false
    # @tests tests_unit/test_004e_submission_behavior.py::test_empty_submission_pops_submission_db_key
    # @tests tests_unit/test_004e_submission_behavior.py::test_html_field_is_ignored_by_form_submission
    # @matrix submission : asset-isolation blank-persistence empty-submission explicit-false form-submit submit-boundary
    def form_submission(self, values, *, actor=None):
        submission = self.properties.submission
        form_values = getattr(values, "form", values)
        files = getattr(values, "files", None)
        updated = normalize_submission_values(form_values, submission.fields)
        preserved = (
            self.validate_browser_submission_references(
                updated,
                actor=actor,
                normalized=True,
            )
            if actor is not None
            else set()
        )

        for field_id, field in submission.fields.items():
            if field_id in preserved:
                continue
            value = updated.get(field_id)
            if isinstance(value, list) and not field.multiple and value:
                value = value[0]
            if files and isinstance(value, str):
                uploaded = files.get(value)
                if uploaded:
                    value = uploaded

            field.validate_submission(value)

        self.save_submission()

    # @testable true
    # @tests tests_unit/test_031_submitted_references.py::test_browser_submission_references_require_view_and_preserve_hidden_existing_values
    # @tests tests_unit/test_031_submitted_references.py::test_browser_submission_references_validate_table_links_before_mutation
    # @matrix submitted-references : browser internal-link no-partial-mutation preflight preservation table
    def validate_browser_submission_references(
        self,
        values,
        *,
        actor,
        normalized=False,
    ) -> set[str]:
        """Authorize changed internal Link values before applying a browser form."""
        from ..definitions import Action
        from ..properties.form_links import Link
        from ..properties.form_table import Table

        submission = self.properties.submission
        updated = (
            values
            if normalized
            else normalize_submission_values(values, submission.fields)
        )
        submitted_by_field = {}
        existing_by_field = {}

        for field_id, field in submission.fields.items():
            if not isinstance(field, (Link, Table)):
                continue

            value = updated.get(field_id)
            if isinstance(value, list) and not field.multiple and value:
                value = value[0]
            submitted_by_field[field_id] = _internal_link_ids(field, value)
            existing_by_field[field_id] = _internal_link_ids(field, field.db_value)

        all_ids = {
            identifier
            for identifiers in [*submitted_by_field.values(), *existing_by_field.values()]
            for identifier in identifiers
        }
        if not all_ids:
            return set()

        expected = (
            Entities.CATEGORY,
            Entities.PAGE,
            Entities.USER,
            Entities.GROUP,
            Entities.PROJECT,
            Entities.TASK,
            Entities.MODEL_TASK,
            Entities.FILE,
            Entities.FORM,
        )
        resolver = SubmittedReferenceResolver(actor, *all_ids)
        preserved = set()

        for field_id, submitted_ids in submitted_by_field.items():
            field = submission.fields[field_id]
            existing_ids = existing_by_field[field_id]
            changed_ids = submitted_ids - existing_ids
            resolver.many(changed_ids, expected=expected, action=Action.VIEW)

            if field_id in updated or not existing_ids:
                continue

            for identifier in existing_ids:
                try:
                    resolver.one(
                        identifier,
                        expected=expected,
                        action=Action.VIEW,
                        required=True,
                    )
                except ValidationError:
                    preserved.add(field_id)
                    break

        return preserved

    # @testable true
    # @tests tests_unit/test_003f_submission_normalize_patch.py::test_patch_submission_merges_single_field
    # @tests tests_unit/test_003f_submission_normalize_patch.py::test_patch_submission_accepts_json_string
    # @tests tests_unit/test_004d_submitter.py::test_patch_submission_merges_multiple_fields
    # @matrix submission : json-payload multiple-fields patch single-field
    def patch_submission(self, update, *, actor=None):
        updated = json.loads(update) if isinstance(update, str) else update
        if actor is not None:
            self.validate_browser_submission_references(
                updated,
                actor=actor,
                normalized=True,
            )
        for field_id, field_value in updated.items():
            self.properties.submission.patch(field_id, field_value)

        self.save_submission()

    def ai_submission(self, generated_submission):
        for field_id, field in self.properties.submission.fields.items():
            field.reset()
            field.validate_ai(generated_submission.get(field_id, None))

        self.save_submission()

    # @testable true
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_validation_error_includes_field_and_payload
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_space_joins_input_list_values
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_preserves_table_row_lists_during_input_list_normalization
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_internal_link_fuzzy_match_warning
    # @tests tests_unit/test_004d_submitter.py::test_import_submission_table_internal_link_fuzzy_match_warning
    # @matrix form-table submission text-input : error-message fuzzy-match import list-normalization save validation
    def import_submission(self, imported_submission, import_process):
        for field_id, field in self.properties.submission.fields.items():
            try:
                field.reset()
                if hasattr(field, "fuzzy_match"):
                    field.fuzzy_match = import_process.fuzzy_match(field_id)
                if hasattr(field, "separator"):
                    field.separator = import_process.separator
                if hasattr(field, "set_import_process"):
                    field.set_import_process(import_process)
                value = imported_submission.get(field_id, None)
                if isinstance(value, list) and field.get("type") == "input":
                    value = " ".join(
                        str(v).strip()
                        for v in value
                        if v is not None and str(v).strip()
                    )
                field.validate_import(value)
            except Exception as e:
                raise ValidationError(
                    f"{field_id}:{imported_submission.get(field_id, None)} - {str(e)}"
                )

        self.save_submission()

    @property
    def schema_version(self):
        return self.db.get("schema_version")

    # @testable true
    # @tests tests_unit/test_004d_submitter.py::test_save_default_field_copies_db_value_and_saves_only_submitter
    # @tests tests_unit/test_004d_submitter.py::test_save_submission_removes_changed_repeating_defaults
    # @matrix submission : repeating-default storage
    @property
    def default_submission(self):
        value = self.db.get("default_submission")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return {}
        return value if isinstance(value, dict) else {}

    # @testable false
    # @covered-by lagniappe/core/mixins/submitter.py::SubmitterMixin.save_default_field
    # @covered-by lagniappe/core/mixins/submitter.py::SubmitterMixin.save_submission
    # @reason repeating-default storage normalization is owned by its public mutation methods
    def _set_default_submission(self, submission):
        if submission:
            self.db["default_submission"] = json.dumps(submission)
        else:
            self.db.pop("default_submission", None)

    # @testable true
    # @tests tests_unit/test_004d_submitter.py::test_save_default_field_copies_db_value_and_saves_only_submitter
    # @tests tests_unit/test_003g_todo_lists.py::test_todo_list_cannot_be_saved_as_repeating_default
    # @matrix submission : direct-save field-copy repeating-default
    # @pair form-todo:repeating-default
    def save_default_field(self, field_id, submission=None):
        """Persist one field's DB value as a repeating submission default."""
        submission = submission or self.properties.submission
        field = submission.fields.get(field_id)
        if field is None:
            raise ValidationError(f"Submission field {field_id!r} does not exist.")
        if not getattr(field, "repeating_default", True):
            raise ValidationError(
                f"Submission field {field_id!r} cannot repeat automatically."
            )
        submission_value = submission.db_value
        if field_id not in submission_value:
            raise ValidationError(f"Submission field {field_id!r} has no saved value.")

        defaults = deepcopy(self.default_submission)
        value = deepcopy(submission_value[field_id])
        defaults[field_id] = value
        self._set_default_submission(defaults)
        Entities.save_root(self, property_mask=("default_submission",))
        return value

    # @testable true
    # @tests tests_unit/test_004e_submission_behavior.py::test_stored_explicit_checkbox_false_survives_load_save
    # @tests tests_unit/test_004e_submission_behavior.py::test_stored_null_checkbox_normalizes_away_on_resave
    # @tests tests_unit/test_004e_submission_behavior.py::test_empty_submission_pops_submission_db_key
    # @tests tests_unit/test_004d_submitter.py::test_save_submission_removes_changed_repeating_defaults
    # @matrix submission : blank-persistence empty-submission load-save normalization reconciliation repeating-default stored-false stored-null
    def save_submission(self):
        submission_value = self.properties.submission.db_value
        self.properties.submission.value = submission_value
        defaults = {
            field_id: value
            for field_id, value in self.default_submission.items()
            if field_id in submission_value and submission_value[field_id] == value
        }
        self._set_default_submission(defaults)
        if self.form:
            self.db["schema_version"] = self.form.version
        if "name" in submission_value:
            self.name = submission_value["name"]
        if "description" in submission_value:
            self.description = submission_value["description"]

    # @testable true
    # @tests tests_unit/test_004c_form_submission_integration.py::test_submission_links_internal_top_level_and_table_row
    # @pairs form-table:derived-page-keys submission:derived-page-keys
    @property
    def derived_page_keys(self):
        keys = []
        for link in self.properties.submission.links:
            if not isinstance(link, dict) or link.get("kind") not in ("page", "user"):
                continue

            key = database_get.datastore_key(link.get("id"))
            if key and key not in keys:
                keys.append(key)

        return keys

    @property
    def fingerprint(self):
        fingerprint = super().fingerprint
        if not self.form:
            return fingerprint

        return hashlib.md5(
            f"{fingerprint}:{self.form.version}".encode("utf-8")
        ).hexdigest()

    # @testable true
    # @tests tests_unit/test_023e_deferred_job_adapters_autofill.py::test_autofill_revision_tracks_only_form_apply_state
    # @pairs ai:autofill deferred-jobs:form-revision
    @property
    def autofill_revision(self):
        """Stable revision for state that autofill reads and may overwrite."""
        form = self.form
        schema_ids = {
            field.get("id")
            for field in (getattr(form, "schema", None) or [])
            if isinstance(field, dict) and field.get("id")
        }
        mirrored = {}
        if "name" in schema_ids:
            mirrored["name"] = self.name
        if "description" in schema_ids:
            mirrored["description"] = self.description

        canonical = json.dumps(
            {
                "form": getattr(form, "urlsafe_key", None),
                "form_version": getattr(form, "version", None),
                "schema_version": self.schema_version,
                "submission": self.properties.submission.value or {},
                "default_submission": self.default_submission,
                "mirrored": mirrored,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
