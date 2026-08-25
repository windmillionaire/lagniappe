from ..definitions import FieldType, FilterOptions, Ordering
from ..definitions.identifiers import short_uuid
from ..mixins import AIMixin, ColumnMixin, FilterMixin
from .base_asset import AssetProperty
from .base_schema import SchemaProperty
from .base_property import UNSET


# @testable true
# @tests tests_unit/test_003c_submission_complex.py::test_signature_field_asset_lifecycle_saves_and_clears_image
# @tests tests_unit/test_003c_submission_complex.py::test_signature_field_projections_reflect_asset_presence
# @tests tests_unit/test_013_task_properties.py::test_task_signature_form_submission_saves_asset_id
# @tests tests_unit/test_013_task_properties.py::test_task_signature_form_submission_saves_multiple_assets_by_field_id
# @matrix signature submission task : asset-lifecycle db-value multiple-fields schema-id
# @pair signature:form-value
class Signature(AssetProperty, FilterMixin, AIMixin, ColumnMixin, SchemaProperty):
    """Signature image field. Stored as an image asset.

    Set:
        value (file): Signature image from form upload.

    Get:
        value (str): Asset path.
        asset: Signature image URL.
        filter_value (bool): Whether a signature exists.
        ai_value (bool): Same as filter_value.
    """

    _icon = "signature"

    # Property Attributes
    _asset_type = "image"

    def validate_submission(self, value):
        if not value:
            self.value = None
        elif isinstance(value, str):
            if value in (self.id, self.form_value):
                return
        else:
            self.value = value

    @property
    def db_value(self):
        return self.id if self.value else None

    @db_value.setter
    def db_value(self, value):
        self._asset = UNSET
        self.unset()

    @property
    def form_value(self):
        asset = self.value
        if not asset:
            return None

        return getattr(asset, "url", None) or self.asset

    # Column Attributes
    _ordering = Ordering.EXISTS

    @property
    def column_value(self):
        return self.form_value

    @property
    def sort_value(self):
        return True if self.value else False

    # AI Attributes
    @property
    def ai_value(self):
        return self.filter_value

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.SIGNATURE.value

    @property
    def filter_value(self):
        return True if self.value else False


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_form_html_fields
# @tests tests_unit/test_004e_submission_behavior.py::test_html_field_is_ignored_by_form_submission
# @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
# @matrix html-field : asset-isolation asset-lifecycle html-fields render-fetch submit-boundary
class HTML(AssetProperty, SchemaProperty):
    """Rich HTML content field. Stored as an HTML text asset.

    The setter returns whether the content actually changed (by
    comparing asset fingerprints).

    Set:
        value (str): HTML string content.

    Get:
        value (str): Asset path.
        asset: HTML content string.
    """

    # Property Attributes
    _asset_type = "html"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if not value:
            return None

        AssetProperty.value.fset(self, value)
        return super().value.updated

    def validate_submission(self, value):
        self.unset()

    def validate_import(self, value):
        self.unset()

    def validate_ai(self, value):
        self.unset()

    @property
    def db_value(self):
        return None

    @db_value.setter
    def db_value(self, value):
        self.unset()

    @property
    def form_value(self):
        return None

    # Column Attributes
    _ordering = None

    @property
    def sort_value(self):
        return True if self.entity.assets.get(self.id) else False

    # Asset Attributes
    def add_image(self, image, visibility="private"):
        name = f"image_{self.id}_{short_uuid()}"
        asset = self.entity.save_asset(image, name, "image", visibility=visibility)
        return asset.url if asset else None


# @testable false
# @covered-by lagniappe/core/properties/form_special.py::Status.status_conditions
# @covered-by lagniappe/core/properties/form_special.py::Status.ai_value
# @covered-by lagniappe/core/properties/form_special.py::Status.column_value
class Status(AIMixin, ColumnMixin, SchemaProperty):
    """Computed status field derived from other form field values.

    Evaluates status_conditions against the entity's submission to
    determine which statuses are active. Not directly persisted --
    value is computed from the submission's current field state.

    Get:
        value (list[str]): Active status display labels.
        column_value (list[str]): Active status display labels.
        ai_value (list[str]): Active status display labels.
    """

    _icon = "status"

    # Property Attributes
    # @testable true
    # @tests tests_unit/test_003c_submission_complex.py::test_submission_status
    # @pair status:computed
    @property
    def status_conditions(self):
        """Return the status conditions from the schema."""
        return self.get("status", [])

    @property
    def active_statuses(self):
        submission = self.entity.properties.get("submission")
        if not submission:
            return []

        return [
            status_element
            for status_element in self.status_conditions
            if submission.condition_matches(status_element)
        ]

    @property
    def value(self):
        return self.ai_value

    @value.setter
    def value(self, value):
        self._value = None

    def validate_submission(self, value):
        self.value = None

    @property
    def db_value(self):
        return None

    @db_value.setter
    def db_value(self, value):
        self.value = None

    @property
    def form_value(self):
        return None

    # Column Attributes
    _ordering = Ordering.EXISTS

    # @testable true
    # @tests tests_unit/test_003c_submission_complex.py::test_submission_status
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_has_status_renders_status_column
    # @matrix status : column computed-column
    @property
    def column_value(self):
        return self.value

    @property
    def sort_value(self):
        return bool(self.value)

    # AI Attributes
    # @testable true
    # @tests tests_unit/test_003c_submission_complex.py::test_submission_status
    # @matrix status : ai-value computed
    @property
    def ai_value(self):
        return [status_element["text"] for status_element in self.active_statuses]
