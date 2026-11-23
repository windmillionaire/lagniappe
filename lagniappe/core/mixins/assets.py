"""Asset storage and retrieval for entities (images, documents, files)."""

import json
import hashlib
from uuid import uuid4
from typing import TYPE_CHECKING, Literal, Protocol, cast, overload

from ..definitions import AssetTypes
from ..definitions.asset import (
    Asset, AssetContent, AssetDefinition, AssetOwner, AssetUpload, FileAsset, HTMLAsset,
    ImageAsset, JSONAsset, JSONValue, StoredAsset, TextAsset, YDocAsset,
)

if TYPE_CHECKING:
    from google.cloud.datastore import Entity as DatastoreEntity, Key
from lagniappe.core.tools.database import assets as database_assets


class _AssetEntity(AssetOwner, Protocol):
    @property
    def assets(self) -> dict[str, AssetDefinition]: ...


if TYPE_CHECKING:
    class _AssetHost:
        @property
        def hash(self) -> str: ...

        @property
        def key(self) -> Key | None: ...

        @property
        def db(self) -> DatastoreEntity | dict[str, object]: ...
else:
    _AssetHost = object


class AssetRegistry:
    def __init__(self) -> None:
        self._types = AssetTypes

    def get(self, name: str, entity: _AssetEntity) -> StoredAsset | None:
        definition = entity.assets.get(name)
        if not definition:
            return None
        tag = definition.get("type", "")
        if tag is None:
            raise AttributeError("Asset type is missing")
        asset_type = self._types[tag.upper()]
        if not asset_type.value:
            return None

        return asset_type.value(definition, name=name, entity=entity)

    def create(self, type: str, name: str, entity: _AssetEntity) -> StoredAsset:
        asset_type = self._types[type.upper()]
        if not asset_type.value:
            raise TypeError(f"Unknown asset type: {type!r}")
        return asset_type.value(name=name, entity=entity)


Assets = AssetRegistry()


class AssetMixin(_AssetHost):
    """Adds cloud-stored asset management to an entity.

    Assets are tracked in entity.db["assets"] as a JSON dict mapping
    asset names to definition dicts ({type, visibility, path, fingerprint}).
    Supports types: image, html, text, ydoc, file, json.
    Supports visibility: private (signed URLs) and public (direct URLs).

    Provides:
        assets (dict): {name: asset_definition} loaded from entity.db.
        get_asset(name): Retrieve asset content (URL, text, parsed JSON, etc.).
        save_asset(content, name, type): Save content and update the assets dict.
        copy_asset(asset, name=None): Copy an existing asset into this entity.
        delete_asset(name): Remove an asset from storage and the assets dict.
    """

    _assets: dict[str, AssetDefinition] | None = None

    @property
    def assets(self) -> dict[str, AssetDefinition]:
        if self._assets is None:
            raw = cast(str, self.db.get("assets", "{}"))
            self._assets = cast("dict[str, AssetDefinition]", json.loads(raw))

        return self._assets

    def get_asset(self, name: str) -> StoredAsset | None:
        name = name.split(".")[0] if isinstance(name, str) else name
        asset = Assets.get(name, self)
        if not asset:
            return None
        return asset

    def delete_asset(self, name: str) -> None:
        asset = self.get_asset(name)
        if not asset:
            return

        asset.delete()

        self.assets.pop(name)
        self.db["assets"] = json.dumps(self._assets)

    @overload
    def save_asset(self, content: str | None, name: str, type: Literal["html"],
                   visibility: str = "private", *, isolated: bool = False) -> HTMLAsset | None: ...

    @overload
    def save_asset(self, content: str | None, name: str, type: Literal["ydoc"],
                   visibility: str = "private", *, isolated: bool = False) -> YDocAsset | None: ...

    @overload
    def save_asset(self, content: str | None, name: str, type: Literal["text"],
                   visibility: str = "private", *, isolated: bool = False) -> TextAsset | None: ...

    @overload
    def save_asset(self, content: JSONValue | None, name: str, type: Literal["json"],
                   visibility: str = "private", *, isolated: bool = False) -> JSONAsset | None: ...

    @overload
    def save_asset(self, content: AssetUpload | None, name: str, type: Literal["image"],
                   visibility: str = "private", *, isolated: bool = False) -> ImageAsset | None: ...

    @overload
    def save_asset(self, content: AssetUpload | None, name: str, type: Literal["file"],
                   visibility: str = "private", *, isolated: bool = False) -> FileAsset | None: ...

    @overload
    def save_asset(self, content: AssetContent, name: str, type: str,
                   visibility: str = "private", *, isolated: bool = False) -> StoredAsset | None: ...

    def save_asset(
        self, content: AssetContent, name: str, type: str, visibility: str = "private",
        *, isolated: bool = False,
    ) -> StoredAsset | None:
        asset = self.get_asset(name)
        if not content:
            self.delete_asset(name)
            return None
        elif not asset:
            asset = Assets.create(type, name, self)
            asset.visibility = visibility
            asset.content_type = getattr(
                content, "lagniappe_content_type", None
            ) or getattr(content, "content_type", None)

        if isolated:
            # A losing checkpoint must never overwrite the winning checkpoint's
            # blob before its guarded Datastore metadata commit.
            if type == "html" and asset.fingerprint == hashlib.md5(cast(str, content).strip().encode()).hexdigest():
                return asset
            asset = Assets.create(type, name, self)
            # Never reuse a retired path: delayed cleanup from an older save
            # must not delete a newer document that happens to have equal text.
            asset._path = f"{self.hash}_{name}_{uuid4().hex}.{asset.extension}"

        if getattr(content, "lagniappe_direct_upload", False):
            asset._path = database_assets.direct_upload_destination_path(
                asset.path,
                content,
            )

        # The runtime registry pairs each storage type with its accepted content.
        writer = cast("Asset[object, AssetContent]", asset)
        saved = writer.save(content)
        if not saved:
            return None

        self.assets[name] = asset.definition

        self.db["assets"] = json.dumps(self.assets)
        return asset

    def copy_asset(self, asset: StoredAsset | None, name: str | None = None, *, isolated: bool = False) -> StoredAsset | None:
        if not asset:
            return None

        name = name or getattr(asset, "name", None)
        source_path = getattr(asset, "path", None)
        asset_type = getattr(asset, "type", None)
        source_visibility = getattr(asset, "visibility", None)
        source_visibility = getattr(source_visibility, "value", source_visibility)
        if not name or not source_path or not asset_type or not source_visibility:
            return None

        copied = Assets.create(asset_type, name, self)
        if not copied:
            return None

        copied.visibility = source_visibility
        copied.content_type = getattr(asset, "content_type", None)
        source_extension = getattr(asset, "extension", None)
        if not copied.extension and source_extension:
            copied._path = f"{self.hash}_{name}.{source_extension}"
        if isolated:
            copied._path = f"{self.hash}_{name}_{uuid4().hex}.{copied.extension}"

        blob = database_assets.copy_file(
            source_path,
            source_visibility,
            copied.path,
            copied.visibility.value,
            **({"source_generation": asset.generation} if getattr(asset, "generation", None) else {}),
        )
        if not blob:
            return None

        copied.fingerprint = getattr(asset, "fingerprint", None)
        source_size = getattr(asset, "size", None)
        if source_size is not None:
            copied.size = source_size
        copied._record_saved_blob(blob)
        self.assets[name] = copied.definition
        self.db["assets"] = json.dumps(self.assets)
        return copied
