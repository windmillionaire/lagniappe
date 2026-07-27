"""Date mixin for datetime property handling with timezone conversion."""

from datetime import datetime, timezone
import re

from ..definitions import FieldType, FilterOptions, Ordering
from ..tools import dates

OLD_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


# @testable infrastructure
# @covered-by lagniappe/core/properties/common_entity.py::Modified
# @covered-by lagniappe/core/properties/user_entity.py::LastLogin
# @covered-by lagniappe/core/properties/form_inputs.py::DateInput
# @covered-by lagniappe/core/properties/task_dates.py::DueDate.value
class DateMixin:
    """Adds UTC datetime storage with timezone conversion.

    All values are stored in UTC. The setter accepts datetimes (with or
    without tzinfo), ISO strings, and timestamps -- naive datetimes and
    date strings are assumed to be in the user's timezone.

    Provides:
        value (datetime): UTC datetime (setter converts to UTC).
        column_value (datetime): User-timezone datetime for display.
        sort_value (float): Unix timestamp for ordering.
        filter_value (float): Unix timestamp for filtering.
        ai_value (str): User-timezone date string for AI context.
        db_value (str): UTC ISO string for database storage.
        form_value (str): User-timezone date (YYYY-MM-DD) for form inputs.
    """

    # Property Attributes
    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        try:
            utc_value = self.set_utc_datetime(value)
        except Exception as e:
            raise ValueError(f"Invalid date value '{value}': {e}")

        super(DateMixin, type(self)).value.fset(self, utc_value)

    def set_utc_datetime(self, value):
        if isinstance(value, list):
            return [self.set_utc_datetime(v) for v in value]
        elif not value:
            return None

        if isinstance(value, str):
            if OLD_FORMAT.match(value):
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(value)
            if not dt.tzinfo:
                return dates.user_date_string_to_utc_datetime(value)
            return dt.astimezone(timezone.utc)
        elif isinstance(value, datetime):
            if not value.tzinfo:
                value = value.replace(tzinfo=dates.user_timezone())
            return value.astimezone(timezone.utc)
        elif isinstance(value, float):
            return datetime.fromtimestamp(value, timezone.utc)

        return None

    # Column Attributes
    _ordering = Ordering.NUMERIC

    @property
    def column_value(self):
        value = super().value
        if not value:
            return None
        return dates.utc_datetime_to_user_datetime(value)

    @property
    def sort_value(self):
        return self.filter_value

    # AI Attributes
    @property
    def ai_value(self):
        return (
            dates.utc_datetime_to_user_date_string(self.value) if self.value else None
        )

    # Filter Attributes
    _field_type = FieldType.TIMESTAMP
    _field_options = FilterOptions.DATE.value

    @property
    def filter_value(self):
        value = super().value
        if not value:
            return None
        return value.timestamp()

    def filter_details(self, condition):
        details = super().filter_details(condition)
        if isinstance(condition.value, list):
            details["value"] = [
                datetime.fromtimestamp(v, dates.user_timezone())
                for v in condition.value
            ]
        else:
            details["value"] = datetime.fromtimestamp(
                condition.value, dates.user_timezone()
            )
        return details

    # Submission Attributes
    @property
    def db_value(self):
        return self.value.isoformat() if self.value else None

    @db_value.setter
    def db_value(self, value):
        self.value = value

    @property
    def form_value(self):
        return (
            self.value.astimezone(dates.user_timezone()).date().isoformat()
            if self.value
            else None
        )
