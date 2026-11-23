"""Asset type and visibility definitions."""

import hashlib
import json
import re
from enum import Enum
from typing import TYPE_CHECKING, BinaryIO, Protocol, TypedDict, cast

if TYPE_CHECKING:
    from google.cloud.datastore import Key
    from werkzeug.datastructures import FileStorage

from smartypants import smartypants

from lagniappe import CONFIG

from .file_consumers import (
    FileConsumer,
    LARGE_ASSET_BYTES,
    enforce_file_consumer,
)
from lagniappe.core.tools.database import assets as database_assets
from lagniappe.core.tools.database import get as database_get
from ..tools.files.html import strip_tags
from .default import DefaultEnum

IMAGE_NAME = re.compile(r"image_[^.\"]+")
MIMETYPE_EXTENSIONS = {
    "text/plain": "txt",
}

PUBLIC_BUCKET = CONFIG.PUBLIC_BUCKET
PRIVATE_BUCKET = CONFIG.PRIVATE_BUCKET
BUCKET_PREFIX = CONFIG.PREFIX


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_asset_uri_and_public_url_include_bucket_prefix
# @matrix file storage : bucket-prefix
def storage_bucket_name(bucket: str) -> str:
    return f"{BUCKET_PREFIX}{bucket}"


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_asset_uri_and_public_url_include_bucket_prefix
# @matrix file storage : bucket-prefix public-url
def public_url() -> str:
    return f"https://storage.googleapis.com/{storage_bucket_name(PUBLIC_BUCKET)}"


PUBLIC_URL = public_url()


class AssetVisibility(Enum, metaclass=DefaultEnum):
    """Asset access levels: private (downloads from GCS) or public (direct URL to GCS)."""

    private = "private"
    public = "public"

    DEFAULT = private


# @testable infrastructure
# @covered-by lagniappe/core/mixins/assets.py::AssetMixin.get_asset
# @covered-by lagniappe/core/mixins/assets.py::AssetMixin.save_asset
class AssetDefinition(TypedDict, total=False):
    type: str | None
    visibility: str
    path: str
    fingerprint: str
    large: bool | None
    size: int
    generation: str


class AssetOwner(Protocol):
    @property
    def key(self) -> Key | None: ...
    @property
    def hash(self) -> str: ...
    def delete_asset(self, name: str) -> None: ...


class _EncodedOwner(AssetOwner, Protocol):
    @property
    def encoding(self) -> str: ...


type AssetUpload = BinaryIO | FileStorage | database_assets.DirectUploadFile


type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]


class Asset[ReadResult = str, WriteContent = str]:
    """Typed wrapper for an asset definition dict.

    Wraps a plain definition dict and exposes type, visibility, path,
    and fingerprint as attributes. Subclasses implement type-specific
    get/save/delete behaviour.
    """

    _content_type: str | None = None
    _type: str | None = None
    _visibility = "private"
    _path: str | None = None
    _fingerprint: str | None = None
    _size: int | None = None
    _large: bool | None = None
    _generation: str | None = None

    def __init__(
        self, definition: AssetDefinition | None = None, *, name: str | None = None,
        entity: AssetOwner | None = None,
    ) -> None:
        definition = definition or {}
        self._visibility = definition.get("visibility", "private")
        self._path = definition.get("path")
        self._fingerprint = definition.get("fingerprint")
        self._size = definition.get("size")
        self._large = definition.get("large")
        self._generation = definition.get("generation")
        self.name = name
        self.entity = entity

    @property
    def _owner(self) -> AssetOwner:
        if self.entity is None:
            raise AttributeError("This asset has no owning entity.")
        return self.entity

    @property
    def type(self) -> str | None:
        return self._type

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_text_plain_asset_uses_txt_extension
    # @tests tests_unit/test_006_file_properties.py::test_file_asset_detects_mislabeled_png_upload
    # @matrix file storage : asset-extension mimetype
    @property
    def path(self) -> str:
        if not self._path:
            self._path = f"{self._owner.hash}_{self.name}.{self.extension}"
        return self._path

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_image_asset_content_type_falls_back_without_recursing
    # @matrix file : content-type image
    @property
    def content_type(self) -> str | None:
        return self._content_type

    @content_type.setter
    def content_type(self, value: str | None) -> None:
        if value and not self._content_type:
            self._content_type = value

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_text_plain_asset_uses_txt_extension
    # @tests tests_unit/test_006_file_properties.py::test_file_asset_detects_mislabeled_png_upload
    # @matrix file storage : asset-extension mimetype
    @property
    def extension(self) -> str | None:
        if self._path:
            return self._path.split(".")[-1]
        elif self.content_type is not None and self.content_type in MIMETYPE_EXTENSIONS:
            return MIMETYPE_EXTENSIONS[self.content_type]
        elif self.content_type and self.content_type != "application/octet-stream":
            return self.content_type.split("/")[-1]
        return None

    @property
    def fingerprint(self) -> str | None:
        return self._fingerprint

    @fingerprint.setter
    def fingerprint(self, value: str | None) -> None:
        self._fingerprint = value

    @property
    def size(self) -> int | None:
        if self._size is None:
            return None
        return int(self._size)

    @size.setter
    def size(self, value: int | str | None) -> None:
        self._size = int(value) if value is not None else None
        self._large = self._size > LARGE_ASSET_BYTES if self._size is not None else None

    @property
    def large(self) -> bool | None:
        if self._large is not None:
            return bool(self._large)
        if self.size is None:
            return None
        return self.size > LARGE_ASSET_BYTES

    @property
    def generation(self) -> str | None:
        return str(self._generation) if self._generation is not None else None

    @generation.setter
    def generation(self, value: str | int | None) -> None:
        self._generation = str(value) if value is not None else None

    @property
    def visibility(self) -> AssetVisibility:
        return AssetVisibility[self._visibility]

    @visibility.setter
    def visibility(self, value: str) -> None:
        visibility = AssetVisibility[value]
        if visibility == AssetVisibility.public:
            self._visibility = value

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_asset_uri_and_public_url_include_bucket_prefix
    # @matrix file storage : asset-uri bucket-prefix
    @property
    def uri(self) -> str:
        bucket = (
            PUBLIC_BUCKET
            if self.visibility == AssetVisibility.public
            else PRIVATE_BUCKET
        )
        return f"gs://{storage_bucket_name(bucket)}/{self.path}"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_file_asset_definition_records_size_and_large_flag
    # @matrix file storage : asset-size large-asset
    @property
    def definition(self) -> AssetDefinition:
        definition: AssetDefinition = {
            "type": self.type,
            "path": self.path,
        }
        if self.visibility == AssetVisibility.public:
            definition["visibility"] = "public"
        if self.fingerprint:
            definition["fingerprint"] = self.fingerprint
        if self.size is not None:
            definition["size"] = self.size
            definition["large"] = self.large
        if self.generation:
            definition["generation"] = self.generation
        return definition

    def _record_saved_blob(self, blob: object) -> None:
        size = getattr(blob, "size", None)
        if size is not None:
            self.size = size
        generation = getattr(blob, "generation", None)
        if generation is not None:
            self.generation = generation

    @property
    def cache_value(self) -> str | None:
        return None

    # @testable true
    # @matrix storage : generation-pinned read copy
    def get(self) -> ReadResult | str:
        return self._read_text()

    def _read_text(self) -> str:
        return database_assets.get_text(
            self.path, self.visibility.value,
            **({"generation": self.generation} if self.generation else {}),
        )

    def delete(self) -> None:
        database_assets.delete_file(self.path, self.visibility.value)

    def save(self, content: WriteContent) -> bool:
        if not content:
            return False

        # Binary assets override save, and JSONAsset encodes before using this text writer.
        blob = database_assets.save_text(
            cast(str, content), self.path, self.content_type, self.visibility.value
        )
        self._record_saved_blob(blob)
        return True


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_assets.py::Document.add_image
# @covered-by lagniappe/core/properties/file_assets.py::FileAsset.preview
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.asset
class FileAsset(Asset[bytes | None, AssetUpload]):
    _type = "file"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_private_asset_url_uses_asset_name_for_shared_storage_path
    # @matrix file storage : private-url shared-asset-path
    @property
    def url(self) -> str | None:
        if self.visibility == AssetVisibility.public:
            return f"{public_url()}/{self.path}"
        elif self.visibility == AssetVisibility.private:
            key = database_get.urlsafe_key(self._owner.key)
            identifier = (
                f"{self.name}.{self.extension}" if self.extension else self.name
            )
            return f"/assets/{key}/{identifier}"
        return None

    def get(self) -> bytes | None:
        return database_assets.download_file(self.path, self.visibility.value)

    def text(self) -> str:
        return database_assets.get_text(
            self.path, self.visibility.value, cast(_EncodedOwner, self._owner).encoding
        )

    def save(self, content: AssetUpload) -> bool:
        if not content:
            return False

        if not getattr(content, "lagniappe_direct_upload", False):
            content.seek(0)
        blob = database_assets.save_file(
            content, self.path, self.content_type, self.visibility.value
        )
        self._record_saved_blob(blob)
        return True


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_assets.py::Document.add_image
class ImageAsset(FileAsset):
    _type = "image"

    # @testable false
    # @covered-by lagniappe/core/properties/common_assets.py::Document.add_image
    # @reason image fingerprinting is a storage detail of document image uploads
    def save(self, content: AssetUpload) -> bool:
        if not content:
            return False

        super().save(content)
        direct_fingerprint = getattr(content, "md5_hex", None)
        if direct_fingerprint:
            self.fingerprint = direct_fingerprint
        else:
            enforce_file_consumer(
                content,
                FileConsumer.IMAGE_FINGERPRINT,
                filename=getattr(content, "filename", None),
            )
            content.seek(0)
            self.fingerprint = hashlib.md5(content.read()).hexdigest()
        return True

    @property
    def content_type(self) -> str:
        if self._content_type:
            return self._content_type
        elif self._path and self._path.endswith(".png"):
            return "image/png"
        elif self._path and self._path.endswith(".gif"):
            return "image/gif"
        elif self._path and self._path.endswith(".webp"):
            return "image/webp"

        return "image/jpeg"

    @content_type.setter
    def content_type(self, value: str | None) -> None:
        if value and not self._content_type:
            self._content_type = value


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_assets.py::Document.save
# @covered-by lagniappe/web/routes/assets/editor.py::get_document_history
class HTMLAsset(Asset):
    _content_type = "text/html"
    _type = "html"
    _updated = False

    # @testable false
    # @covered-by lagniappe/web/routes/assets/editor.py::get_document_history
    # @reason stored HTML rendering is exposed through document/history responses
    def html(self) -> str:
        return smartypants(self.get())

    def delete(self) -> None:
        html = self.get()

        for image in IMAGE_NAME.findall(html):
            self._owner.delete_asset(image)

        super().delete()

    @property
    def updated(self) -> bool:
        return self._updated

    # @testable false
    # @covered-by lagniappe/core/properties/common_assets.py::Document.save
    # @reason HTML fingerprint and updated-state checks are owned by document save behavior
    def save(self, content: str) -> bool:
        if not content:
            return False

        html = content.strip()
        fingerprint = hashlib.md5(html.encode("utf-8")).hexdigest()
        if self.fingerprint != fingerprint:
            super().save(html)
            self.fingerprint = fingerprint
            self._updated = True

        return True

    @property
    def cache_value(self) -> str:
        return strip_tags(self.get()).strip()


# @testable infrastructure
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.asset
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.markup
class TextAsset(Asset):
    _type = "text"

    @property
    def content_type(self) -> str:
        return self._content_type or "text/plain"

    @content_type.setter
    def content_type(self, value: str | None) -> None:
        if value and not self._content_type:
            self._content_type = value

    @property
    def extension(self) -> str | None:
        return (
            "txt"
            if self.content_type == "text/plain"
            else self.content_type.split("/")[-1]
        )

    @property
    def cache_value(self) -> str:
        return self.get().strip()


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_assets.py::Document.save
class YDocAsset(Asset):
    _content_type = "text/plain"
    _type = "ydoc"

    @property
    def extension(self) -> str | None:
        return "ydoc"


# @testable infrastructure
# @covered-by lagniappe/core/properties/file_assets.py::Results.save
class JSONAsset(Asset[JSONValue, JSONValue]):
    _content_type = "application/json"
    _type = "json"

    def get(self) -> JSONValue:
        return json.loads(self._read_text())

    def save(self, content: JSONValue) -> bool:
        if not content:
            return False
        return super().save(json.dumps(content))


class AssetTypes(Enum, metaclass=DefaultEnum):
    """Storage types for entity assets. Used by AssetMixin."""

    IMAGE = ImageAsset
    HTML = HTMLAsset
    TEXT = TextAsset
    YDOC = YDocAsset
    FILE = FileAsset
    JSON = JSONAsset

    DEFAULT = None


type StoredAsset = TextAsset | YDocAsset | JSONAsset | HTMLAsset | FileAsset | ImageAsset
type AssetContent = JSONValue | AssetUpload
