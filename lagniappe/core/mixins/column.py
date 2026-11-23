from typing import Literal

from .field_host import FieldHost

from ..definitions import Ordering


# @testable false
# @covered-by lagniappe/core/mixins/column.py::ColumnMixin
# @reason helper keeps generic column editability from touching entity descriptors
def _entity_is_completed(entity: object) -> bool:
    return (
        getattr(entity, "entity_kind", None) == "task"
        and bool(getattr(entity, "db", {}).get("completed"))
    )


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Name.column_value
# @covered-by lagniappe/core/properties/user_entity.py::Email
# @covered-by lagniappe/core/properties/task_dates.py::Completed.column_value
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

    # @testable true
    # @tests tests_unit/test_008_page_properties.py::test_column_editable_does_not_load_page_tasks
    # @matrix page : table-editability task-load
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

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_column_and_filter_contract_errors_are_explicit
    # @matrix property : column validation
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
