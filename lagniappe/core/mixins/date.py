"""Date mixin for datetime property handling with timezone conversion."""

from datetime import datetime, time, UTC
import re
from typing import TYPE_CHECKING, cast, overload

from .field_host import FieldHost

from ..definitions import Comparator, FieldType, FilterOptions, Ordering
from ..tools import dates

if TYPE_CHECKING:
    from ..entities.condition import Condition

    class _DateHost(FieldHost):
        @property
        def value(self) -> datetime | None: ...
        @value.setter
        def value(self, value: object) -> None: ...
        def filter_details(self, condition: Condition) -> dict[str, object]: ...
else:
    _DateHost = object

type UTCDate = datetime | None | list[UTCDate]


OLD_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


class DateMixin(_DateHost):
    """Adds UTC datetime storage with timezone conversion.

    All values are stored in UTC. The setter accepts datetimes (with or
    without tzinfo), ISO strings, and timestamps -- naive datetimes and
    date strings use the property's acting user (or request context) timezone.

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
    def value(self) -> datetime | None:
        return super().value

    @value.setter
    def value(self, value: object) -> None:
        self._set_date_value(value)

    def _set_date_value(self, value: object) -> None:
        try:
            utc_value = self.set_utc_datetime(value)
        except Exception as e:
            raise ValueError(f"Invalid date value '{value}': {e}") from e

        # A schema field and a database field use different storage descriptors.
        # Locate the next value descriptor on the concrete field's existing MRO.
        descriptor = cast(property, getattr(super(DateMixin, type(self)), "value"))  # noqa: B009
        setter = descriptor.fset
        if setter is None:
            raise TypeError("Date storage requires a writable value descriptor")
        setter(self, utc_value)

    @overload
    def set_utc_datetime(self, value: datetime | str | float | None) -> datetime | None: ...
    @overload
    def set_utc_datetime(self, value: list[object]) -> list[UTCDate]: ...
    @overload
    def set_utc_datetime(self, value: object) -> UTCDate: ...
    def set_utc_datetime(self, value: object) -> UTCDate:
        if isinstance(value, list):
            return [self.set_utc_datetime(v) for v in value]
        elif not value:
            return None

        if isinstance(value, str):
            if OLD_FORMAT.match(value):
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = datetime.fromisoformat(value)
            if not dt.tzinfo:
                return dates.user_date_string_to_utc_datetime(value, user=self.user)
            return dt.astimezone(UTC)
        elif isinstance(value, datetime):
            if not value.tzinfo:
                value = value.replace(tzinfo=dates.user_timezone(self.user))
            return value.astimezone(UTC)
        elif isinstance(value, float):
            return datetime.fromtimestamp(value, UTC)

        return None

    # Column Attributes
    _ordering = Ordering.DATE

    @property
    def column_value(self) -> datetime | None:
        value = super().value
        if not value:
            return None
        return dates.utc_datetime_to_user_datetime(value, user=self.user)

    @property
    def sort_value(self) -> float | None:
        return self.filter_value

    # AI Attributes
    @property
    def ai_value(self) -> str | None:
        return (
            dates.utc_datetime_to_user_date_string(self.value, user=self.user) if self.value else None
        )

    # Filter Attributes
    _field_type = FieldType.TIMESTAMP
    _field_options = FilterOptions.DATE.value

    @property
    def filter_value(self) -> float | None:
        value = super().value
        if not value:
            return None
        return value.timestamp()

    def filter_details(self, condition: Condition) -> dict[str, object]:
        details = super().filter_details(condition)
        tz = dates.user_timezone(self.user)
        if isinstance(condition.value, list):
            dt_values = [datetime.fromtimestamp(v, tz) for v in condition.value]
            if (
                condition.comparator == Comparator.BETWEEN
                and len(dt_values) == 2
                and dt_values[0].date() == dt_values[1].date()
                and dt_values[0].time() == time.min
                and dt_values[1].hour == 23
                and dt_values[1].minute == 59
                and dt_values[1].second == 59
            ):
                details["text"] = FilterOptions.DATE.value.EQUALS.value
                details["status"] = Comparator.EQUALS.name
                details["value"] = dt_values[0]
            else:
                details["value"] = dt_values
        else:
            details["value"] = datetime.fromtimestamp(
                cast(float, condition.value), tz
            )
        return details

    # Submission Attributes
    @property
    def db_value(self) -> str | None:
        return self.value.isoformat() if self.value else None

    @db_value.setter
    def db_value(self, value: object) -> None:
        self.value = value

    @property
    def form_value(self) -> str | None:
        return (
            self.value.astimezone(dates.user_timezone(self.user)).date().isoformat()
            if self.value
            else None
        )
