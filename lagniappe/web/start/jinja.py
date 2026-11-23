"""Jinja environment setup: custom tests, filters, and template globals."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    from lagniappe.core.entities.entity import Entity

from datetime import date, datetime

from flask.json.provider import DefaultJSONProvider
from flask_login import current_user
from markupsafe import Markup, escape

from lagniappe import CONFIG
from lagniappe.core.definitions import AI, Action, Resource
from lagniappe.core.tools import cache, dates
from lagniappe.core.tools.files.html import SafeHTML
from lagniappe.reference import get_topic, topics, topic_html, topic_sections, topic_context

from . import formatters, styles


class SafeJSONProvider(DefaultJSONProvider):
    """JSON provider that gracefully handles non-serializable types
    so ``|tojson`` in templates never raises TypeError."""

    def default(self, o: object) -> object:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        serializer = getattr(o, "__json__", None)
        if callable(serializer):
            return serializer()
        return str(o)


def starred(entity: Entity) -> bool:
    return entity.key in current_user.properties.starred.keys


def owner_allows_assignments() -> bool:
    owner = cache.get_owner_projection()
    return bool(owner and owner.get("allow_task_assignments"))


def is_datetime(value: object) -> bool:
    return isinstance(value, datetime)


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    elif isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    elif isinstance(value, float):
        return datetime.fromtimestamp(value).astimezone(dates.user_timezone()).date()
    else:
        return None


def yesno(value: object) -> str:
    return "true" if value else "false"


def render_safe_html(value: SafeHTML) -> Markup:
    """Expose only policy-stamped HTML at an explicit Jinja raw sink."""
    if not isinstance(value, SafeHTML):
        raise TypeError(f"safe_html requires SafeHTML, got {type(value).__name__}")
    return Markup(str(value))


def _icon_definition(key):
    definition = styles.ICONS
    for part in str(key or "").split("."):
        if not part or not isinstance(definition, dict):
            return None
        definition = definition.get(part)
    if not isinstance(definition, dict) or "glyph" not in definition:
        return None
    return definition


def render_icon(key: str, classes: str | None = "", kind: str | None = None) -> Markup:
    """Render one decorative Material Symbol from its semantic registry ID."""
    definition = _icon_definition(key)
    if not definition:
        return Markup("")

    class_names = ["icon"]
    if definition.get("spin"):
        class_names.append("icon-spin")
    if classes:
        class_names.extend(str(classes).split())

    attributes = [
        f'class="{escape(" ".join(class_names))}"',
        f'data-icon="{escape(str(key))}"',
        f'data-fill="{definition["fill"]}"',
        'aria-hidden="true"',
    ]
    if weight := definition.get("weight"):
        attributes.append(f'data-weight="{weight}"')
    if kind:
        attributes.append(f'data-kind="{escape(str(kind))}"')

    glyph = escape(definition["glyph"])
    return Markup(
        f"<span {' '.join(attributes)}>"
        f'<span class="icon-glyph">{glyph}</span>'
        "</span>"
    )


def is_after_today(value: date | datetime | None) -> bool:
    date = _date(value)
    if not date:
        return False

    return date > dates.user_today().date()


def is_before_today(value: date | datetime | None) -> bool:
    date = _date(value)
    if not date:
        return False

    return date < dates.user_today().date()


def initialize(app: Flask) -> None:
    app.json_provider_class = SafeJSONProvider
    app.json = SafeJSONProvider(app)

    app.jinja_options.update({"trim_blocks": True, "lstrip_blocks": True})
    app.jinja_env.policies["json.dumps_function"] = app.json.dumps
    app.jinja_env.tests.update(
        {
            "datetime": is_datetime,
            "in_future": is_after_today,
            "in_past": is_before_today,
        }
    )
    app.jinja_env.filters.update(
        {
            "format_datetime": formatters.format_datetime,
            "format_date": formatters.format_date,
            "format_time": formatters.format_time,
            "format_phone": formatters.format_phone,
            "format_number": formatters.format_number,
            "format_markdown_text": formatters.format_markdown_text,
            "format_date_as_input_string": dates.format_date_as_input_string,
            "yesno": yesno,
            "safe_html": render_safe_html,
        }
    )
    app.jinja_env.filters.pop("safe", None)
    from flask import g, has_request_context
    from lagniappe.core.tools.ai.auto_execute import site_auto_execute_enabled
    from lagniappe.web.deferred_autofill import form_state

    def auto_execute_site_enabled() -> bool:
        if has_request_context():
            cached = getattr(g, "_auto_execute_site_enabled", None)
            if cached is not None:
                return bool(cached)
            value = site_auto_execute_enabled()
            g._auto_execute_site_enabled = value
            return value
        return site_auto_execute_enabled()

    app.jinja_env.globals.update(
        {
            "CONFIG": CONFIG,
            "help_topic": get_topic,
            "help_topics": topics,
            "help_html": topic_html,
            "help_sections": topic_sections,
            "help_context": topic_context,
            "render_icon": render_icon,
            "styles": styles.STYLES,
            "fonts": styles.FONTS,
            "is_starred": starred,
            "current_user": current_user,
            "form_state": form_state,
            "Action": Action,
            "AI": AI,
            "Resource": Resource,
            "owner_allows_assignments": owner_allows_assignments,
            "auto_execute_site_enabled": auto_execute_site_enabled,
        }
    )
