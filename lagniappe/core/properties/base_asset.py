from .base_property import Property, UNSET


# @testable infrastructure
class AssetProperty(Property):
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
    def asset_type(self):
        return getattr(self, "_asset_type", None)

    @asset_type.setter
    def asset_type(self, value):
        self._asset_type = value

    @property
    def asset(self):
        if getattr(self, "_asset", UNSET) is not UNSET:
            return self._asset
        elif not self.value:
            self._asset = None
        else:
            self._asset = self.value.get()

        return self._asset

    @property
    def value(self):
        if self.is_set:
            return self._value

        self._value = self.entity.get_asset(self.id)
        return self._value

    @value.setter
    def value(self, value):
        self._asset = UNSET

        if value:
            self._value = self.entity.save_asset(value, self.id, self.asset_type)
        else:
            self.entity.delete_asset(self.id)
            self._value = None
