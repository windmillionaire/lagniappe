from ..mixins import CacheMixin
from ..definitions import (
    FileConsumer,
    FileConsumerLimitError,
    enforce_file_consumer,
)
from ..tools import files
from .base_asset import AssetProperty
from .base_property import UNSET


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_records_metadata_before_asset_save
# @tests tests_unit/test_006_file_properties.py::test_file_asset_detects_mislabeled_png_upload
# @features file
# @dimensions upload metadata encoding asset-lifecycle mimetype asset-extension
class FileAsset(AssetProperty):
    """The uploaded file for a File entity.

    The setter determines the mimetype and encoding from the upload.

    Set:
        value (file): File upload object.

    Get:
        value (str): Asset path.
        url (str | None): Signed URL for the file.
        preview (str | None): URL if the mimetype supports preview.
        image (str | None): URL if the mimetype is an image type.
        uri (str): Cloud storage URI (gs://...).
    """

    _id = "file"
    _asset_type = "file"
    _label = "File"
    _icon = "file"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, upload):
        mimetype = upload.content_type or self.entity.mimetype
        self.entity.mimetype = files.determine_mimetype(
            upload, self.entity.filename, mimetype, self.entity.encoding
        )

        if self.entity.mimetype in files.TEXT_MIMETYPES.values():
            self.entity.encoding = files.determine_encoding(upload)

        upload.lagniappe_content_type = self.entity.mimetype
        AssetProperty.value.fset(self, upload)

    @property
    def url(self):
        return self.value.url if self.value else None

    # @testable true
    # @tests tests_unit/test_014_security.py::test_svg_removed_from_preview_mimetypes
    # @features files, security
    # @dimensions preview, mimetype, svg
    @property
    def preview(self):
        mimetype = self.entity.mimetype
        if mimetype and mimetype in files.PREVIEW_MIMETYPES:
            return self.url
        return None

    @property
    def image(self):
        mimetype = self.entity.mimetype
        if mimetype and mimetype in files.IMAGE_MIMETYPES:
            return self.url
        return None

    @property
    def uri(self):
        return self.value.uri if self.value else None

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_file_to_ai_exports_metadata_and_uri_to_ai
    # @features file ai
    # @dimensions uri mimetype
    @property
    def uri_to_ai(self):
        from ..tools.ai.constants import GEMINI_MIMETYPES

        if self.entity.mimetype not in GEMINI_MIMETYPES:
            return None

        uri = self.uri
        if not uri:
            return None
        return {"uri": uri, "mime_type": self.entity.mimetype}


# @testable false
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.is_text_file
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.extractable
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.value
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.asset
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.markup
# @reason text asset behavior is owned by availability, fallback, and markup accessors
class TextAsset(CacheMixin, AssetProperty):
    """Extracted text content for a File entity.

    If no text asset is stored, falls back to reading the file directly
    when it has a text mimetype and known encoding.

    Set:
        value (str): Text content to store.

    Get:
        value (bool | None): True if text exists, None otherwise.
        asset (str | None): The text content.

    Overrides:
        cache_value: Returns text only if extract.search is enabled.
        cache_key: Returns "doc".
    """

    _id = "text"
    _asset_type = "text"
    _label = "Text"
    _icon = "text"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_text_asset_extractable_only_for_non_text_document_ai_mimetypes
    # @features file
    # @dimensions text-asset, mimetype
    @property
    def is_text_file(self):
        mimetype = self.entity.mimetype
        return bool(mimetype and mimetype in files.TEXT_MIMETYPES.values())

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_text_asset_extractable_only_for_non_text_document_ai_mimetypes
    # @features file
    # @dimensions extractable, mimetype
    @property
    def extractable(self):
        mimetype = self.entity.mimetype
        return bool(
            mimetype
            and not self.is_text_file
            and mimetype in files.DOCUMENT_AI_MIMETYPES
        )

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_as_html
    # @tests tests_unit/test_006_file_properties.py::test_text_asset_falls_back_to_original_text_file
    # @tests tests_unit/test_006_file_properties.py::test_text_asset_skips_oversized_original_before_download
    # @tests tests_unit/test_006_file_properties.py::test_extract_update_completes_immediately_for_text_files
    # @features file
    # @dimensions text-asset, fallback, extract, process-complete
    @property
    def value(self):
        if self.is_set:
            return self._value

        stored_asset = self.entity.get_asset(self.id)
        if stored_asset:
            self._value = True
        elif self.is_text_file and self.entity.get_asset("file") and self.entity.encoding:
            self._value = True
        else:
            self._value = None

        return self._value

    @value.setter
    def value(self, value):
        self._markup = UNSET
        AssetProperty.value.fset(self, value)
        self._value = True if value else None

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_text_asset_falls_back_to_original_text_file
    # @features file
    # @dimensions text-asset, fallback
    @property
    def asset(self):
        if getattr(self, "_asset", UNSET) is not UNSET:
            return self._asset

        stored_asset = self.entity.get_asset(self.id)
        if stored_asset:
            self._asset = stored_asset.get()
            return self._asset

        file_asset = self.entity.get_asset("file")
        encoding = self.entity.encoding

        if file_asset and encoding and self.is_text_file:
            try:
                enforce_file_consumer(
                    getattr(file_asset, "size", None),
                    FileConsumer.TEXT_PREVIEW,
                    filename=getattr(self.entity, "filename", None),
                )
            except FileConsumerLimitError:
                self._asset = None
                return self._asset
            self._asset = file_asset.text()
            return self._asset
        else:
            self._asset = None

        return self._asset

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_as_html
    # @tests tests_unit/test_006_file_properties.py::test_text_asset_falls_back_to_original_text_file
    # @features file
    # @dimensions html-preview, text-asset, fallback
    @property
    def markup(self):
        if getattr(self, "_markup", UNSET) is not UNSET:
            return self._markup

        text = self.asset
        self._markup = files.htmlize(text, self.entity.mimetype) if text else None
        return self._markup

    @property
    def cache_value(self):
        extract = self.entity.properties.get("extract")
        if extract and extract.search:
            return self.asset

    @property
    def cache_key(self):
        return "doc"


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_import_wizard_story_parses_the_uploaded_csv_into_rows_and_columns
# @features ingress
# @dimensions rows asset-storage
class Rows(AssetProperty):
    """Parsed CSV rows for an ingress file. Stored as a JSON asset.

    Set:
        value: Row data from the ProcessCSV stage.

    Get:
        asset (list[dict]): Row dicts keyed by column ID.
    """

    _id = "rows"
    _asset_type = "json"


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_importer_story_processes_page_rows_into_entities_and_results
# @tests tests_unit/test_006b_ingress_entity.py::test_completed_ingress_shows_results
# @tests tests_unit/test_006b_ingress_entity.py::test_results_asset_loads_stored_json_without_recursing
# @pair ingress:row-results
# @pair ingress:asset-storage
# @pair ingress:regression
# @pair ingress:completed
class Results(AssetProperty):
    """Import results for an ingress file. Stored as a JSON asset.

    Each result dict contains the row data, created entity details,
    and any warnings or errors from validation.

    Get:
        value (list[dict]): Import result dicts (defaults to []).
    """

    _id = "results"
    _asset_type = "json"

    @property
    def value(self):
        slots = self.slots
        if self.entity.db.get("ingress_format") != 1:
            return slots
        execution = self.entity.get_process("execution")
        cursor = max(0, int(execution.get("cursor") or 0))
        if cursor >= len(slots):
            return slots
        return [result for result in slots[:cursor] if result is not None]

    @value.setter
    def value(self, value):
        self.save_slots(value or [])

    @property
    def slots(self):
        """Return all written result slots, including uncommitted tail slots."""
        if getattr(self, "_asset", UNSET) is not UNSET:
            return self._asset

        stored_asset = AssetProperty.value.fget(self)
        if stored_asset:
            self._asset = stored_asset.get() or []
        else:
            self._asset = []

        return self._asset

    def save_slots(self, value):
        """Write indexed result slots before the cursor transaction publishes them."""
        AssetProperty.value.fset(self, value)
        self._asset = value or []

    def save(self):
        self.save_slots(getattr(self, "_asset", None) or [])
