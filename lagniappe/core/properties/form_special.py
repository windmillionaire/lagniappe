from typing import TYPE_CHECKING, cast

from ..definitions import FieldType, FilterOptions, Ordering
from ..definitions.asset import HTMLAsset, ImageAsset
from ..definitions.identifiers import short_uuid
from ..mixins import AIMixin, ColumnMixin, FilterMixin
from .base_asset import AssetProperty
from .base_property import UNSET
from .base_schema import SchemaProperty

if TYPE_CHECKING:
    from ..definitions.asset import AssetUpload
    # Specialized generic bases below defer the circular owner import.
    from ..entities.entity import Entity as Entity
    from ..mixins.assets import AssetMixin
    from .base_schema import FieldDefinition
    from .form_submission import FormSubmission


class Signature(AssetProperty["Entity", ImageAsset, object], FilterMixin, AIMixin, ColumnMixin, SchemaProperty[ImageAsset, object]):
    """Signature image field. Stored as an image asset.

    Set:
        value (file): Signature image from form upload.

    Get:
        value (str): Asset path.
        asset: Signature image URL.
        filter_value (bool): Whether a signature exists.
        ai_value (bool): Same as filter_value.
    """

    _icon = "signature"

    # Property Attributes
    _asset_type = "image"

    def validate_submission(self, value: object) -> None:
        if not value:
            self.value = None
        elif isinstance(value, str):
            if value in (self.id, self.form_value):
                return
        else:
            self.value = value

    @property
    def db_value(self) -> str | None:
        return self.id if self.value else None

    @db_value.setter
    def db_value(self, value: object) -> None:
        self._asset = UNSET
        self.unset()

    @property
    def form_value(self) -> str | bytes | None:
        asset = self.value
        if not asset:
            return None

        return getattr(asset, "url", None) or cast(bytes | None, self.asset)

    # Column Attributes
    _ordering = Ordering.EXISTS

    @property
    def column_value(self) -> str | bytes | None:
        return self.form_value

    @property
    def sort_value(self) -> bool:
        return bool(self.value)

    # AI Attributes
    @property
    def ai_value(self) -> bool:
        return self.filter_value

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.SIGNATURE.value

    @property
    def filter_value(self) -> bool:
        return bool(self.value)


class HTML(AssetProperty["Entity", HTMLAsset, str | None], SchemaProperty[HTMLAsset, str | None]):
    """Rich HTML content field. Stored as an HTML text asset.

    The setter returns whether the content actually changed (by
    comparing asset fingerprints).

    Set:
        value (str): HTML string content.

    Get:
        value (str): Asset path.
        asset: HTML content string.
    """

    # Property Attributes
    _asset_type = "html"

    @property
    def value(self) -> HTMLAsset | None:
        return super().value

    @value.setter
    def value(self, value: str | None) -> bool | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- direct descriptor callers receive the asset change flag.
        if not value:
            return None

        self._store_asset_value(value)
        return cast(HTMLAsset, super().value).updated

    def validate_submission(self, value: object) -> None:
        self.unset()

    def validate_import(self, value: object) -> None:
        self.unset()

    def validate_ai(self, value: object) -> None:
        self.unset()

    @property
    def db_value(self) -> None:
        return None

    @db_value.setter
    def db_value(self, value: object) -> None:
        self.unset()

    @property
    def form_value(self) -> None:
        return None

    # Column Attributes
    _ordering = None

    @property
    def sort_value(self) -> bool:
        return bool(cast("AssetMixin", self.entity).assets.get(self.id))

    # Asset Attributes
    def add_image(self, image: AssetUpload, visibility: str = "private") -> str | None:
        name = f"image_{self.id}_{short_uuid()}"
        asset = cast("AssetMixin", self.entity).save_asset(image, name, "image", visibility=visibility)
        return asset.url if asset else None


class Status(AIMixin, ColumnMixin, SchemaProperty):
    """Computed status field derived from other form field values.

    Evaluates status_conditions against the entity's submission to
    determine which statuses are active. Not directly persisted --
    value is computed from the submission's current field state.

    Get:
        value (list[str]): Active status display labels.
        column_value (list[str]): Active status display labels.
        ai_value (list[str]): Active status display labels.
    """

    _icon = "status"

    # Property Attributes
    @property
    def status_conditions(self) -> list[FieldDefinition]:
        """Return the status conditions from the schema."""
        return cast("list[FieldDefinition]", self.get("status", []))

    @property
    def active_statuses(self) -> list[FieldDefinition]:
        submission = cast("FormSubmission | None", self.entity.properties.get("submission"))
        if not submission:
            return []

        return [
            status_element
            for status_element in self.status_conditions
            if submission.condition_matches(status_element)
        ]

    @property
    def value(self) -> list[str]:
        return self.ai_value

    @value.setter
    def value(self, value: object) -> None:
        self._value = None

    def validate_submission(self, value: object) -> None:
        self.value = None

    @property
    def db_value(self) -> None:
        return None

    @db_value.setter
    def db_value(self, value: object) -> None:
        self.value = None

    @property
    def form_value(self) -> None:
        return None

    # Column Attributes
    _ordering = Ordering.EXISTS

    @property
    def column_value(self) -> list[str]:
        return self.value

    @property
    def sort_value(self) -> bool:
        return bool(self.value)

    # AI Attributes
    @property
    def ai_value(self) -> list[str]:
        return [cast(str, status_element["text"]) for status_element in self.active_statuses]
