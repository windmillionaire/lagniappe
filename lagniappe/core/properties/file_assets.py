from typing import TYPE_CHECKING, Any, Protocol, TypedDict, cast

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage
    from ..definitions.asset import FileAsset as StoredFile, TextAsset as StoredText
    from .file_options import Extract
    from ..entities.file import File
    from ..entities.ingress import Ingress
    from ..tools.database.assets import DirectUploadFile
    from ..tools.ingress import CsvRow
    from ..tools.files.html import SafeHTML

from ..mixins import CacheMixin
from ..definitions import (
    FileConsumer,
    FileConsumerLimitError,
    enforce_file_consumer,
)
from ..tools.files import constants as file_constants
from ..tools.files import html as file_html
from ..tools.files import utility as file_utility
from .base_asset import AssetProperty
from .base_property import UNSET


type _FileOwner = File | Ingress


class FilePart(TypedDict):
    uri: str
    mime_type: str


class _PreparedUpload(Protocol):
    lagniappe_content_type: str | None


class FileAsset(AssetProperty[_FileOwner, "StoredFile", "FileStorage | DirectUploadFile"]):
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
    def value(self) -> StoredFile | None:
        return cast("StoredFile | None", super().value)

    @value.setter
    def value(self, value: FileStorage | DirectUploadFile) -> None:
        upload = value
        mimetype = upload.content_type or self.entity.mimetype
        self.entity.mimetype = file_utility.determine_mimetype(
            upload, self.entity.filename, mimetype, self.entity.encoding
        )

        if self.entity.mimetype in file_constants.TEXT_MIMETYPES.values():
            self.entity.encoding = file_utility.determine_encoding(upload)

        cast(_PreparedUpload, upload).lagniappe_content_type = self.entity.mimetype
        self._store_asset_value(upload)

    @property
    def url(self) -> str | None:
        return self.value.url if self.value else None

    @property
    def preview(self) -> str | None:
        mimetype = self.entity.mimetype
        if mimetype and mimetype in file_constants.PREVIEW_MIMETYPES:
            return self.url
        return None

    @property
    def image(self) -> str | None:
        mimetype = self.entity.mimetype
        if mimetype and mimetype in file_constants.IMAGE_MIMETYPES:
            return self.url
        return None

    @property
    def uri(self) -> str | None:
        return self.value.uri if self.value else None

    @property
    def uri_to_ai(self) -> FilePart | None:
        from ..tools.ai.constants import gemini_mimetype

        mime_type = gemini_mimetype(self.entity.mimetype)
        if not mime_type:
            return None

        uri = self.uri
        if not uri:
            return None
        return {"uri": uri, "mime_type": mime_type}


class TextAsset(CacheMixin, AssetProperty[_FileOwner, bool, "str | None"]):
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

    @property
    def is_text_file(self) -> bool:
        mimetype = self.entity.mimetype
        return bool(
            mimetype and mimetype in file_constants.TEXT_MIMETYPES.values()
        )

    @property
    def extractable(self) -> bool:
        mimetype = self.entity.mimetype
        return bool(
            mimetype
            and not self.is_text_file
            and mimetype in file_constants.DOCUMENT_AI_MIMETYPES
        )

    @property
    def value(self) -> bool | None:
        if self.is_set:
            return cast("bool | None", self._value)

        stored_asset = cast("StoredText | None", self.entity.get_asset(self.id))
        if stored_asset or self.is_text_file and self.entity.get_asset("file") and self.entity.encoding:
            self._value = True
        else:
            self._value = None

        return self._value

    @value.setter
    def value(self, value: str | None) -> None:
        self._markup = UNSET
        self._store_asset_value(value)
        self._value = True if value else None

    @property
    def asset(self) -> str | None:
        if getattr(self, "_asset", UNSET) is not UNSET:
            return cast("str | None", self._asset)

        stored_asset = cast("StoredText | None", self.entity.get_asset(self.id))
        if stored_asset:
            self._asset = stored_asset.get()
            return self._asset

        file_asset = cast("StoredFile | None", self.entity.get_asset("file"))
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

    @property
    def markup(self) -> SafeHTML | None:
        if getattr(self, "_markup", UNSET) is not UNSET:
            return cast("SafeHTML | None", self._markup)

        text = self.asset
        self._markup = (
            file_html.htmlize(text, self.entity.mimetype) if text else None
        )
        return cast("SafeHTML | None", self._markup)

    @property
    def cache_value(self) -> str | None:
        extract = cast("Extract | None", self.entity.properties.get("extract"))
        if extract and extract.search:
            return self.asset

    @property
    def cache_key(self) -> str:
        return "doc"


class Rows(AssetProperty["Ingress"]):
    """Parsed CSV rows for an ingress file. Stored as a JSON asset.

    Set:
        value: Row data from the ProcessCSV stage.

    Get:
        asset (list[dict]): Row dicts keyed by column ID.
    """

    if TYPE_CHECKING:
        @property
        def asset(self) -> list[CsvRow] | None: ...

    _id = "rows"
    _asset_type = "json"


class Results(AssetProperty["Ingress", "list[dict[str, Any] | None]", "list[dict[str, Any] | None] | None"]):
    """Import results for an ingress file. Stored as a JSON asset.

    Each result dict contains the row data, created entity details,
    and any warnings or errors from validation.

    Get:
        value (list[dict]): Import result dicts (defaults to []).
    """

    _id = "results"
    _asset_type = "json"

    @property
    def value(self) -> list[dict[str, Any] | None]:
        slots = self.slots
        if self.entity.db.get("ingress_format") != 1:
            return slots
        execution = self.entity.get_process("execution")
        cursor = max(0, int(cast(int, execution.get("cursor") or 0)))
        if cursor >= len(slots):
            return slots
        return [result for result in slots[:cursor] if result is not None]

    @value.setter
    def value(self, value: list[dict[str, Any] | None] | None) -> None:
        self.save_slots(value or [])

    @property
    def slots(self) -> list[dict[str, Any] | None]:
        """Return all written result slots, including uncommitted tail slots."""
        if getattr(self, "_asset", UNSET) is not UNSET:
            return self._asset

        stored_asset = self._stored_asset()
        if stored_asset:
            self._asset = cast("list[dict[str, Any] | None]", stored_asset.get() or [])
        else:
            self._asset = []

        return self._asset

    def save_slots(self, value: list[dict[str, Any] | None]) -> None:
        """Write indexed result slots before the cursor transaction publishes them."""
        self._store_asset_value(value)
        self._asset = value or []

    def save(self) -> None:
        self.save_slots(getattr(self, "_asset", None) or [])
