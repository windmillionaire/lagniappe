"""Filter lists and constants for debug context extraction."""

import sys
FILTER_KEYS = {
    "self",
    "cls",
    "app",
    "current_app",
    "request",
    "g",
    "session",
    "_request_ctx_stack",
}

# Jinja template globals and built-ins to filter from locals
# These are injected into every template context and aren't useful for debugging
JINJA_GLOBALS_FILTER = {
    # App-defined globals (from __init__.py)
    "VERSION",
    "CAPTURE_ERRORS",
    "icons",
    "colors",
    "elements",
    "layout",
    "short_uuid",
    "is_starred",
    "has_permission",
    "Action",
    "Resource",
    # Jinja2 built-in globals
    "range",
    "dict",
    "lipsum",
    "cycler",
    "joiner",
    "namespace",
    # Flask-injected globals
    "config",
    "url_for",
    "get_flashed_messages",
}

# Types to skip when extracting local variables
SKIP_TYPES = (type, type(lambda: None), type(sys))

# Keys in entity.db that are stored as JSON strings and should be decoded
JSON_DB_KEYS = {
    "options",
    "assets",
    "definitions",
    "schema",
    "permissions",
    "settings",
    "submission",
    "schedule",
}

