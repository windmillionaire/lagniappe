from datetime import datetime
import re

from dateutil import parser as date_parser
import phonenumbers

from ..definitions import FieldType, FilterOptions, Ordering
from ..exceptions import ValidationError
from ..mixins import AIMixin, ColumnMixin, DateMixin, FilterMixin, SearchMixin
from .base_schema import SchemaProperty

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


# @testable true
# @tests tests_unit/test_003a_submission_basic.py::test_submission_text_input
# @tests tests_unit/test_003a_submission_basic.py::test_submission_text_input_empty_column_value_is_blank
# @tests tests_unit/test_004d_submitter.py::test_text_input_validate_import_space_joins_list_values
# @tests tests_unit/test_004d_submitter.py::test_import_submission_space_joins_input_list_values
# @tests tests_unit/test_004b_schema_core.py::test_schema_create_field_known_text_input
# @matrix text-input : ai-value column empty-field empty-value field-factory filter-value import list-normalization save search-value
class TextInput(SearchMixin, AIMixin, FilterMixin, ColumnMixin, SchemaProperty):
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
    def validate_import(self, value):
        try:
            value_string = (
                " ".join(
                    str(v).strip() for v in value if v is not None and str(v).strip()
                )
                if isinstance(value, list)
                else value
            )
            self.value = value_string if value_string else None
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
    def sort_value(self):
        return self.value.replace("The ", "").lower() if self.value else None

    @property
    def search_value(self):
        if self.id == "name":
            return None
        return super().search_value


# @testable true
# @tests tests_unit/test_003a_submission_basic.py::test_submission_date_input
# @matrix date-input : ai-value column filter-value import
class DateInput(DateMixin, AIMixin, FilterMixin, ColumnMixin, SchemaProperty):
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
    _ordering = Ordering.NUMERIC
    _editable = True

    # Form Attributes
    def validate_submission(self, value):
        """Parse form-submitted date string (YYYY-MM-DD format)."""
        if value:
            self.value = value  # DateMixin.value setter handles parsing
        else:
            self._value = None

    # AI Attributes
    def validate_ai(self, value):
        """Parse AI-submitted date string (YYYY-MM-DD format, UTC)."""
        if value:
            self.value = date_parser.parse(value)
        else:
            self._value = None

    # Ingress Attributes
    def validate_import(self, value):
        try:
            self.value = value if not value else date_parser.parse(value)
        except ValidationError as e:
            self.errors.append(e)
        except (ValueError, TypeError, date_parser.ParserError):
            self.errors.append(
                f"Invalid date value '{value}' in column '({self.label})'"
            )

    # Filter Attributes
    _field_type = FieldType.TIMESTAMP
    _field_options = FilterOptions.DATE.value


# @testable true
# @tests tests_unit/test_003a_submission_basic.py::test_submission_time_input
# @matrix time-input : ai-value column filter-value import
class TimeInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty):
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
    _ordering = Ordering.NUMERIC
    _editable = True

    # Form Attributes
    # @testable true
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_time_form_invalid_format_raises
    # @matrix time-input : form-submission validation
    def validate_submission(self, value):
        """Parse form-submitted time string (HH:MM format)."""
        if value:
            self.value = datetime.strptime(value, "%H:%M")
        else:
            self._value = None

    # Ingress Attributes
    def validate_import(self, value):
        try:
            self.value = datetime.strptime(value, "%H:%M") if value else None
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
    def filter_value(self):
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
    def validate_ai(self, value):
        """Parse AI-submitted time string (HH:MM format)."""
        if value:
            self.value = datetime.strptime(value, "%H:%M")
        else:
            self._value = None

    @property
    def ai_value(self):
        return self.value.strftime("%H:%M") if self.value else None

    @property
    def db_value(self):
        return self.value.strftime("%H:%M") if self.value else None

    @db_value.setter
    def db_value(self, value):
        self.value = datetime.strptime(value, "%H:%M") if value else None


# @testable true
# @tests tests_unit/test_003a_submission_basic.py::test_submission_number_input
# @matrix number-input : ai-value filter-value import
class NumberInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty):
    """Numeric input field. Stored as a float.

    Set:
        value (float | str): Converted to float on set.

    Get:
        value (float): Numeric value.
        sort_value (float): Same as filter_value.
        filter_value (float): float(value), or None if invalid.
    """

    # Property Attributes
    _icon = "number"

    # Column Attributes
    _ordering = Ordering.NUMERIC
    _editable = True

    @property
    def sort_value(self):
        return self.filter_value

    # Form Attributes
    # @testable true
    # @tests tests_unit/test_004e_submission_behavior.py::test_submission_number_form_accepts_zero
    # @matrix number-input : form-submission zero
    def validate_submission(self, value):
        """Parse form-submitted number string to float."""
        try:
            if value is None or (isinstance(value, str) and value.strip() == ""):
                self.value = None
            else:
                self.value = float(value)
        except (ValueError, TypeError):
            self.value = None

    # AI Attributes
    def validate_ai(self, value):
        """Parse AI-submitted number (string or numeric) to float."""
        try:
            self.value = float(value) if value is not None else None
        except (ValueError, TypeError):
            self.value = None

    # Ingress Attributes
    def validate_import(self, value):
        try:
            if value is None or (isinstance(value, str) and str(value).strip() == ""):
                self.value = None
            else:
                self.value = float(value)
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
    def filter_value(self):
        if self.value is not None:
            try:
                return float(self.value)
            except (ValueError, TypeError):
                return None
        return None


# @testable true
# @tests tests_unit/test_003a_submission_basic.py::test_submission_email_input
# @tests tests_unit/test_004e_submission_behavior.py::test_submission_email_form_accepts_non_matching_string
# @matrix email-input : ai-value filter-value form-submission import validation
class EmailInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty):
    """Email input field. Validates format against EMAIL_REGEX on import.

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

    # AI Attributes
    def validate_ai(self, value):
        """Validate AI-submitted email format."""
        if value and isinstance(value, str) and EMAIL_REGEX.match(value):
            self.value = value
        else:
            self.value = None

    # Ingress Attributes
    def validate_import(self, value):
        if isinstance(value, str) and not EMAIL_REGEX.match(value):
            self.errors.append(
                f"Invalid email value '{value}' in column '({self.label})'"
            )
        else:
            self.value = value if value else None

    # Filter Attributes
    _field_type = FieldType.STRING
    _field_options = FilterOptions.STRING.value


# @testable true
# @tests tests_unit/test_003a_submission_basic.py::test_submission_tel_input
# @matrix tel-input : ai-value filter-value formatting import
class TelInput(AIMixin, FilterMixin, ColumnMixin, SchemaProperty):
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

    def _format_phone(self, value):
        if not value:
            return None

        try:
            parsed_number = phonenumbers.parse(value, "US")
            return phonenumbers.format_number(
                parsed_number, phonenumbers.PhoneNumberFormat.E164
            )
        except phonenumbers.NumberParseException:
            raise ValidationError(
                f"Invalid phone number value '{value}' in column '({self.label})'"
            )
        except (ValueError, TypeError):
            return None

    # AI Attributes
    def validate_ai(self, value):
        """Parse and normalize AI-submitted phone number to E.164 format."""
        if value:
            try:
                self.value = self._format_phone(value)
            except ValidationError:
                pass
        else:
            self.value = None

    # Ingress Attributes
    def validate_import(self, value):
        try:
            self.value = self._format_phone(value)
        except ValidationError as e:
            self.errors.append(e)

    def validate_submission(self, value):
        if value:
            try:
                self.value = self._format_phone(value)
            except ValidationError:
                pass
        else:
            self.value = None

    @property
    def form_value(self):
        if not self.value:
            return None

        digits = re.sub(r"\D", "", self.value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
