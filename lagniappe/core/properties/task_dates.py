from datetime import datetime

from ..definitions import FieldType, FilterOptions, Ordering
from ..mixins import AIMixin, ColumnMixin, DateMixin, DetailsMixin, FilterMixin
from ..tools import dates
from .base_db import DBProperty


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_completed
# @features task
# @dimensions completed details
class Completed(ColumnMixin, DetailsMixin, FilterMixin, AIMixin, DBProperty):
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
    _kind = "task"
    _label = "Completed"
    _icon = "completed"

    @property
    def value(self):
        return DBProperty.value.fget(self) is True

    @value.setter
    def value(self, value):
        if not isinstance(value, bool):
            raise TypeError("completed must be a boolean")

        DBProperty.value.fset(self, value)

    @property
    def details_value(self):
        return self.value

    # Column Attributes
    _ordering = Ordering.BOOLEAN
    _editable = True

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_completed
    # @features task
    # @dimensions column
    @property
    def column_value(self):
        return self.filter_value

    @property
    def sort_value(self):
        return self.filter_value

    # Filter Attributes
    _field_options = FilterOptions.COMPLETED.value
    _field_text = "is"
    _default = "IS_FALSE"
    _field_type = FieldType.BOOLEAN

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_completed
    # @features task
    # @dimensions details filter-value
    @property
    def filter_value(self):
        return self.value

    def filter_details(self, condition):
        return FilterMixin.filter_details(self, condition)

    @property
    def ai_value(self):
        return self.filter_value

    @property
    def schema(self):
        return {"type": "checkbox"}

    @property
    def editable(self):
        return not getattr(self.entity, "readonly", False)

    @property
    def form_value(self):
        return self.filter_value


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_completed_on_stores_timestamp
# @features task
# @dimensions completed-on
class CompletedOn(DateMixin, AIMixin, ColumnMixin, DBProperty):
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
    _kind = "task"
    _label = "Completed On"
    _icon = "completed"

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _editable = False

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if isinstance(value, (datetime, type(None))):
            DateMixin.value.fset(self, value)

    @property
    def column_value(self):
        return dates.utc_datetime_to_user_datetime(self.value) if self.value else None


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_due_date
# @features task
# @dimensions column, ai-value, filter-value
class DueDate(DateMixin, AIMixin, ColumnMixin, FilterMixin, DBProperty):
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
    _kind = "task"
    _label = "Due Date"
    _icon = "dueDate"

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _editable = True

    @property
    def schema(self):
        return {"type": "input", "input": "date"}

    # Filter Attributes
    _field_options = FilterOptions.DATE.value
    _field_type = FieldType.TIMESTAMP

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_due_date
    # @features task
    # @dimensions due-date, date
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if value:
            DateMixin.value.fset(self, value)
        else:
            self.entity.db["due_date"] = None
            self._value = None
