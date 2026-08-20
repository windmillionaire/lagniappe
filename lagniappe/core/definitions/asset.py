"""Asset type and visibility definitions."""

import hashlib
import json
import re
from enum import Enum

from smartypants import smartypants

from lagniappe import CONFIG

from .file_consumers import (
    FileConsumer,
    LARGE_ASSET_BYTES,
    enforce_file_consumer,
)
from ..tools import database, utility
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
# @features file storage
# @dimensions bucket-prefix
def storage_bucket_name(bucket):
    return f"{BUCKET_PREFIX}{bucket}"


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_asset_uri_and_public_url_include_bucket_prefix
# @features file storage
# @dimensions bucket-prefix public-url
def public_url():
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
class Asset:
    """Typed wrapper for an asset definition dict.

    Wraps a plain definition dict and exposes type, visibility, path,
    and fingerprint as attributes. Subclasses implement type-specific
    get/save/delete behaviour.
    """

    _content_type = None
    _type = None
    _visibility = None
    _path = None
    _fingerprint = None
    _size = None
    _large = None

    def __init__(self, definition=None, *, name=None, entity=None):
        definition = definition or {}
        self._visibility = definition.get("visibility", "private")
        self._path = definition.get("path")
        self._fingerprint = definition.get("fingerprint")
        self._size = definition.get("size")
        self._large = definition.get("large")
        self.name = name
        self.entity = entity

    @property
    def type(self):
        return self._type

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_text_plain_asset_uses_txt_extension
    # @tests tests_unit/test_006_file_properties.py::test_file_asset_detects_mislabeled_png_upload
    # @features file storage
    # @dimensions asset-extension mimetype
    @property
    def path(self):
        if not self._path:
            self._path = f"{self.entity.hash}_{self.name}.{self.extension}"
        return self._path

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_image_asset_content_type_falls_back_without_recursing
    # @features file
    # @dimensions image content-type
    @property
    def content_type(self):
        return self._content_type

    @content_type.setter
    def content_type(self, value):
        if value and not self._content_type:
            self._content_type = value

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_text_plain_asset_uses_txt_extension
    # @tests tests_unit/test_006_file_properties.py::test_file_asset_detects_mislabeled_png_upload
    # @features file storage
    # @dimensions asset-extension mimetype
    @property
    def extension(self):
        if self._path:
            return self._path.split(".")[-1]
        elif self.content_type in MIMETYPE_EXTENSIONS:
            return MIMETYPE_EXTENSIONS[self.content_type]
        elif self.content_type and self.content_type != "application/octet-stream":
            return self.content_type.split("/")[-1]
        return None

    @property
    def fingerprint(self):
        return self._fingerprint

    @fingerprint.setter
    def fingerprint(self, value):
        self._fingerprint = value

    @property
    def size(self):
        if self._size is None:
            return None
        return int(self._size)

    @size.setter
    def size(self, value):
        self._size = int(value) if value is not None else None
        self._large = self._size > LARGE_ASSET_BYTES if self._size is not None else None

    @property
    def large(self):
        if self._large is not None:
            return bool(self._large)
        if self.size is None:
            return None
        return self.size > LARGE_ASSET_BYTES

    @property
    def visibility(self):
        return AssetVisibility[self._visibility]

    @visibility.setter
    def visibility(self, value):
        visibility = AssetVisibility[value]
        if visibility == AssetVisibility.public:
            self._visibility = value

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_asset_uri_and_public_url_include_bucket_prefix
    # @features file storage
    # @dimensions asset-uri bucket-prefix
    @property
    def uri(self):
        bucket = (
            PUBLIC_BUCKET
            if self.visibility == AssetVisibility.public
            else PRIVATE_BUCKET
        )
        return f"gs://{storage_bucket_name(bucket)}/{self.path}"

    @property
    def definition(self):
        definition = {
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
        return definition

    def _record_saved_blob(self, blob):
        size = getattr(blob, "size", None)
        if size is not None:
            self.size = size

    @property
    def cache_value(self):
        return None

    def get(self):
        return database.assets.get_text(self.path, self.visibility.value)

    def delete(self):
        database.assets.delete_file(self.path, self.visibility.value)

    def save(self, content):
        if not content:
            return False

        database.assets.save_text(
            content, self.path, self.content_type, self.visibility.value
        )
        return True


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_assets.py::Document.add_image
# @covered-by lagniappe/core/properties/file_assets.py::FileAsset.preview
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.asset
class FileAsset(Asset):
    _type = "file"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_private_asset_url_uses_asset_name_for_shared_storage_path
    # @features file storage
    # @dimensions private-url shared-asset-path
    @property
    def url(self):
        if self.visibility == AssetVisibility.public:
            return f"{public_url()}/{self.path}"
        elif self.visibility == AssetVisibility.private:
            key = database.get.urlsafe_key(self.entity.key)
            identifier = f"{self.name}.{self.extension}" if self.extension else self.name
            return f"/assets/{key}/{identifier}"
        return None

    def get(self):
        return database.assets.download_file(self.path, self.visibility.value)

    def text(self):
        return database.assets.get_text(
            self.path, self.visibility.value, self.entity.encoding
        )

    def save(self, content):
        if not content:
            return False

        if not getattr(content, "lagniappe_direct_upload", False):
            content.seek(0)
        blob = database.assets.save_file(
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
    def save(self, content):
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
    def content_type(self):
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
    def content_type(self, value):
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
    def html(self):
        return smartypants(self.get())

    def delete(self):
        html = self.get()

        for image in IMAGE_NAME.findall(html):
            self.entity.delete_asset(image)

        super().delete()

    @property
    def updated(self):
        return self._updated

    # @testable false
    # @covered-by lagniappe/core/properties/common_assets.py::Document.save
    # @reason HTML fingerprint and updated-state checks are owned by document save behavior
    def save(self, content):
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
    def cache_value(self):
        return utility.strip_tags(self.get()).strip()


# @testable infrastructure
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.asset
# @covered-by lagniappe/core/properties/file_assets.py::TextAsset.markup
class TextAsset(Asset):
    _type = "text"

    @property
    def content_type(self):
        return self._content_type or "text/plain"

    @content_type.setter
    def content_type(self, value):
        if value and not self._content_type:
            self._content_type = value

    @property
    def extension(self):
        return (
            "txt"
            if self.content_type == "text/plain"
            else self.content_type.split("/")[-1]
        )

    @property
    def cache_value(self):
        return self.get().strip()


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_assets.py::Document.save
class YDocAsset(Asset):
    _content_type = "text/plain"
    _type = "ydoc"

    @property
    def extension(self):
        return "ydoc"


# @testable infrastructure
# @covered-by lagniappe/core/properties/file_assets.py::Results.save
class JSONAsset(Asset):
    _content_type = "application/json"
    _type = "json"

    def get(self):
        return json.loads(super().get())

    def save(self, content):
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
