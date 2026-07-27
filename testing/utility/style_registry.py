"""Shared semantic style-registry schema and normalization helpers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re

import yaml


DEFAULT_STYLES_PATH = Path("src/style/styles.yaml")
DEFAULT_SCHEMA_PATH = Path("src/style/registry.schema.json")
DEFAULT_ICONS_PATH = Path("src/style/icons.yaml")
DEFAULT_ICONS_SCHEMA_PATH = Path("src/style/icons.schema.json")
FALLBACK_SCHEMA: dict[str, object] = {
    "schema_version": 1,
    "id_segment_pattern": r"^[a-z][A-Za-z0-9]*$",
    "record_fields": [
        "alias",
        "classes",
        "intent",
        "surfaces",
        "markers",
        "hooks",
        "css",
        "exceptions",
    ],
    "required_metadata": [],
    "surfaces": ["server", "frontend"],
    "exception_fields": ["diagnostic", "target", "reason"],
    "exception_diagnostics": ["duplicate-style-value"],
}
FALLBACK_ICONS_SCHEMA: dict[str, object] = {
    "schema_version": 2,
    "id_segment_pattern": r"^[a-z][A-Za-z0-9]*$",
    "glyph_pattern": r"^[a-z][a-z0-9_]*$",
    "record_fields": ["glyph", "fill", "weight", "spin"],
    "weights": [300, 400, 500, 600],
}


@dataclass
class StyleDefinition:
    name: str
    classes: str
    tokens: list[str]
    alias: str = ""
    canonical: str = ""
    intent: str = ""
    surfaces: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    css: list[str] = field(default_factory=list)
    exceptions: list[dict[str, str]] = field(default_factory=list)


def load_registry_schema(
    repo_root: Path,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> dict[str, object]:
    """Load the authored registry contract, with a relaxed isolated-test fallback."""
    path = schema_path if schema_path.is_absolute() else repo_root / schema_path
    if not path.is_file():
        return dict(FALLBACK_SCHEMA)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("style registry schema must be an object")
    required = set(FALLBACK_SCHEMA)
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(
            "style registry schema is missing fields: " + ", ".join(missing)
        )
    return data


def load_icons_schema(
    repo_root: Path,
    schema_path: Path = DEFAULT_ICONS_SCHEMA_PATH,
) -> dict[str, object]:
    """Load the shared Material Symbol registry contract."""
    path = schema_path if schema_path.is_absolute() else repo_root / schema_path
    if not path.is_file():
        return dict(FALLBACK_ICONS_SCHEMA)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("icon registry schema must be an object")
    missing = sorted(set(FALLBACK_ICONS_SCHEMA) - set(data))
    if missing:
        raise ValueError(
            "icon registry schema is missing fields: " + ", ".join(missing)
        )
    return data


def flatten_icon_definitions(
    data: object,
    *,
    schema: dict[str, object] | None = None,
) -> dict[str, dict[str, object]]:
    """Validate and flatten a nested Material Symbol registry."""
    contract = schema or dict(FALLBACK_ICONS_SCHEMA)
    id_pattern = re.compile(str(contract["id_segment_pattern"]))
    glyph_pattern = re.compile(str(contract["glyph_pattern"]))
    record_fields = {str(field) for field in contract["record_fields"]}
    weights = {int(weight) for weight in contract["weights"]}
    definitions: dict[str, dict[str, object]] = {}

    def collect(value: object, name: str) -> None:
        if not isinstance(value, dict) or not value:
            raise TypeError(f"{name or 'icons'} must be a non-empty mapping")
        if "glyph" in value:
            unknown = sorted(set(value) - record_fields)
            if unknown:
                raise ValueError(
                    f"{name} has unknown icon fields: {', '.join(unknown)}"
                )
            glyph = value.get("glyph")
            if not isinstance(glyph, str) or not glyph_pattern.fullmatch(glyph):
                raise ValueError(f"{name}.glyph must be a Material Symbol name")
            fill = value.get("fill")
            if isinstance(fill, bool) or fill not in {0, 1}:
                raise ValueError(f"{name}.fill must be 0 or 1")
            if "weight" in value and (
                isinstance(value["weight"], bool) or value["weight"] not in weights
            ):
                raise ValueError(
                    f"{name}.weight must be one of "
                    + ", ".join(str(weight) for weight in sorted(weights))
                )
            if "spin" in value and not isinstance(value["spin"], bool):
                raise TypeError(f"{name}.spin must be a boolean")
            definitions[name] = dict(value)
            return
        if set(value) & record_fields:
            raise ValueError(f"{name} must define glyph and fill together")
        for key, child in value.items():
            key_text = str(key)
            if not id_pattern.fullmatch(key_text):
                raise ValueError(
                    f"{name or 'icons'} has invalid icon ID segment {key_text}"
                )
            child_name = f"{name}.{key_text}" if name else key_text
            collect(child, child_name)

    collect(data, "")
    return definitions


def normalize_icon_registry(
    data: object,
    *,
    schema: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return the validated nested runtime form of the icon registry."""
    definitions = flatten_icon_definitions(data, schema=schema)
    normalized: dict[str, object] = {}
    for name, definition in definitions.items():
        parts = name.split(".")
        target = normalized
        for part in parts[:-1]:
            target = target.setdefault(part, {})  # type: ignore[assignment]
        target[parts[-1]] = definition
    return normalized


def split_class_tokens(value: str) -> list[str]:
    tokens = []
    for raw_token in re.split(r"\s+", value.strip()):
        token = raw_token.strip().strip("`")
        if not token:
            continue
        if any(marker in token for marker in ("{{", "}}", "{%", "%}", "${", "}")):
            continue
        if token in {"class", "className"}:
            continue
        tokens.append(token)
    return tokens


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{label} must be a list of strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicates")
    return list(value)


def style_record(
    data: object,
    name: str,
    schema: dict[str, object],
) -> dict[str, object] | None:
    if not isinstance(data, dict) or not ({"classes", "alias"} & set(data)):
        return None
    record_fields = {str(value) for value in schema["record_fields"]}
    unknown = sorted(set(data) - record_fields)
    if unknown:
        raise ValueError(f"{name} has unknown style fields: {', '.join(unknown)}")
    if ("classes" in data) == ("alias" in data):
        raise ValueError(f"{name} must define exactly one of classes or alias")
    if "classes" in data and not isinstance(data["classes"], str):
        raise TypeError(f"{name}.classes must be a string")
    if "alias" in data and (
        not isinstance(data["alias"], str) or not data["alias"].strip()
    ):
        raise TypeError(f"{name}.alias must be a semantic style ID")

    required_metadata = {str(value) for value in schema["required_metadata"]}
    for field_name in required_metadata:
        if field_name not in data:
            raise ValueError(f"{name} must define {field_name}")
    intent = data.get("intent", "")
    if not isinstance(intent, str):
        raise TypeError(f"{name}.intent must be a string")
    if "intent" in required_metadata and not intent.strip():
        raise ValueError(f"{name}.intent must not be blank")

    surfaces = _string_list(data.get("surfaces", []), f"{name}.surfaces")
    allowed_surfaces = {str(value) for value in schema["surfaces"]}
    invalid_surfaces = sorted(set(surfaces) - allowed_surfaces)
    if invalid_surfaces:
        raise TypeError(f"{name}.surfaces must contain only server/frontend")
    if "surfaces" in required_metadata and not surfaces:
        raise ValueError(f"{name}.surfaces must not be empty")

    _string_list(data.get("markers", []), f"{name}.markers")
    _string_list(data.get("hooks", []), f"{name}.hooks")
    css = _string_list(data.get("css", []), f"{name}.css")
    if any("::" in item for item in css):
        raise ValueError(f"{name}.css must contain stylesheet paths, not path::hook")

    exceptions = data.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise TypeError(f"{name}.exceptions must be a list of records")
    exception_fields = {str(value) for value in schema["exception_fields"]}
    diagnostics = {str(value) for value in schema["exception_diagnostics"]}
    for item in exceptions:
        if not isinstance(item, dict) or set(item) != exception_fields:
            raise TypeError(
                f"{name}.exceptions must contain diagnostic/target/reason records"
            )
        if not all(isinstance(item[field], str) for field in exception_fields):
            raise TypeError(f"{name}.exceptions fields must be strings")
        if not item["target"].strip() or not item["reason"].strip():
            raise ValueError(f"{name}.exceptions target and reason must not be blank")
        if item["diagnostic"] not in diagnostics:
            raise ValueError(
                f"{name}.exceptions has unknown diagnostic {item['diagnostic']}"
            )
    return data


def flatten_style_definitions(
    data: object,
    prefix: str = "",
    *,
    schema: dict[str, object] | None = None,
) -> dict[str, StyleDefinition]:
    contract = schema or dict(FALLBACK_SCHEMA)
    records: dict[str, dict[str, object]] = {}
    id_pattern = re.compile(str(contract["id_segment_pattern"]))

    def collect(value: object, name: str) -> None:
        record = style_record(value, name or "styles", contract)
        if record is not None:
            if not name:
                raise ValueError("styles root cannot be a style record")
            records[name] = record
            return
        if not isinstance(value, dict):
            raise TypeError(
                f"{name or 'styles'} must be a mapping or typed style record, "
                f"got {type(value).__name__}"
            )
        for key, child_value in value.items():
            key_text = str(key)
            if not id_pattern.fullmatch(key_text):
                raise ValueError(
                    f"{name or 'styles'} has invalid style ID segment {key_text}"
                )
            child = f"{name}.{key_text}" if name else key_text
            collect(child_value, child)

    collect(data, prefix)
    definitions: dict[str, StyleDefinition] = {}

    def resolve(name: str, stack: tuple[str, ...] = ()) -> StyleDefinition:
        if name in definitions:
            return definitions[name]
        if name in stack:
            raise ValueError(f"style alias cycle: {' -> '.join((*stack, name))}")
        record = records.get(name)
        if record is None:
            raise ValueError(f"unknown style alias target: {name}")
        alias = str(record.get("alias", ""))
        if alias:
            target = resolve(alias, (*stack, name))
            classes = target.classes
            canonical = target.canonical
        else:
            classes = str(record["classes"])
            canonical = name
        definition = StyleDefinition(
            name=name,
            classes=classes,
            tokens=split_class_tokens(classes),
            alias=alias,
            canonical=canonical,
            intent=str(record.get("intent", "")),
            surfaces=list(record.get("surfaces", [])),
            markers=list(record.get("markers", [])),
            hooks=list(record.get("hooks", [])),
            css=list(record.get("css", [])),
            exceptions=[dict(item) for item in record.get("exceptions", [])],
        )
        definitions[name] = definition
        return definition

    for name in records:
        resolve(name)
    for definition in definitions.values():
        for exception in definition.exceptions:
            target_name = exception["target"]
            target = definitions.get(target_name)
            if target is None:
                raise ValueError(
                    f"{definition.name}.exceptions has unknown target {target_name}"
                )
            if target_name == definition.name:
                raise ValueError(
                    f"{definition.name}.exceptions cannot target the same style"
                )
            if (
                exception["diagnostic"] == "duplicate-style-value"
                and target.classes != definition.classes
            ):
                raise ValueError(
                    f"{definition.name}.exceptions targets {target_name} with different classes"
                )
    return definitions


def normalize_style_registry(
    data: object,
    prefix: str = "",
    *,
    schema: dict[str, object] | None = None,
) -> object:
    definitions = flatten_style_definitions(data, prefix, schema=schema)
    normalized: dict[str, object] = {}
    for name, definition in definitions.items():
        parts = name.split(".")
        target = normalized
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = definition.classes
    return normalized


def style_families(
    definitions: dict[str, StyleDefinition],
) -> dict[str, list[str]]:
    families: dict[str, list[str]] = defaultdict(list)
    for name in definitions:
        parts = name.split(".")
        for index in range(1, len(parts)):
            families[".".join(parts[:index])].append(name)
    return {name: sorted(children) for name, children in families.items()}


def load_style_definitions(
    repo_root: Path,
    styles_path: Path = DEFAULT_STYLES_PATH,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> dict[str, StyleDefinition]:
    path = styles_path if styles_path.is_absolute() else repo_root / styles_path
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    schema = load_registry_schema(repo_root, schema_path)
    return flatten_style_definitions(data, schema=schema)


def style_record_fingerprints(repo_root: Path) -> dict[str, str]:
    """Fingerprint each semantic record independently for test-result freshness."""
    fingerprints: dict[str, str] = {}
    for name, definition in load_style_definitions(repo_root).items():
        payload = {
            "alias": definition.alias,
            "canonical": definition.canonical,
            "classes": definition.classes,
            "intent": definition.intent,
            "surfaces": definition.surfaces,
            "markers": definition.markers,
            "hooks": definition.hooks,
            "css": definition.css,
            "exceptions": definition.exceptions,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        fingerprints[name] = hashlib.sha256(encoded).hexdigest()
    return fingerprints


__all__ = [
    "DEFAULT_ICONS_PATH",
    "DEFAULT_ICONS_SCHEMA_PATH",
    "DEFAULT_SCHEMA_PATH",
    "DEFAULT_STYLES_PATH",
    "StyleDefinition",
    "flatten_icon_definitions",
    "flatten_style_definitions",
    "load_registry_schema",
    "load_icons_schema",
    "load_style_definitions",
    "normalize_icon_registry",
    "normalize_style_registry",
    "split_class_tokens",
    "style_families",
    "style_record_fingerprints",
    "style_record",
]
