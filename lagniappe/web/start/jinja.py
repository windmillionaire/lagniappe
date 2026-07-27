"""Jinja environment setup: custom tests, filters, and template globals."""

from datetime import date, datetime

from flask.json.provider import DefaultJSONProvider
from flask_login import current_user
from markupsafe import Markup, escape

from lagniappe import CONFIG
from lagniappe.core.definitions import Action, Resource
from lagniappe.core.tools import dates

from . import formatters, styles


# @testable false
# @reason Flask/Jinja startup helpers are exercised through rendered E2E pages; unit coverage would require app-context scaffolding
class SafeJSONProvider(DefaultJSONProvider):
    """JSON provider that gracefully handles non-serializable types
    so ``|tojson`` in templates never raises TypeError."""

    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if hasattr(o, "__json__"):
            return o.__json__()
        return str(o)


# @testable false
# @reason current-user template helper is exercised through rendered E2E pages
def starred(entity):
    if entity.key in current_user.properties.starred.keys:
        return True
    return False


# @testable false
# @reason Flask/Jinja date tests are exercised through rendered E2E pages
def is_datetime(value):
    return isinstance(value, datetime)


# @testable false
# @reason Flask/Jinja date tests are exercised through rendered E2E pages
def _date(value):
    if isinstance(value, datetime):
        return value.date()
    elif isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    elif isinstance(value, float):
        return datetime.fromtimestamp(value).astimezone(dates.user_timezone()).date()
    else:
        return None


# @testable false
# @reason Flask/Jinja filters are exercised through rendered E2E pages
def yesno(value):
    return "true" if value else "false"


# @testable false
# @reason Flask/Jinja filters are exercised through rendered E2E pages
def _icon_definition(key):
    definition = styles.ICONS
    for part in str(key or "").split("."):
        if not part or not isinstance(definition, dict):
            return None
        definition = definition.get(part)
    if not isinstance(definition, dict) or "glyph" not in definition:
        return None
    return definition


# @testable true
# @tests tests_e2e/002_home/test_002a_home.py::test_home_material_symbols_use_semantic_span_markup
# @pairs home:material-symbol-markup icons:material-symbol-markup
def render_icon(key, classes="", kind=None):
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


# @testable false
# @reason Flask/Jinja date tests are exercised through rendered E2E pages
def is_after_today(value):
    date = _date(value)
    if not date:
        return False

    return date > dates.user_today().date()


# @testable false
# @reason Flask/Jinja date tests are exercised through rendered E2E pages
def is_before_today(value):
    date = _date(value)
    if not date:
        return False

    return date < dates.user_today().date()


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_navbar_task_results_handle_legacy_completed_values
# @features template-formatting
# @dimensions tojson safe-json
def initialize(app):
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
            "format_date_as_input_string": dates.format_date_as_input_string,
            "yesno": yesno,
        }
    )
    app.jinja_env.globals.update(
        {
            "CONFIG": CONFIG,
            "render_icon": render_icon,
            "styles": styles.STYLES,
            "is_starred": starred,
            "current_user": current_user,
            "Action": Action,
            "Resource": Resource,
        }
    )
