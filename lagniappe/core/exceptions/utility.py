"""Formatting utilities for debug context display (pretty-printing, safe repr)."""

import json
from pprint import pformat

from .constants import JSON_DB_KEYS


def pretty_print_dict(d, indent=0, decode_json_keys=False):
    """Pretty print a dictionary with nice formatting for HTML display.

    Args:
        d: Dictionary to format
        indent: Current indentation level
        decode_json_keys: If True, attempt to JSON-decode values for keys in JSON_DB_KEYS
    """
    if not isinstance(d, dict):
        return repr(d)

    lines = []
    prefix = "  " * indent

    for key, value in d.items():
        # Check if this key should be JSON-decoded
        if decode_json_keys and key in JSON_DB_KEYS and isinstance(value, str):
            try:
                decoded = json.loads(value)
                lines.append(f"{prefix}{key}: (JSON)")
                lines.append(pretty_print_dict(decoded, indent + 1))
                continue
            except (json.JSONDecodeError, TypeError):
                pass  # Fall through to normal handling

        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(pretty_print_dict(value, indent + 1))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
            elif len(value) <= 3 and all(
                not isinstance(v, (dict, list)) for v in value
            ):
                lines.append(f"{prefix}{key}: {value!r}")
            else:
                lines.append(f"{prefix}{key}: [")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(pretty_print_dict(item, indent + 2))
                    else:
                        lines.append(f"{prefix}    {item!r}")
                lines.append(f"{prefix}  ]")
        elif isinstance(value, str) and len(value) > 100:
            # Truncate long strings
            lines.append(f"{prefix}{key}: {value[:100]!r}... [{len(value)} chars]")
        else:
            lines.append(f"{prefix}{key}: {value!r}")

    return "\n".join(lines)


def safe_repr(obj, max_length=2000, is_entity_context=False):
    """Safely convert an object to a string representation.

    Args:
        obj: Object to represent
        max_length: Maximum length of output string
        is_entity_context: If True, decode JSON keys in entity.db
    """
    try:
        if hasattr(obj, "db") and isinstance(obj.db, dict):
            # This is likely an entity - pretty print its db attribute with JSON decoding
            entity_type = type(obj).__name__
            db_formatted = pretty_print_dict(obj.db, decode_json_keys=True)
            return f"<{entity_type}>\n{db_formatted}"
        elif isinstance(obj, dict):
            # Pretty print dictionaries (with JSON decoding if in entity context)
            return pretty_print_dict(obj, decode_json_keys=is_entity_context)
        elif hasattr(obj, "__dict__"):
            # For objects with __dict__, show a summary
            attrs = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
            if attrs:
                result = f"<{type(obj).__name__}>\n{pretty_print_dict(attrs)}"
            else:
                result = repr(obj)
        else:
            result = pformat(obj, width=80, depth=3)

        if len(result) > max_length:
            return result[:max_length] + "... [truncated]"
        return result
    except Exception:
        return f"<Unable to represent: {type(obj).__name__}>"


def format_debug_context_for_template(context):
    """Format debug context for display in a template."""
    formatted = {
        "timestamp": context.get("timestamp"),
        "error_type": context.get("error_type"),
        "error_message": context.get("error_message"),
        "traceback": context.get("traceback"),
    }

    # Format request info with pretty printing
    if context.get("request"):
        formatted["request"] = pretty_print_dict(context["request"])

    # Entity info
    if context.get("entity"):
        formatted["entity"] = context["entity"]

    return formatted
