from typing import TYPE_CHECKING, cast

from ..mixins import AIMixin, CacheMixin
from ..tools.files import constants as file_constants
from ..tools.files.html import strip_tags
from .base_db import DBProperty
from .base_property import Property
from .common_entity import Name

if TYPE_CHECKING:
    from ..entities.file import File
    from ..definitions.asset import FileAsset as StoredFile
    from ..tools.files.html import SafeHTML


type _File = File
type _HTML = SafeHTML


class DisplayName(Name):
    """Display name for a File entity.

    Falls back to the filename (without extension) if no name has been
    explicitly set.

    Get:
        value (str): Explicit name or filename stem.
    """

    @property
    def value(self) -> str | None:
        if self.is_set:
            return super().value

        filename = cast("File", self.entity).filename
        self._value = self.entity.db.get("name") or (filename.rsplit(".", 1)[0] if filename else None)
        return super().value

    @value.setter
    def value[Part](self, value: str | list[Part] | None) -> None:
        setter = Name.value.fset
        assert setter is not None
        setter(self, value)

    @property
    def ai_key(self) -> str:
        return "display_name"


class Filename(AIMixin, DBProperty[str, _File]):
    """Original filename of the uploaded file."""

    _id = "filename"
    _label = "Filename"
    _icon = "file"

    @property
    def ai_key(self) -> str:
        return self.id


class Mimetype(AIMixin, DBProperty[str, _File]):
    """MIME type of the uploaded file. Determined on upload.

    Always returns a string (empty if unset) so callers can safely
    use string methods like ``startswith`` without a None guard.
    """

    _id = "mimetype"
    _label = "Mimetype"
    _icon = "file"

    @property
    def ai_key(self) -> str:
        return self.id

    @property
    def value(self) -> str:
        return super().value or ""

    @value.setter
    def value(self, value: str | None) -> None:
        self._write_db_value(value)


class Encoding(DBProperty[str, _File]):
    """Character encoding for text files. Determined on upload."""

    _id = "encoding"
    _label = "Encoding"
    _icon = "file"

    @property
    def value(self) -> str | None:
        return super().value

    @value.setter
    def value(self, value: str | None) -> None:
        self._write_db_value(value)


class Size(Property[int, _File]):
    """Stored byte size for the uploaded file, when known."""

    _id = "size"
    _label = "Size"
    _icon = "file"

    @property
    def value(self) -> int | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        if self.is_set:
            return super().value

        asset = self.entity.properties.file.value
        if not asset:
            self._value = None
            return super().value

        size = asset.size
        self._value = int(size) if size is not None else None
        return super().value


class Large(AIMixin, Property[bool, _File]):
    """Whether the uploaded file is too large to attach to AI by default."""

    _id = "large"
    _label = "Large"
    _icon = "file"

    @property
    def ai_key(self) -> str:
        return self.id

    @property
    def value(self) -> bool | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        if self.is_set:
            return super().value

        asset = self.entity.properties.file.value
        if not asset:
            self._value = None
            return super().value

        large = asset.large
        self._value = bool(large) if large is not None else None
        return super().value


class Preview(Property[str, _File]):
    """Preview URL for a file, if the mimetype supports inline preview.

    Get:
        value (str | None): Signed URL for preview, or None.
    """

    _id = "preview"
    _label = "Preview"
    _icon = "image"

    @property
    def value(self) -> str | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        if self.is_set:
            return super().value

        mimetype = self.entity.mimetype
        if mimetype and mimetype in file_constants.PREVIEW_MIMETYPES:
            file = cast("StoredFile | None", self.entity.get_asset("file"))
            if file:
                self._value = file.url
            else:
                self._value = None
        else:
            self._value = None

        return super().value


class AsHTML(Property[_HTML, _File]):
    """HTML rendering of the file's text content (for .rtf, .md, etc).

    Get:
        value (str | None): Converted HTML, or None if no text content.
    """

    _id = "html"

    @property
    def value(self) -> _HTML | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        if self.is_set:
            return super().value

        self._value = self.entity.properties.text.markup

        return super().value


class Summary(CacheMixin, AIMixin, DBProperty[str, _File]):
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
    def ai_key(self) -> str:
        return self.id

    @property
    def value(self) -> str | None:
        return super().value

    @value.setter
    def value(self, value: str | None) -> None:
        if isinstance(value, str):
            value = strip_tags(value, preserve_whitespace=True).strip()
        self._write_db_value(value)

    @property
    def cache_value(self) -> str | None:
        if self.entity.properties.summarize.search:
            return self.value

    @property
    def cache_key(self) -> str:
        return "desc"
