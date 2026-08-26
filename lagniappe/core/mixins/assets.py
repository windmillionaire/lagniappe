"""Asset storage and retrieval for entities (images, documents, files)."""

import json

from ..definitions import AssetTypes
from lagniappe.core.tools.database import assets as database_assets


# @testable infrastructure
# @covered-by lagniappe/core/mixins/assets.py::AssetMixin.get_asset
# @covered-by lagniappe/core/mixins/assets.py::AssetMixin.save_asset
class AssetRegistry:
    def __init__(self):
        self._types = AssetTypes

    def get(self, name, entity):
        definition = entity.assets.get(name)
        if not definition:
            return None
        asset_type = self._types[definition.get("type", "").upper()]
        if not asset_type.value:
            return None

        return asset_type.value(definition, name=name, entity=entity)

    def create(self, type, name, entity):
        asset_type = self._types[type.upper()]
        if not asset_type:
            return None
        return asset_type.value(name=name, entity=entity)


Assets = AssetRegistry()


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_assets.py::Document.add_image
# @covered-by lagniappe/core/properties/common_assets.py::Document.save
class AssetMixin:
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

    _assets = None

    @property
    def assets(self):
        if self._assets is None:
            self._assets = json.loads(self.db.get("assets", "{}"))

        return self._assets

    # @testable false
    # @covered-by lagniappe/core/properties/common_assets.py::Document.add_image
    # @covered-by lagniappe/core/properties/common_assets.py::Document.save
    # @reason production asset lookup mechanics are exercised through E2E asset-backed property flows
    def get_asset(self, name):
        name = name.split(".")[0] if isinstance(name, str) else name
        asset = Assets.get(name, self)
        if not asset:
            return None
        return asset

    # @testable false
    # @covered-by lagniappe/core/properties/common_assets.py::Document.save
    # @reason asset deletion is owned by property save/delete contracts
    def delete_asset(self, name):
        asset = self.get_asset(name)
        if not asset:
            return

        asset.delete()

        self._assets.pop(name)
        self.db["assets"] = json.dumps(self._assets)

    # @testable false
    # @covered-by lagniappe/core/properties/common_assets.py::Document.add_image
    # @covered-by lagniappe/core/properties/common_assets.py::Document.save
    # @reason asset persistence plumbing is owned by the asset-backed property contracts
    def save_asset(self, content, name, type, visibility="private"):
        asset = self.get_asset(name)
        if not content:
            self.delete_asset(name)
            return None
        elif content and not asset:
            asset = Assets.create(type, name, self)
            asset.visibility = visibility
            asset.content_type = getattr(
                content, "lagniappe_content_type", None
            ) or getattr(content, "content_type", None)

        saved = asset.save(content)
        if not saved:
            return None

        self.assets[name] = asset.definition

        self.db["assets"] = json.dumps(self.assets)
        return asset

    # @testable true
    # @tests tests_unit/test_013e_task_complete_lifecycle.py::test_asset_mixin_copy_asset_copies_storage_and_updates_definition
    # @matrix asset-storage : copy metadata visibility
    def copy_asset(self, asset, name=None):
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

        blob = database_assets.copy_file(
            source_path,
            source_visibility,
            copied.path,
            copied.visibility.value,
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
