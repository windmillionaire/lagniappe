from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..mixins.assets import AssetMixin
    from ..definitions.asset import Asset, AssetContent

from .base_property import Property, UNSET


# @testable infrastructure
class AssetProperty[Owner: Entity = "Entity", Read = object, Write = object](Property[Read, Owner, Write]):
    """Property backed by a stored asset (image, document, file, etc.).

    Subclasses set ``_asset_type`` (image, html, text, ydoc, file, json).
    Setting value saves the content via entity.save_asset; setting to
    None deletes the existing asset.

    Set:
        value (any): Asset content to save. None deletes the asset.

    Get:
        value (str | None): Asset path in storage.
        asset: The resolved asset object (loaded via entity.get_asset).
    """

    @property
    def asset_type(self) -> str | None:
        return cast("str | None", getattr(self, "_asset_type", None))

    @asset_type.setter
    def asset_type(self, value: str | None) -> None:
        self._asset_type = value

    @property
    def asset(self) -> object:
        if getattr(self, "_asset", UNSET) is not UNSET:
            return self._asset
        elif not self.value:
            self._asset = None
        else:
            self._asset = cast("Asset", self.value).get()

        return self._asset

    @property
    def value(self) -> Read | None:
        return cast("Read | None", self._stored_asset())

    def _stored_asset(self) -> Asset | None:
        if self.is_set:
            return cast("Asset | None", self._value)

        self._value = cast("AssetMixin", self.entity).get_asset(self.id)
        return cast("Asset | None", self._value)

    @value.setter
    def value(self, value: Write) -> None:
        self._store_asset_value(value)

    def _store_asset_value(self, value: object) -> None:
        self._asset = UNSET

        if value:
            asset_type = self.asset_type
            if asset_type is None:
                raise ValueError("An asset property must declare its storage type.")
            # Each concrete setter supplies the content allowed by its registered asset type.
            self._value = cast("AssetMixin", self.entity).save_asset(
                cast("AssetContent", value), self.id, asset_type
            )
        else:
            cast("AssetMixin", self.entity).delete_asset(self.id)
            self._value = None
