from typing import Literal

from .field_host import FieldHost

from ..definitions import Ordering


def _entity_is_completed(entity: object) -> bool:
    return (
        getattr(entity, "entity_kind", None) == "task"
        and bool(getattr(entity, "db", {}).get("completed"))
    )


class ColumnMixin(FieldHost):
    """Adds table column display. Used by Columns to build table metadata.

    Provides:
        column_value: Value to display in the column (default: self.value).
        sort_value: Value used for sorting (default: column_value).
        field (str): Field identifier (default: self.id).
        selected (bool): Whether the column is shown by default.
        editable (bool): Whether values can be edited inline.

    Override:
        _ordering (Ordering | None): Sort strategy (LEXICAL, NUMERIC, etc.).
        _selected (bool): Default visibility (default: False).
        _editable (bool): Inline editing (default: False).
    """

    _ordering: Ordering | Literal[False] | None = None
    _selected = False
    _editable = False

    @property
    def field(self) -> str:
        return self.id

    @property
    def column_id(self) -> str:
        return self.id

    @property
    def column_value(self) -> object:
        val = self.value
        return None if val is None else val

    @property
    def sort_value(self) -> object:
        return self.column_value

    @property
    def selected(self) -> bool:
        return getattr(self, "_selected", False)

    @selected.setter
    def selected(self, value: bool) -> None:
        self._selected = value

    @property
    def editable(self) -> bool:
        return (
            getattr(self, "_editable", False)
            and not getattr(self.entity, "readonly", False)
            and not _entity_is_completed(self.entity)
        )

    @editable.setter
    def editable(self, value: bool) -> None:
        self._editable = value

    @property
    def ordering(self) -> Ordering | Literal[False]:
        ordering = getattr(self, "_ordering", False)
        if ordering is not False and not isinstance(ordering, Ordering):
            raise TypeError(
                f"Column {self.__class__.__name__} ordering must be False or an Ordering enum"
            )
        return ordering

    @ordering.setter
    def ordering(self, value: Ordering) -> None:
        if not isinstance(value, Ordering):
            raise TypeError("Ordering must be an Ordering enum")
        self._ordering = value
