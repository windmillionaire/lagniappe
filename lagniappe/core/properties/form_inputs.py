import math
import re
from contextlib import suppress
from datetime import datetime
from typing import cast

import phonenumbers
from dateutil import parser as date_parser

from ..definitions import FieldType, FilterOptions, Ordering
from ..exceptions import ValidationError
from ..mixins import AIMixin, ColumnMixin, DateMixin, FilterMixin, SearchMixin
from .base_schema import SchemaProperty

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


class TextInput(SearchMixin, AIMixin, FilterMixin, ColumnMixin, SchemaProperty[str]):
    """Plain text input field.

    Strips "The " prefix for lexical sorting. On import, list values
    are joined with spaces.

    Set:
        value (str): Text value.

    Get:
        value (str): Text value.
        sort_value (str): Lowercase with "The " stripped.
    """

    # Property Attributes
    _icon = "text"

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        try:
            value_string = (
                " ".join(
                    str(v).strip() for v in value if v is not None and str(v).strip()
                )
                if isinstance(value, list)
                else value
            )
            self.value = cast(str, value_string) if value_string else None
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError):
            self.errors.append(
                f"Invalid text value '{value}' in column '({self.label})'"
            )

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value

    # Column Attributes
    _ordering = Ordering.LEXICAL
    _editable = True

    @property
    def sort_value(self) -> str | None:
        return self.value.replace("The ", "").lower() if self.value else None

    @property
    def search_value(self) -> object:
        if self.id == "name":
            return None
        return super().search_value


class DateInput(DateMixin, AIMixin, FilterMixin, ColumnMixin, SchemaProperty[datetime]):
    """Date input field. Stored as UTC datetime.

    Set:
        value (datetime | str): Parsed to UTC datetime via DateMixin.

    Get:
        value (datetime): UTC datetime.
        column_value (datetime): User-timezone datetime (via DateMixin).
        sort_value (float): Timestamp for ordering.
    """

    _icon = "date"

    # Column Attributes
    _ordering = Ordering.DATE
    _editable = True

    # Form Attributes
    def validate_submission(self, value: object) -> None:
        """Parse form-submitted date string (YYYY-MM-DD format)."""
        try:
            if value in (None, "", []):
                self._value = None
            elif not isinstance(value, str):
                raise ValueError("Date input must be a string")
            else:
                self.value = value  # Keep the existing actor-timezone conversion.
        except (ValueError, TypeError) as error:
            raise ValidationError(
                f"Invalid date for '{self.label}'. Use YYYY-MM-DD."
            ) from error

    # AI Attributes
    def validate_ai(self, value: object) -> None:
        """Parse an AI calendar date in the acting user's timezone; store UTC."""
        if value:
            self.value = date_parser.parse(cast(str, value))
        else:
            self._value = None

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        try:
            self.value = value if not value else date_parser.parse(cast(str, value))
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError, date_parser.ParserError):
            self.errors.append(
                f"Invalid date value '{value}' in column '({self.label})'"
            )

    # Filter Attributes
    _field_type = FieldType.TIMESTAMP
    _field_options = FilterOptions.DATE.value


class TimeInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty[datetime]):
    """Time input field. Stored as a datetime with only the time component.

    Set:
        value (datetime): Parsed from HH:MM format.

    Get:
        value (datetime): Datetime with time component (no timezone).
        db_value (str): HH:MM formatted string.
        ai_value (str): HH:MM formatted string.
        filter_value (float): Timestamp for filtering.
    """

    # Property Attributes
    _icon = "time"

    # Column Attributes
    _ordering = Ordering.TIME
    _editable = True

    # Form Attributes
    def validate_submission(self, value: object) -> None:
        """Parse form-submitted time string (HH:MM format)."""
        try:
            parsed = (
                None if value in (None, "", []) else datetime.strptime(cast(str, value), "%H:%M")
            )
        except (ValueError, TypeError) as error:
            raise ValidationError(
                f"Invalid time for '{self.label}'. Use HH:MM."
            ) from error
        self.value = parsed

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        try:
            self.value = datetime.strptime(cast(str, value), "%H:%M") if value else None
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError):
            self.errors.append(
                f"Invalid time value '{value}' in column '({self.label})'"
            )

    # Filter Attributes
    _field_type = FieldType.TIMESTAMP
    _field_options = FilterOptions.TIME.value

    @property
    def filter_value(self) -> float | None:
        """Convert time to timestamp for filtering."""
        if self.value:
            val = self.value
            # Parse string if needed
            if isinstance(val, str):
                try:
                    val = datetime.strptime(val, "%H:%M")
                except (ValueError, TypeError):
                    return None
            return val.timestamp()
        return None

    # AI Attributes
    def validate_ai(self, value: object) -> None:
        """Parse AI-submitted time string (HH:MM format)."""
        if value:
            self.value = datetime.strptime(cast(str, value), "%H:%M")
        else:
            self._value = None

    @property
    def ai_value(self) -> str | None:
        return self.value.strftime("%H:%M") if self.value else None

    @property
    def db_value(self) -> str | None:
        return self.value.strftime("%H:%M") if self.value else None

    @db_value.setter
    def db_value(self, value: object) -> None:
        self.value = datetime.strptime(cast(str, value), "%H:%M") if value else None


class NumberInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty[float]):
    """Numeric input field. Stored as a float.

    Set:
        value (float | str): Converted to float on set.

    Get:
        value (float): Numeric value.
        sort_value (float): Same as filter_value.
        filter_value (float): float(cast(str | float, value)), or None if invalid.
    """

    # Property Attributes
    _icon = "number"

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _editable = True

    @property
    def sort_value(self) -> float | None:
        return self.filter_value

    # Form Attributes
    def validate_submission(self, value: object) -> None:
        """Parse form-submitted number string to float."""
        try:
            if value in (None, []) or (isinstance(value, str) and not value.strip()):
                parsed = None
            else:
                parsed = float(cast(str | float, value))
                if not math.isfinite(parsed):
                    raise ValueError("Number must be finite")
        except (ValueError, TypeError, OverflowError) as error:
            raise ValidationError(f"Invalid number for '{self.label}'.") from error
        self.value = parsed

    # AI Attributes
    def validate_ai(self, value: object) -> None:
        """Parse AI-submitted number (string or numeric) to float."""
        try:
            self.value = float(cast(str | float, value)) if value is not None else None
        except (ValueError, TypeError):
            self.value = None

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        try:
            if value is None or (isinstance(value, str) and str(value).strip() == ""):
                self.value = None
            else:
                self.value = float(cast(str | float, value))
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError):
            self.errors.append(
                f"Invalid number value '{value}' in column '({self.label})'"
            )

    # Filter Attributes
    _field_type = FieldType.NUMBER
    _field_options = FilterOptions.NUMBER.value

    @property
    def filter_value(self) -> float | None:
        if self.value is not None:
            try:
                return float(self.value)
            except (ValueError, TypeError):
                return None
        return None


class EmailInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty[str]):
    """Email input field. Validates format on browser submission, AI, and import.

    Set:
        value (str): Email address.

    Get:
        value (str): Email address.
        sort_value (bool): Whether an email exists (EXISTS ordering).
    """

    # Property Attributes
    _icon = "email"

    # Column Attributes
    _ordering = Ordering.EXISTS
    _editable = True

    def validate_submission(self, value: object) -> None:
        """Reject nonempty malformed addresses without replacing an existing value."""
        if value in (None, "", []):
            self.value = None
        elif not isinstance(value, str) or not EMAIL_REGEX.fullmatch(value):
            raise ValidationError(f"Invalid email address for '{self.label}'.")
        else:
            self.value = value

    # AI Attributes
    def validate_ai(self, value: object) -> None:
        """Validate AI-submitted email format."""
        if value and isinstance(value, str) and EMAIL_REGEX.match(value):
            self.value = value
        else:
            self.value = None

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        if isinstance(value, str) and not EMAIL_REGEX.match(value):
            self.errors.append(
                f"Invalid email value '{value}' in column '({self.label})'"
            )
        else:
            self.value = cast(str, value) if value else None

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value


class TelInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty[str]):
    """Telephone input field. Normalizes to E.164 format.

    Set:
        value (str): Phone number, parsed and formatted to E.164.

    Get:
        value (str): E.164 formatted phone number.
        form_value (str): US-formatted display string: "+1 (XXX) XXX-XXXX".
        sort_value (bool): Whether a phone number exists (EXISTS ordering).
    """

    # Property Attributes
    _icon = "tel"

    # Column Attributes
    _ordering = Ordering.EXISTS
    _editable = True

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value

    def _format_phone(self, value: object) -> str | None:
        if not value:
            return None

        try:
            parsed_number = phonenumbers.parse(cast(str, value), "US")
            return phonenumbers.format_number(
                parsed_number, phonenumbers.PhoneNumberFormat.E164
            )
        except phonenumbers.NumberParseException as error:
            raise ValidationError(
                f"Invalid phone number value '{value}' in column '({self.label})'"
            ) from error
        except (ValueError, TypeError):
            return None

    # AI Attributes
    def validate_ai(self, value: object) -> None:
        """Parse and normalize AI-submitted phone number to E.164 format."""
        if value:
            with suppress(ValidationError):
                self.value = self._format_phone(value)
        else:
            self.value = None

    # Ingress Attributes
    def validate_import(self, value: object) -> None:
        try:
            self.value = self._format_phone(value)
        except ValidationError as e:
            self.errors.append(e)

    def validate_submission(self, value: object) -> None:
        if value:
            with suppress(ValidationError):
                self.value = self._format_phone(value)
        else:
            self.value = None

    @property
    def form_value(self) -> str | None:
        if not self.value:
            return None

        digits = re.sub(r"\D", "", self.value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
