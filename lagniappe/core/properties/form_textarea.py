from typing import cast

from ..definitions import FieldType, FilterOptions, Ordering
from ..exceptions import ValidationError
from ..mixins import AIMixin, ColumnMixin, FilterMixin, SearchMixin
from .base_schema import SchemaProperty


class Textarea(ColumnMixin, AIMixin, FilterMixin, SearchMixin, SchemaProperty[str]):
    """Multi-line text field.

    Sorted by existence (has content or not) rather than lexically.

    Set:
        value (str): Text content.

    Get:
        value (str): Text content.
        sort_value (bool): Whether any content exists.
    """

    _icon = "textarea"

    # Column Attributes
    _ordering = Ordering.EXISTS

    @property
    def sort_value(self) -> bool:
        return bool(self.value)

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        try:
            self.value = cast(str, value) if value else None
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError):
            self.errors.append(
                f"Invalid textarea value '{value}' in column '({self.label})'"
            )

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value

    # AI Attributes
    @property
    def ai_value(self) -> str | None:
        return self.value or None

    @property
    def search_value(self) -> object:
        if self.id == "description":
            return None
        return super().search_value
