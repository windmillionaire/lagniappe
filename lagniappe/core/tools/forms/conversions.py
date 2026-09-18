"""Provider-free form conversions. Classification reads schemas, never submissions."""

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import phonenumbers

from ...exceptions import ValidationError
from .contracts import needs_ai_value


VERSION = 2
MISSING = object()
INPUTS = frozenset({"text", "number", "email", "tel", "date", "time"})
CHOICE = frozenset({"radio", "select", "multiple"})
REPLACEMENTS = {
    "checkbox": {"text", "radio"},
    "out": {"text", "bookmark"},
    "in": set(),
    "location": {"text"},
    "textarea": {"text"},
    "radio": {"text", "select", "multiple"},
    "select": {"text", "radio", "multiple"},
    "multiple": {"text", "radio", "select"},
}
KINDS = (
    ("text", "Text"),
    ("textarea", "Textarea"),
    ("number", "Number"),
    ("email", "Email"),
    ("tel", "Phone"),
    ("date", "Date"),
    ("time", "Time"),
    ("checkbox", "Checkbox"),
    ("radio", "Radio"),
    ("select", "Select"),
    ("multiple", "Multiple select"),
    ("out", "External link"),
    ("in", "Internal link"),
    ("bookmark", "Bookmark"),
    ("location", "Location"),
    ("table", "Table"),
    ("todo", "Todo list"),
)
TRUE = frozenset({"true", "yes", "1", "on"})
FALSE = frozenset({"false", "no", "0", "off"})


# @testable false
# @covered-by lagniappe/core/tools/forms/conversions.py::classify_changes
# @reason effective kinds are shared by schema classification and pure conversion
def field_kind(field):
    kind = field.get("type")
    if kind == "input":
        return field.get("input", "text")
    if kind == "link":
        return field.get("location", "out")
    if kind == "select" and field.get("multiple"):
        return "multiple"
    return kind


# @testable true
# @tests tests_unit/test_004j_form_conversions.py::test_capabilities_are_schema_only
# @matrix form-migration : capabilities no-submission-read
def conversion_rule(source, target):
    """Return an executable rule, an AI placeholder, or an unsupported result."""
    before, after = field_kind(source), field_kind(target) if target else "delete"
    if after == "delete":
        return "delete"
    if before == after:
        return "table" if before == "table" else "scalar"
    if before in REPLACEMENTS:
        if after in REPLACEMENTS[before]:
            return "scalar"
    elif before in INPUTS:
        # Inputs stay within their family (or expand to multiline text).
        # Typed values cannot meaningfully be parsed as unrelated input types.
        if after in {"text", "textarea"} or (before == "text" and after in INPUTS):
            return "scalar"
    elif before == "bookmark":
        if after in {"text", "textarea", "out", *CHOICE}:
            return "scalar"
    if before in {"table", "todo"} and after == "textarea":
        return "text"
    if before in {"textarea", "table", "todo"} and after in {"table", "todo"}:
        return "ai"
    return None


# @testable true
# @tests tests_unit/test_004j_form_conversions.py::test_capabilities_are_schema_only
# @matrix form-migration : capabilities no-submission-read
def conversion_catalog():
    """Project the same code-owned capabilities to the builder without I/O."""

    # @testable infrastructure
    def schema(kind):
        if kind in {"text", "email", "tel", "number", "date", "time"}:
            return {"type": "input", "input": kind}
        if kind in {"in", "out"}:
            return {"type": "link", "location": kind}
        if kind == "multiple":
            return {"type": "select", "multiple": True}
        return {"type": kind}

    return {
        "version": VERSION,
        "types": [
            {"value": kind, "label": label, "schema": schema(kind)}
            for kind, label in KINDS
        ],
        "rules": {
            kind: {
                other: conversion_rule(schema(kind), schema(other))
                for other, _ in KINDS
            }
            for kind, _ in KINDS
        },
    }


# @testable false
# @covered-by lagniappe/core/tools/forms/conversions.py::classify_changes
# @reason fingerprints exclude presentation and only identify representation changes
def representation(field):
    return {
        "kind": field_kind(field),
        "options": sorted(option["value"] for option in field.get("options", [])),
        "columns": {
            column["id"]: representation(column) for column in field.get("columns", [])
        },
    }


# @testable true
# @tests tests_unit/test_004j_form_conversions.py::test_schema_diff_preserves_ids_and_rejects_unsupported_changes
# @matrix form-migration : schema-diff identity validation
def classify_changes(previous, proposed, mappings=None):
    """Derive actual answer changes; caller-owned labels never classify a diff."""
    mappings = mappings or {}
    if not isinstance(mappings, dict):
        raise ValidationError("Invalid form conversion mappings.")
    targets = {field["id"]: field for field in proposed}
    changes = []
    for source in previous:
        field_id = source["id"]
        target = targets.get(field_id)
        if target and representation(source) == representation(target):
            continue
        if (
            target
            and field_kind(source) in CHOICE
            and field_kind(source) == field_kind(target)
        ):
            old_values = {option["value"] for option in source.get("options", [])}
            if old_values <= {option["value"] for option in target.get("options", [])}:
                continue
        if target and field_kind(source) == field_kind(target) == "table":
            columns = classify_changes(
                source.get("columns", []), target.get("columns", [])
            )
            if not columns:
                continue
        if field_id in {"name", "description"}:
            raise ValidationError(
                "Reserved Page fields cannot be removed or converted."
            )
        if source.get("type") in {"html", "status"}:
            if target:
                raise ValidationError(
                    "Static controls cannot be converted to answer fields."
                )
            continue
        rule = conversion_rule(source, target)
        if not rule:
            raise ValidationError(
                "This conversion is not available yet. Choose another type or delete the element."
            )
        if (
            rule == "ai"
            and field_kind(target) == "table"
            and (
                not target.get("columns")
                or any(
                    field_kind(column) not in INPUTS | {"checkbox", "out", "bookmark"}
                    for column in target["columns"]
                )
            )
        ):
            raise ValidationError(
                "AI table conversion requires destination scalar, checkbox or external-link columns. Configure the columns before Save."
            )
        mapping = mappings.get(field_id, {})
        if not isinstance(mapping, dict) or any(
            not isinstance(k, str) for k in mapping
        ):
            raise ValidationError("Invalid option mapping.")
        if any(
            not isinstance(value, (str, bool, type(None))) for value in mapping.values()
        ):
            raise ValidationError(
                "Option mappings must contain choices, checked states, or empty values."
            )
        changes.append(
            {
                "id": field_id,
                "source": deepcopy(source),
                "target": deepcopy(target),
                "rule": rule,
                "version": VERSION,
                "map": deepcopy(mapping),
            }
        )
    if set(mappings) - {change["id"] for change in changes}:
        raise ValidationError(
            "A conversion mapping refers to an unchanged or unavailable field."
        )
    return changes


# @testable false
# @covered-by lagniappe/core/tools/forms/conversions.py::convert_value
# @reason text extraction is a provider-free part of the conversion contract
def _text(value, source, zone):
    kind = field_kind(source)
    if kind in CHOICE:
        labels = {
            option["value"]: option["label"] for option in source.get("options", [])
        }
        values = value if isinstance(value, list) else [value]
        return "\n".join(str(labels.get(item, item)) for item in values)
    if kind == "checkbox":
        return "True" if value is True else "False" if value is False else str(value)
    if kind in {"out", "bookmark"}:
        return str(value.get("url", "")) if isinstance(value, dict) else str(value)
    if kind == "in":
        return str(value.get("name", "")) if isinstance(value, dict) else ""
    if kind == "location":
        if not isinstance(value, dict):
            return str(value)
        return ", ".join(
            dict.fromkeys(
                str(value[key])
                for key in ("name", "address", "address2")
                if value.get(key)
            )
        )
    if kind == "date":
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (
            parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
            .astimezone(ZoneInfo(zone))
            .date()
            .isoformat()
        )
    if kind == "todo":
        return "\n".join(
            f"- [{'x' if item.get('checked') else ' '}] {item['text']}"
            for item in value["items"]
        )
    if kind == "table":
        columns = source.get("columns", [])

        def cell(text):
            return text.replace("|", "\\|").replace("\n", "<br>")

        rows = value.get("rows", []) if isinstance(value, dict) else value
        output = [
            " | ".join(cell(column.get("title", column["id"])) for column in columns),
            " | ".join("---" for _ in columns),
        ]
        output.extend(
            " | ".join(
                cell(_text(row[column["id"]], column, zone))
                if column["id"] in row
                else ""
                for column in columns
            )
            for row in rows
        )
        return "\n".join(f"| {row} |" for row in output)
    return str(value)


# @testable false
# @covered-by lagniappe/core/tools/forms/conversions.py::convert_value
# @reason destination parsing is deliberately separate from coercing AI/import validators
def _parse(text, target, zone):
    kind = field_kind(target)
    value = text.strip()
    if kind == "textarea":
        return text
    if kind == "text":
        return text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    if not value:
        return MISSING
    if kind == "number":
        number = float(value)
        return number if math.isfinite(number) else MISSING
    if kind == "checkbox":
        return (
            True
            if value.casefold() in TRUE
            else False
            if value.casefold() in FALSE
            else MISSING
        )
    if kind == "email":
        return value if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) else MISSING
    if kind == "tel":
        phone = phonenumbers.parse(value, "US")
        return (
            phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)
            if phonenumbers.is_valid_number(phone)
            else MISSING
        )
    if kind == "date":
        parsed = date.fromisoformat(value)
        return (
            datetime.combine(parsed, datetime.min.time(), ZoneInfo(zone))
            .astimezone(timezone.utc)
            .isoformat()
        )
    if kind == "time":
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    if kind in {"out", "bookmark"}:
        parsed = urlsplit(value)
        return (
            {"url": value, "title": value}
            if parsed.scheme in {"https", "http"}
            and parsed.hostname
            and not re.search(r"\s", value)
            else MISSING
        )
    if kind == "location":
        return {"address": value, "name": value}
    if kind == "todo":
        items = []
        for line in text.splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r"\s*(?:-\s+)?\[([ xX])\]\s*(.+)", line)
            items.append(
                {
                    "text": match[2].strip() if match else line.strip(),
                    "checked": bool(match and match[1].lower() == "x"),
                }
            )
        return {"items": items} if items else MISSING
    return MISSING


# @testable true
# @tests tests_unit/test_004j_form_conversions.py::test_scalar_conversions_and_invalid_values
# @tests tests_unit/test_004j_form_conversions.py::test_table_and_collection_conversions
# @matrix form-migration : conversion invalid-value presence nested-columns provider-free
def convert_value(value, source, target, *, mapping=None, zone="UTC"):
    """Return (value or MISSING, reason); malformed answers clear deterministically."""
    if target is None:
        return MISSING, "removed"
    if value is MISSING or value is None:
        return MISSING, "unset"
    before, after = field_kind(source), field_kind(target)
    try:
        if before == after == "table":
            rows = value.get("rows", []) if isinstance(value, dict) else value
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) for row in rows
            ):
                return MISSING, "invalid"
            changes = classify_changes(
                source.get("columns", []), target.get("columns", [])
            )
            converted = []
            for row in rows:
                item = deepcopy(row)
                for change in changes:
                    result, _reason = convert_value(
                        row.get(change["id"], MISSING),
                        change["source"],
                        change["target"],
                        zone=zone,
                    )
                    if result is MISSING:
                        item.pop(change["id"], None)
                    else:
                        item[change["id"]] = result
                converted.append(item)
            return {"rows": converted}, "converted"
        if before == after and before not in CHOICE:
            return deepcopy(value), "unchanged"
        if before in CHOICE or after in CHOICE:
            values = value if isinstance(value, list) else [value]
            if after in CHOICE:
                allowed = {option["value"] for option in target.get("options", [])}
                converted = []
                for item in values:
                    token = str(item).lower() if isinstance(item, bool) else str(item)
                    mapped = (mapping or {}).get(token, item)
                    if mapped not in allowed:
                        label = _text(item, source, zone).strip().casefold()
                        matches = [
                            option["value"]
                            for option in target.get("options", [])
                            if option["label"].strip().casefold() == label
                        ]
                        mapped = (
                            matches[0]
                            if len(matches) == 1 and token not in (mapping or {})
                            else MISSING
                        )
                    if mapped in allowed and mapped not in converted:
                        converted.append(mapped)
                if after == "multiple":
                    return (converted if converted else MISSING), "converted" if len(
                        converted
                    ) == len(values) else "invalid"
                return (
                    (converted[0], "converted")
                    if len(values) == len(converted) == 1
                    else (MISSING, "invalid")
                )
            if before in CHOICE and after == "checkbox" and len(values) == 1:
                mapped = (mapping or {}).get(str(values[0]), MISSING)
                if isinstance(mapped, bool):
                    return mapped, "converted"
                if mapped is None:
                    return MISSING, "invalid"
        if before in {"out", "bookmark"} and after in {"out", "bookmark"}:
            return deepcopy(value), "converted"
        if before == "checkbox" and after == "number" and isinstance(value, bool):
            return int(value), "converted"
        result = _parse(_text(value, source, zone), target, zone)
        return result, "invalid" if result is MISSING else "converted"
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        phonenumbers.NumberParseException,
    ):
        return MISSING, "invalid"


# @testable true
# @tests tests_unit/test_004j_form_conversions.py::test_submission_notice_preserves_first_values_and_unrelated_answers
# @matrix form-migration : notice preservation presence repeated-change
def convert_submission(
    values, changes, *, previous_notice=None, generation=0, zone="UTC", ai_values=None
):
    """Patch planned paths and retain one cumulative informational before-state."""
    result = deepcopy(values)
    notice = deepcopy(previous_notice or {})
    for change in changes:
        field_id = change["id"]
        before = values.get(field_id, MISSING)
        if change["rule"] == "ai":
            if before is MISSING or not needs_ai_value(before):
                after, reason = MISSING, "unset"
            else:
                candidate = (ai_values or {}).get(field_id)
                if candidate is None:
                    raise ValidationError("A prepared AI conversion is missing.")
                after = validate_ai_candidate(candidate, change["target"])
                reason = "invalid" if after is MISSING else "ai"
        else:
            after, reason = convert_value(
                before,
                change["source"],
                change["target"],
                mapping=change["map"],
                zone=zone,
            )
        if after is MISSING:
            result.pop(field_id, None)
        else:
            result[field_id] = after
        if before is MISSING or (
            after is not MISSING
            and json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
        ):
            continue
        entry = notice.setdefault(
            field_id,
            {
                "schema": deepcopy(change["source"]),
                "value": deepcopy(before),
                "generation": generation,
            },
        )
        entry["reason"] = reason
        if after is not MISSING and json.dumps(
            entry["value"], sort_keys=True
        ) == json.dumps(after, sort_keys=True):
            notice.pop(field_id, None)
    return result, notice


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_ai_candidates_validate_exact_shapes_without_truthiness_coercion
# @matrix form-migration : ai-value strict-validation table todo
def validate_ai_candidate(candidate, target):
    """Accept exact destination values or an explicit unresolved outcome."""
    if not isinstance(candidate, dict):
        raise ValidationError("AI conversion must return an object.")
    if "unresolved_reason" in candidate:
        reason = candidate["unresolved_reason"]
        if "value" in candidate or not isinstance(reason, str) or not reason.strip():
            raise ValidationError(
                "An unresolved conversion requires a reason and no value."
            )
        return MISSING
    if "value" not in candidate:
        raise ValidationError("AI conversion requires a value or unresolved_reason.")
    value = candidate["value"]
    if not isinstance(value, dict):
        raise ValidationError(
            "AI conversion must use the destination collection envelope."
        )
    if field_kind(target) == "todo":
        if set(value) != {"items"} or not isinstance(value["items"], list):
            raise ValidationError("Todo conversion requires an items array.")
        for item in value["items"]:
            if (
                not isinstance(item, dict)
                or set(item) != {"text", "checked"}
                or not isinstance(item["text"], str)
                or not item["text"].strip()
                or not isinstance(item["checked"], bool)
            ):
                raise ValidationError(
                    "Todo items require nonempty text and a boolean checked value."
                )
    elif field_kind(target) == "table":
        if set(value) != {"rows"} or not isinstance(value["rows"], list):
            raise ValidationError("Table conversion requires a rows array.")
        columns = {column["id"]: column for column in target.get("columns", [])}
        if not columns:
            raise ValidationError("AI table conversion requires destination columns.")
        for row_number, row in enumerate(value["rows"], start=1):
            if not isinstance(row, dict) or not row or set(row) - set(columns):
                raise ValidationError(
                    "Table conversion must use exact destination column IDs."
                )
            for field_id, cell in row.items():
                kind = field_kind(columns[field_id])
                try:
                    if kind == "checkbox":
                        valid = isinstance(cell, bool)
                    elif kind == "number":
                        valid = (
                            isinstance(cell, (int, float))
                            and not isinstance(cell, bool)
                            and math.isfinite(cell)
                        )
                    elif kind in {"out", "bookmark"}:
                        valid = (
                            isinstance(cell, dict)
                            and set(cell) <= {"url", "title"}
                            and isinstance(cell.get("url"), str)
                            and isinstance(cell.get("title", ""), str)
                            and _parse(cell["url"], columns[field_id], "UTC")
                            is not MISSING
                        )
                    elif kind == "date":
                        valid = (
                            isinstance(cell, str)
                            and datetime.fromisoformat(cell).tzinfo is not None
                        )
                    else:
                        valid = (
                            kind in INPUTS
                            and isinstance(cell, str)
                            and _parse(cell, columns[field_id], "UTC") is not MISSING
                        )
                except (
                    ValueError,
                    TypeError,
                    OverflowError,
                    phonenumbers.NumberParseException,
                ):
                    valid = False
                if not valid:
                    title = columns[field_id].get("title") or "Untitled column"
                    expected = {
                        "checkbox": "a checked or unchecked value",
                        "number": "a number",
                        "date": "a date with a timezone",
                        "time": "a time",
                        "email": "an email address",
                        "tel": "a phone number",
                        "out": "a web link",
                        "bookmark": "a web link",
                    }.get(kind, "text")
                    raise ValidationError(
                        f'“{title}”, row {row_number}: the converted value must be {expected}.'
                    )
    else:
        raise ValidationError("Unsupported AI conversion destination.")
    if not value.get("rows", value.get("items")):
        raise ValidationError(
            "Use unresolved_reason to clear a populated source; do not return an empty collection."
        )
    return deepcopy(value)
