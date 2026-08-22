from ..mixins import AIMixin, CacheMixin
from ..tools import files
from ..tools.files.html import strip_tags
from .base_db import DBProperty
from .base_property import Property
from .common_entity import Name


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_display_name
# @features file
# @dimensions display-name filename-fallback
class DisplayName(Name):
    """Display name for a File entity.

    Falls back to the filename (without extension) if no name has been
    explicitly set.

    Get:
        value (str): Explicit name or filename stem.
    """

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_display_name
    # @features file
    # @dimensions display-name, filename-fallback
    @property
    def value(self):
        if self.is_set:
            return super().value

        self._value = (
            self.entity.db.get("name") or self.entity.filename.rsplit(".", 1)[0]
        )
        return self._value

    @value.setter
    def value(self, value):
        Name.value.fset(self, value)

    @property
    def ai_key(self):
        return "display_name"


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_filename_mimetype_encoding
# @features file
# @dimensions property
class Filename(AIMixin, DBProperty):
    """Original filename of the uploaded file."""

    _id = "filename"
    _label = "Filename"
    _icon = "file"

    @property
    def ai_key(self):
        return self.id


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_filename_mimetype_encoding
# @tests tests_unit/test_006_file_properties.py::test_text_asset_extractable_only_for_non_text_document_ai_mimetypes
# @tests tests_unit/test_006_file_properties.py::test_preview_url_when_mimetype_supported_and_file_present
# @tests tests_unit/test_006_file_properties.py::test_preview_none_when_mimetype_not_supported
# @features file
# @dimensions property, mimetype, extractable, preview, unsupported
class Mimetype(AIMixin, DBProperty):
    """MIME type of the uploaded file. Determined on upload.

    Always returns a string (empty if unset) so callers can safely
    use string methods like ``startswith`` without a None guard.
    """

    _id = "mimetype"
    _label = "Mimetype"
    _icon = "file"

    @property
    def ai_key(self):
        return self.id

    @property
    def value(self):
        return super().value or ""

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_filename_mimetype_encoding
# @features file
# @dimensions property, encoding
class Encoding(DBProperty):
    """Character encoding for text files. Determined on upload."""

    _id = "encoding"
    _label = "Encoding"
    _icon = "file"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        DBProperty.value.fset(self, value)


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_file_size_and_large_use_asset_metadata
# @features file
# @dimensions asset-metadata size
class Size(Property):
    """Stored byte size for the uploaded file, when known."""

    _id = "size"
    _label = "Size"
    _icon = "file"

    @property
    def value(self):
        if self.is_set:
            return self._value

        asset = self.entity.properties.file.value
        if not asset:
            self._value = None
            return self._value

        size = asset.size
        self._value = int(size) if size is not None else None
        return self._value


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_file_to_ai_exports_metadata_and_uri_to_ai
# @tests tests_unit/test_006_file_properties.py::test_file_size_and_large_use_asset_metadata
# @pair file:large-file
# @pair ai:large-file
# @pair file:asset-metadata
class Large(AIMixin, Property):
    """Whether the uploaded file is too large to attach to AI by default."""

    _id = "large"
    _label = "Large"
    _icon = "file"

    @property
    def ai_key(self):
        return self.id

    @property
    def value(self):
        if self.is_set:
            return self._value

        asset = self.entity.properties.file.value
        if not asset:
            self._value = None
            return self._value

        large = asset.large
        self._value = bool(large) if large is not None else None
        return self._value


# @testable false
# @covered-by lagniappe/core/properties/file_entity.py::Preview.value
# @reason preview behavior is owned by the value accessor
class Preview(Property):
    """Preview URL for a file, if the mimetype supports inline preview.

    Get:
        value (str | None): Signed URL for preview, or None.
    """

    _id = "preview"
    _label = "Preview"
    _icon = "image"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_preview_url_when_mimetype_supported_and_file_present
    # @tests tests_unit/test_006_file_properties.py::test_preview_none_when_mimetype_not_supported
    # @tests tests_unit/test_006_file_properties.py::test_preview_none_when_no_file_asset
    # @features file
    # @dimensions preview, mimetype, asset, unsupported, missing-asset
    @property
    def value(self):
        if self.is_set:
            return self._value

        mimetype = self.entity.mimetype
        if mimetype and mimetype in files.PREVIEW_MIMETYPES:
            file = self.entity.get_asset("file")
            if file:
                self._value = file.url
            else:
                self._value = None
        else:
            self._value = None

        return self._value


# @testable false
# @covered-by lagniappe/core/properties/file_entity.py::AsHTML.value
# @reason HTML preview behavior is owned by the value accessor
class AsHTML(Property):
    """HTML rendering of the file's text content (for .rtf, .md, etc).

    Get:
        value (str | None): Converted HTML, or None if no text content.
    """

    _id = "html"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_as_html
    # @tests tests_unit/test_006_file_properties.py::test_text_asset_falls_back_to_original_text_file
    # @features file
    # @dimensions html-preview, text-asset, fallback
    @property
    def value(self):
        if self.is_set:
            return self._value

        self._value = self.entity.properties.text.markup

        return self._value


# @testable false
# @covered-by lagniappe/core/properties/file_entity.py::Summary.value
# @covered-by lagniappe/core/properties/file_entity.py::Summary.cache_value
# @reason summary behavior is owned by value sanitization and cache projection
class Summary(CacheMixin, AIMixin, DBProperty):
    """User-facing description/AI-generated summary of a file's content.

    Set:
        value (str): Description text.

    Get:
        value (str): Description text.

    Overrides:
        cache_value: Returns value only if description search is enabled.
        cache_key: Returns "desc".
    """

    _id = "summary"
    _label = "Summary"
    _icon = "text"

    @property
    def ai_key(self):
        return self.id

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_summary
    # @tests tests_unit/test_014_security.py::test_file_summary_strips_tags
    # @features file, security
    # @dimensions summary, html-stripping
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if isinstance(value, str):
            value = strip_tags(value).strip()
        DBProperty.value.fset(self, value)

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_summary
    # @tests tests_unit/test_006_file_properties.py::test_file_description_form_field_populates_search_cache
    # @features file
    # @dimensions cache
    @property
    def cache_value(self):
        if self.entity.properties.summarize.search:
            return self.value

    @property
    def cache_key(self):
        return "desc"
