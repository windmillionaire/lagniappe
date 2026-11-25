"""Jinja template filters for text, date, time, phone, and number formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime, time

from lagniappe.core.tools.files.html import render_markdown, strip_tags


def format_markdown_text(value: str) -> str:
    """Flatten Markdown into escaped-by-Jinja text for compact previews."""
    return strip_tags(render_markdown(value))


def format_datetime(value: datetime | str | None) -> str:
    if not value:
        return ""
    elif isinstance(value, str):
        return value

    return value.strftime("%I:%M %p, %d %b %Y")


def format_date(value: date | str | None) -> str:
    if not value:
        return ""
    elif isinstance(value, str):
        return value

    return value.strftime("%d %b %Y")


def format_time(value: datetime | time | str | None) -> str:
    if not value:
        return ""
    elif isinstance(value, str):
        return value

    return value.strftime("%I:%M %p")


def format_phone(value: str | None) -> str:
    if not value:
        return ""

    digits = "".join(filter(str.isdigit, value))

    if len(digits) == 10:  # Standard US number
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):  # US number with country code
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

    return value


def format_number(value: object) -> str:
    if value is None or value == "":
        return ""

    if isinstance(value, int):
        return f"{value:.0f}"
    elif isinstance(value, float):
        return f"{value:.2f}"
    else:
        return f"{value}"
