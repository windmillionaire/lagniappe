"""Jinja template filters for date, time, phone, and number formatting."""


# @testable true
# @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_basic_input_submission
# @pairs template-formatting:date template-formatting:time
def format_datetime(value):
    if not value:
        return ""
    elif isinstance(value, str):
        return value

    return value.strftime("%I:%M %p, %d %b %Y")


# @testable true
# @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_basic_input_submission
# @features template-formatting
# @dimensions date
def format_date(value):
    if not value:
        return ""
    elif isinstance(value, str):
        return value

    return value.strftime("%d %b %Y")


# @testable true
# @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_basic_input_submission
# @features template-formatting
# @dimensions time
def format_time(value):
    if not value:
        return ""
    elif isinstance(value, str):
        return value

    return value.strftime("%I:%M %p")


# @testable true
# @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_basic_input_submission
# @features template-formatting
# @dimensions phone
def format_phone(value):
    if not value:
        return ""

    digits = "".join(filter(str.isdigit, value))

    if len(digits) == 10:  # Standard US number
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):  # US number with country code
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

    return value


# @testable true
# @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_basic_input_submission
# @features template-formatting
# @dimensions number
def format_number(value):
    if value is None or value == "":
        return ""

    if isinstance(value, int):
        return f"{value:.0f}"
    elif isinstance(value, float):
        return f"{value:.2f}"
    else:
        return f"{value}"
