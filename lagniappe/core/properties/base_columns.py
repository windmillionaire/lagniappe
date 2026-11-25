from collections.abc import Mapping
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.site import Site

from ..mixins import ColumnMixin
from .base_property import Property, build_field


class Columns[Owner: Entity | Site = "Entity"](Property["Columns", Owner, "Columns | None"]):
    """Table column configuration for an entity's list view.

    Builds a dict of ColumnMixin fields from ``column_fields`` and
    generates column metadata (title, icon, ordering, etc.) for the
    frontend table renderer.

    Get:
        fields (dict): {field_id: ColumnMixin field instance}.
        columns (list[dict]): Column metadata dicts for the UI.
        selected (list[str]): IDs of columns currently selected for display.
    """

    _id = "table"
    _embedded = False
    column_fields: list[type[ColumnMixin]]
    _fields: dict[str, ColumnMixin] | None
    _columns: list[dict[str, object]] | None

    def __init__(self, *args: object, entity: Owner | None = None, **kwargs: object) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self._fields = None
        self._columns = None

    @property
    def value(self) -> Self:  # pyright: ignore[reportIncompatibleMethodOverride] -- The table is a read-only computed field.
        return self

    @property
    def embedded(self) -> bool:
        return self._embedded

    @embedded.setter
    def embedded(self, value: bool) -> None:
        self._embedded = value

    @property
    def fields(self) -> dict[str, ColumnMixin]:
        if cached := getattr(self, "_fields", None):
            return cached

        fields = {}
        for f in self.column_fields:
            field = build_field(f, self.entity)
            fields[field.id] = field

        if not all(isinstance(f, ColumnMixin) for f in fields.values()):
            raise TypeError("All fields must inherit from ColumnMixin")

        self._fields = fields
        return fields

    def update_fields(self, fields: Mapping[str, object]) -> None:
        new_fields = {
            f_id: f
            for f_id, f in fields.items()
            if f_id not in self.fields and isinstance(f, ColumnMixin)
        }
        for field in new_fields.values():
            field.selected = False
        self.fields.update(new_fields)
        self._columns = None

    @property
    def selected(self) -> list[str]:
        return [f.id for f in self.fields.values() if f.selected]

    @property
    def columns(self) -> list[dict[str, object]]:
        if cached := getattr(self, "_columns", None):
            return cached

        self._columns = [
            {
                "field": f.id,
                "title": f.label,
                "icon": f.icon,
                "ordering": ordering.value if (ordering := getattr(f, "ordering", None)) else None,
                "selected": getattr(f, "selected", False),
                "link": getattr(f, "link", True),
                "parent": getattr(f, "parent", True),
                "schema": f.schema if f.editable else None,
            }
            for f in self.fields.values()
        ]
        return self._columns

    @property
    def preload(self) -> dict[str, object]:
        return {"columns": self.columns, "selected": self.selected}
