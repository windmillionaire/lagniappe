from ..definitions import FieldType, FilterOptions, Ordering

from ..mixins import ColumnMixin, FilterMixin
from .base_asset import AssetProperty
from .base_property import UNSET


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_image_asset_lifecycle_and_projections
# @features page
# @dimensions image asset-lifecycle column filter-value
class Image(ColumnMixin, FilterMixin, AssetProperty):
    """Entity image. Stored as an image asset.

    Set:
        value (file): Image file to upload.

    Get:
        value (str): Asset path.
        column_value (str | None): Image URL for table display.
        filter_value (bool): Whether an image exists.
    """

    # Property Attributes
    _id = "image"
    _icon = "image"
    _kind = "page"
    _asset_type = "image"
    _label = "Image"

    # Entity Attributes
    def delete(self):
        self.entity.delete_asset(self.id)
        self.unset()
        self._asset = UNSET

    # Column Attributes
    _ordering = Ordering.EXISTS
    _selected = False
    _editable = False

    @property
    def sort_value(self):
        return self.filter_value

    @property
    def column_value(self):
        return self.value.url if self.value else None

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.IMAGE.value
    _field_text = "has"
    _filter_key = "has_image"

    @property
    def filter_value(self):
        return True if self.value else False

    @property
    def filter_label(self):
        return "Has Image"
