from datetime import datetime
from typing import TYPE_CHECKING

from ..definitions import FieldType, FilterOptions, Ordering
from ..mixins import AIMixin, ColumnMixin, DateMixin, DetailsMixin, FilterMixin
from ..tools import dates
from .base_db import DBProperty

if TYPE_CHECKING:
    from ..entities.condition import Condition
    from ..entities.task import Task
    from ..entities.history import TaskHistory

type TaskRecord = Task | TaskHistory



class Completed(ColumnMixin, DetailsMixin, FilterMixin, AIMixin, DBProperty[bool, TaskRecord, bool]):
    """Task completion status. Stored and exposed as a boolean.

    Set:
        value (bool): Whether the task is completed.

    Get:
        value (bool): True if completed, False otherwise.
        filter_value (bool): Same as value.
        column_value (bool): Same as value.
    """

    # Property Attributes
    _id = "completed"
    _kind: str | None = "task"
    _label = "Completed"
    _icon = "completed"

    @property
    def value(self) -> bool:
        return self._read_db_value() is True

    @value.setter
    def value(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("completed must be a boolean")

        self._write_db_value(value)

    @property
    def details_value(self) -> bool:
        return self.value

    # Column Attributes
    _ordering = Ordering.BOOLEAN
    _editable = True

    @property
    def column_value(self) -> bool:
        return self.filter_value

    @property
    def sort_value(self) -> bool:
        return self.filter_value

    # Filter Attributes
    _field_options = FilterOptions.COMPLETED.value
    _field_text = "is"
    _default = "IS_FALSE"
    _field_type = FieldType.BOOLEAN

    @property
    def filter_value(self) -> bool:
        return self.value

    def filter_details(self, condition: Condition) -> dict[str, object]:
        return FilterMixin.filter_details(self, condition)

    @property
    def ai_value(self) -> bool:
        return self.filter_value

    @property
    def schema(self) -> dict[str, object]:
        return {"type": "checkbox"}

    @property
    def editable(self) -> bool:  # pyright: ignore[reportIncompatibleMethodOverride] -- Completion editability is computed from its owner.
        return not getattr(self.entity, "readonly", False)

    @property
    def form_value(self) -> bool:
        return self.filter_value


class CompletedOn(DateMixin, AIMixin, ColumnMixin, DBProperty[datetime, TaskRecord]):
    """Task completion date. Stored as a UTC datetime, exposed as date.

    Set:
        value (datetime): Completion date (UTC) From DateMixin.

    Get:
        value (datetime | None): Completion date (UTC) From DateMixin.
        column_value (datetime): User-timezone datetime (via DateMixin).
        sort_value (float): Timestamp for ordering.
    """

    # Property Attributes
    _id = "completed_on"
    _kind: str | None = "task"
    _label = "Completed On"
    _icon = "completed"

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _editable = False

    @property
    def value(self) -> datetime | None:
        return super().value

    @value.setter
    def value(self, value: object) -> None:
        if isinstance(value, (datetime, type(None))):
            self._set_date_value(value)

    @property
    def column_value(self) -> datetime | None:
        return dates.utc_datetime_to_user_datetime(self.value) if self.value else None


class DueDate(DateMixin, AIMixin, ColumnMixin, FilterMixin, DBProperty[datetime, TaskRecord]):
    """Task due date. Stored as UTC, displayed in user timezone.

    Set:
        value (datetime): Due date (converted to UTC via DateMixin).

    Get:
        value (datetime): UTC datetime.
        column_value (datetime): User-timezone datetime (via DateMixin).
        sort_value (float): Timestamp for ordering.
    """

    # Property Attributes
    _id = "due_date"
    _kind: str | None = "task"
    _label = "Due Date"
    _icon = "dueDate"

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _editable = True

    @property
    def schema(self) -> dict[str, object]:
        return {"type": "input", "input": "date"}

    # Filter Attributes
    _field_options = FilterOptions.DATE.value
    _field_type = FieldType.TIMESTAMP

    @property
    def value(self) -> datetime | None:
        return super().value

    @value.setter
    def value(self, value: object) -> None:
        if value:
            self._set_date_value(value)
        else:
            self.entity.db["due_date"] = None
            self._value = None
