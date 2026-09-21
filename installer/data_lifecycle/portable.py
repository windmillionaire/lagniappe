"""Normative key-free portable format, value codec, record validation, and sharding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import base64
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable, Iterable

from .provider import DataLifecycleError


PORTABLE_FORMAT = "lagniappe-portable"
PORTABLE_SCHEMA_VERSION = 1
MAX_SHARD_RECORDS = 1_000
MAX_SHARD_BYTES = 8 * 1024 * 1024
REFERENCE_COMPONENT = re.compile(r"\A[a-z0-9.~_-]{1,384}\Z")
TEXT_ESCAPE_PREFIX = "literal:"
TEXT_REFERENCE_PREFIX = "ref:"
PORTABLE_ID_PATTERN = re.compile(r"\A[a-z0-9][a-z0-9._-]{5,127}\Z")
PORTABLE_KIND_ROLES = {
    "users",
    "models",
    "instances",
    "files",
    "filters",
    "activity",
    "message_conversations",
}
PORTABLE_TYPE_ROLES = {
    "user": "users",
    "group": "models",
    "public_group": "models",
    "project": "models",
    "category": "models",
    "users": "models",
    "model": "models",
    "form": "models",
    "page": "instances",
    "task": "instances",
    "file": "files",
    "filter": "filters",
    "note": "activity",
    "report": "activity",
    "message_conversation": "message_conversations",
}
PORTABLE_CHILD_ROLES = {
    "page": {"document_history": "history"},
    "project": {"document_history": "history"},
    "task": {"task_history": "history"},
    "message_conversation": {"message": "messages"},
}


# @testable infrastructure
@dataclass(frozen=True, order=True)
class PortableIdentity:
    namespace: str
    type: str
    id: str

    def as_dict(self):
        return {"type": self.type, "id": self.id, "namespace": self.namespace}


# @testable infrastructure
@dataclass(frozen=True)
class PortableReference:
    type: str
    id: str
    namespace: str = ""

    def identity(self):
        return PortableIdentity(self.namespace, self.type, self.id)

    def as_tag(self):
        value = {"type": self.type, "id": self.id}
        if self.namespace:
            value["namespace"] = self.namespace
        return {"$ref": value}


# @testable infrastructure
@dataclass(frozen=True)
class MissingReference:
    type: str
    digest: str
    warning_id: str

    def as_tag(self):
        return {
            "$missing_ref": {
                "type": self.type,
                "digest": self.digest,
                "warning_id": self.warning_id,
            }
        }


# @testable infrastructure
@dataclass(frozen=True)
class DecodedEntity:
    properties: dict[str, Any]
    exclude_from_indexes: tuple[str, ...]


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_portable_names_and_reference_strings_are_lossless
# @matrix portable-json : path-safety reference-escaping
def portable_name(value: str) -> str:
    """Encode arbitrary display text as one collision-stable portable component."""
    value = str(value or "")
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise DataLifecycleError("Portable path component is empty or contains controls.")
    encoded = []
    for byte in value.encode("utf-8"):
        character = chr(byte)
        if character in "abcdefghijklmnopqrstuvwxyz0123456789._-":
            encoded.append(character)
        else:
            encoded.append(f"~{byte:02x}")
    result = "".join(encoded)
    if result in {".", ".."} or not result:
        raise DataLifecycleError("Portable path component is unsafe.")
    return result


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_portable_names_and_reference_strings_are_lossless
# @matrix portable-json : path-safety reference-escaping
def unportable_name(value: str) -> str:
    """Decode one component produced by :func:`portable_name`."""
    value = str(value or "")
    payload = bytearray()
    index = 0
    while index < len(value):
        if value[index] == "~":
            if index + 2 >= len(value):
                raise DataLifecycleError("Portable path component escape is incomplete.")
            try:
                payload.append(int(value[index + 1 : index + 3], 16))
            except ValueError as error:
                raise DataLifecycleError("Portable path component escape is invalid.") from error
            index += 3
        else:
            character = value[index]
            if character not in "abcdefghijklmnopqrstuvwxyz0123456789._-":
                raise DataLifecycleError("Portable path component contains an invalid byte.")
            payload.extend(character.encode("ascii"))
            index += 1
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DataLifecycleError("Portable path component is not valid UTF-8.") from error
    if portable_name(decoded) != value:
        raise DataLifecycleError("Portable path component is not canonical.")
    return decoded


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_portable_names_and_reference_strings_are_lossless
# @pair portable-json:reference-escaping
def reference_string(reference: PortableReference) -> str:
    parts = [TEXT_REFERENCE_PREFIX.removesuffix(":")]
    if reference.namespace:
        parts.append(portable_name(reference.namespace))
    parts.extend((portable_name(reference.type), portable_name(reference.id)))
    if not all(REFERENCE_COMPONENT.fullmatch(part) for part in parts[1:]):
        raise DataLifecycleError("Portable reference contains an invalid component.")
    return ":".join(parts)


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_portable_names_and_reference_strings_are_lossless
# @pair portable-json:reference-escaping
def parse_reference_string(value: str) -> PortableReference:
    """Parse one canonical typed reference string without accepting literals."""
    value = str(value or "")
    parts = value.split(":")
    if len(parts) not in {3, 4} or parts[0] != TEXT_REFERENCE_PREFIX.removesuffix(":"):
        raise DataLifecycleError("Portable reference string is invalid.")
    encoded = parts[1:]
    if not all(REFERENCE_COMPONENT.fullmatch(part) for part in encoded):
        raise DataLifecycleError("Portable reference string contains an invalid component.")
    decoded = [unportable_name(part) for part in encoded]
    if len(decoded) == 2:
        reference = PortableReference(decoded[0], decoded[1])
    else:
        reference = PortableReference(decoded[1], decoded[2], decoded[0])
    if reference_string(reference) != value:
        raise DataLifecycleError("Portable reference string is not canonical.")
    return reference


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_portable_names_and_reference_strings_are_lossless
# @pair portable-json:reference-escaping
def escape_reference_string(value: str) -> str:
    value = str(value)
    if value.startswith((TEXT_REFERENCE_PREFIX, TEXT_ESCAPE_PREFIX)):
        return f"{TEXT_ESCAPE_PREFIX}{value}"
    return value


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_portable_names_and_reference_strings_are_lossless
# @pair portable-json:reference-escaping
def unescape_reference_string(value: str) -> str:
    value = str(value)
    return value[len(TEXT_ESCAPE_PREFIX) :] if value.startswith(TEXT_ESCAPE_PREFIX) else value


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_value_codec_round_trips_every_supported_value
# @matrix portable-json : round-trip value-codec
class ValueCodec:
    """Canonical JSON codec for every supported Datastore value."""

    def __init__(
        self,
        *,
        reference_resolver: Callable[[Any], PortableReference | MissingReference] | None = None,
        string_normalizer: Callable[[str, tuple[Any, ...]], str | PortableReference | MissingReference] | None = None,
    ):
        self.reference_resolver = reference_resolver
        self.string_normalizer = string_normalizer

    def encode(self, value: Any, path=()):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise DataLifecycleError(f"Unsupported non-finite float at {self._path(path)}")
            return value
        if isinstance(value, str):
            normalized = self.string_normalizer(value, path) if self.string_normalizer else value
            if isinstance(normalized, PortableReference):
                return normalized.as_tag()
            if isinstance(normalized, MissingReference):
                return normalized.as_tag()
            return escape_reference_string(normalized)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise DataLifecycleError(f"Naive datetime is unsupported at {self._path(path)}")
            normalized = value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return {"$datetime": normalized}
        if isinstance(value, date):
            return {"$date": value.isoformat()}
        if isinstance(value, bytes):
            return {"$bytes": base64.b64encode(value).decode("ascii")}
        if isinstance(value, PortableReference):
            return value.as_tag()
        if isinstance(value, MissingReference):
            return value.as_tag()
        if isinstance(value, DecodedEntity):
            return {
                "$entity": {
                    "exclude_from_indexes": sorted(value.exclude_from_indexes),
                    "properties": self.encode(value.properties, (*path, "$entity")),
                }
            }
        if self._is_key(value):
            if self.reference_resolver is None:
                raise DataLifecycleError(f"Datastore Key requires a resolver at {self._path(path)}")
            resolved = self.reference_resolver(value)
            if not isinstance(resolved, (PortableReference, MissingReference)):
                raise DataLifecycleError(f"Key resolver returned an unsupported value at {self._path(path)}")
            return resolved.as_tag()
        if self._is_geopoint(value):
            return {
                "$geopoint": {
                    "latitude": float(value.latitude),
                    "longitude": float(value.longitude),
                }
            }
        if self._is_entity(value):
            exclusions = sorted(getattr(value, "exclude_from_indexes", ()) or ())
            return {
                "$entity": {
                    "exclude_from_indexes": exclusions,
                    "properties": self.encode(dict(value), (*path, "$entity")),
                }
            }
        if isinstance(value, (list, tuple)):
            return [self.encode(item, (*path, index)) for index, item in enumerate(value)]
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise DataLifecycleError(f"Non-string map key at {self._path(path)}")
            encoded = {}
            for key in sorted(value):
                normalized_key = self.string_normalizer(key, (*path, key)) if self.string_normalizer else key
                if isinstance(normalized_key, PortableReference):
                    normalized_key = reference_string(normalized_key)
                    generated_reference = True
                elif isinstance(normalized_key, MissingReference):
                    normalized_key = f"missing:{normalized_key.type}:{normalized_key.digest}"
                    generated_reference = True
                else:
                    generated_reference = False
                normalized_key = str(normalized_key)
                if not generated_reference:
                    normalized_key = escape_reference_string(normalized_key)
                if normalized_key in encoded:
                    raise DataLifecycleError(f"Map-key normalization collision at {self._path(path)}")
                encoded[normalized_key] = self.encode(value[key], (*path, key))
            return encoded
        raise DataLifecycleError(
            f"Unsupported {type(value).__name__} value at {self._path(path)}"
        )

    def decode(self, value: Any, path=()):
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return unescape_reference_string(value)
        if isinstance(value, list):
            return [self.decode(item, (*path, index)) for index, item in enumerate(value)]
        if not isinstance(value, dict):
            raise DataLifecycleError(f"Invalid portable value at {self._path(path)}")
        if "$datetime" in value and len(value) == 1:
            return datetime.fromisoformat(str(value["$datetime"]).replace("Z", "+00:00"))
        if "$date" in value and len(value) == 1:
            return date.fromisoformat(str(value["$date"]))
        if "$bytes" in value and len(value) == 1:
            try:
                return base64.b64decode(value["$bytes"], validate=True)
            except Exception as error:
                raise DataLifecycleError(f"Invalid base64 bytes at {self._path(path)}") from error
        if "$geopoint" in value and len(value) == 1:
            point = value["$geopoint"]
            try:
                from google.cloud.datastore.helpers import GeoPoint

                return GeoPoint(float(point["latitude"]), float(point["longitude"]))
            except (KeyError, TypeError, ValueError) as error:
                raise DataLifecycleError(f"Invalid GeoPoint at {self._path(path)}") from error
        if "$ref" in value and len(value) == 1:
            reference = value["$ref"]
            try:
                return PortableReference(
                    type=str(reference["type"]),
                    id=str(reference["id"]),
                    namespace=str(reference.get("namespace") or ""),
                )
            except (KeyError, TypeError) as error:
                raise DataLifecycleError(f"Invalid reference at {self._path(path)}") from error
        if "$missing_ref" in value and len(value) == 1:
            reference = value["$missing_ref"]
            try:
                return MissingReference(
                    type=str(reference["type"]),
                    digest=str(reference["digest"]),
                    warning_id=str(reference["warning_id"]),
                )
            except (KeyError, TypeError) as error:
                raise DataLifecycleError(f"Invalid missing reference at {self._path(path)}") from error
        if "$entity" in value and len(value) == 1:
            entity = value["$entity"]
            return DecodedEntity(
                properties=self.decode(entity.get("properties", {}), (*path, "$entity")),
                exclude_from_indexes=tuple(sorted(entity.get("exclude_from_indexes") or ())),
            )
        return {
            unescape_reference_string(key): self.decode(nested, (*path, key))
            for key, nested in value.items()
        }

    @staticmethod
    def _path(path):
        return ".".join(str(item) for item in path) or "<root>"

    @staticmethod
    def _is_key(value):
        return (
            type(value).__name__ == "Key"
            and hasattr(value, "flat_path")
            and hasattr(value, "to_legacy_urlsafe")
        )

    @staticmethod
    def _is_geopoint(value):
        return type(value).__name__ == "GeoPoint" and hasattr(value, "latitude") and hasattr(value, "longitude")

    @staticmethod
    def _is_entity(value):
        return (
            type(value).__name__ == "Entity"
            and hasattr(value, "exclude_from_indexes")
            and isinstance(value, dict)
        )


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_value_codec_round_trips_every_supported_value
# @pair portable-json:canonical-encoding
def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DataLifecycleError(f"Value is not canonical JSON: {error}") from error


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_shard_writer_enforces_count_bytes_and_ordering
# @matrix portable-json : deterministic-order sharding
class ShardWriter:
    """Stream sorted per-type JSON-array shards within both v1 limits."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def write_type(self, semantic_type: str, records: Iterable[dict[str, Any]]):
        safe_type = portable_name(semantic_type)
        directory = self.root / "data" / "entities" / safe_type
        directory.mkdir(parents=True, exist_ok=True)
        descriptors = []
        shard = []
        shard_size = 2

        def flush():
            nonlocal shard, shard_size
            if not shard:
                return
            number = len(descriptors) + 1
            relative = f"data/entities/{safe_type}/{number:06d}.json"
            payload = b"[" + b",".join(shard) + b"]"
            if len(payload) > MAX_SHARD_BYTES:
                raise DataLifecycleError("Portable entity shard exceeds 8 MiB.")
            target = self.root / PurePosixPath(relative)
            target.write_bytes(payload)
            descriptors.append(
                {
                    "path": relative,
                    "count": len(shard),
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            shard = []
            shard_size = 2

        prior_identity = None
        for record in records:
            validate_entity_record(record)
            identity = record["identity"]
            ordering = (identity["namespace"], identity["id"])
            if prior_identity is not None and ordering <= prior_identity:
                raise DataLifecycleError("Portable records are not strictly identity-sorted.")
            prior_identity = ordering
            encoded = canonical_json(record)
            if len(encoded) + 2 > MAX_SHARD_BYTES:
                raise DataLifecycleError("One portable entity cannot fit in an 8 MiB shard.")
            separator = 1 if shard else 0
            if shard and (
                len(shard) >= MAX_SHARD_RECORDS
                or shard_size + separator + len(encoded) > MAX_SHARD_BYTES
            ):
                flush()
            shard.append(encoded)
            shard_size += separator + len(encoded)
        flush()
        return descriptors


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_shard_writer_enforces_count_bytes_and_ordering
# @pair portable-json:entity-envelope
def validate_entity_record(record: dict[str, Any]) -> PortableIdentity:
    if not isinstance(record, dict) or set(record) - {
        "identity", "exclude_from_indexes", "properties", "children"
    } or not {"identity", "exclude_from_indexes", "properties"}.issubset(record):
        raise DataLifecycleError("Portable entity envelope is invalid.")
    identity = record["identity"]
    required = {"type", "id", "namespace", "kind_role", "ancestors"}
    if (
        not isinstance(identity, dict)
        or not required.issubset(identity)
        or set(identity) - {*required, "reserved_role"}
    ):
        raise DataLifecycleError("Portable entity identity is incomplete.")
    if (
        not isinstance(identity["type"], str)
        or not identity["type"]
        or not isinstance(identity["namespace"], str)
        or not isinstance(identity["id"], str)
        or not PORTABLE_ID_PATTERN.fullmatch(identity["id"])
        or identity["kind_role"] not in PORTABLE_KIND_ROLES
        or PORTABLE_TYPE_ROLES.get(identity["type"]) != identity["kind_role"]
    ):
        raise DataLifecycleError("Portable entity identity values are invalid.")
    if "reserved_role" in identity and not str(identity["reserved_role"] or "").strip():
        raise DataLifecycleError("Portable reserved role is invalid.")
    if not isinstance(identity["ancestors"], list):
        raise DataLifecycleError("Portable entity ancestors must be a list.")
    for ancestor in identity["ancestors"]:
        if not isinstance(ancestor, dict) or set(ancestor) != {"$ref"}:
            raise DataLifecycleError("Portable structural ancestor is invalid.")
        reference = ancestor["$ref"]
        if (
            not isinstance(reference, dict)
            or not {"type", "id"}.issubset(reference)
            or set(reference) - {"namespace", "type", "id"}
            or not str(reference.get("type") or "")
            or not PORTABLE_ID_PATTERN.fullmatch(str(reference.get("id") or ""))
        ):
            raise DataLifecycleError("Portable structural ancestor identity is invalid.")
    exclusions = record["exclude_from_indexes"]
    if (
        not isinstance(exclusions, list)
        or not all(isinstance(value, str) and value for value in exclusions)
        or exclusions != sorted(set(exclusions))
    ):
        raise DataLifecycleError("Portable index exclusions must be sorted and unique.")
    if not isinstance(record["properties"], dict):
        raise DataLifecycleError("Portable entity properties must be an object.")
    if (
        identity["type"] != "user"
        and "hash" in record["properties"]
        and record["properties"]["hash"] != identity["id"]
    ):
        raise DataLifecycleError("Portable stored hash disagrees with entity identity.")
    portable_identity = PortableIdentity(
        str(identity["namespace"]),
        str(identity["type"]),
        str(identity["id"]),
    )
    children = record.get("children") or {}
    if not isinstance(children, dict):
        raise DataLifecycleError("Portable entity children must be an object.")
    allowed_children = PORTABLE_CHILD_ROLES.get(portable_identity.type, {})
    if set(children) - set(allowed_children):
        raise DataLifecycleError("Portable entity has unsupported child collections.")
    for child_type, values in children.items():
        if not isinstance(values, list):
            raise DataLifecycleError("Portable child collection must be a list.")
        prior_key = None
        for child in values:
            child_key = validate_child_record(child_type, child)
            ordering = canonical_json(child_key)
            if prior_key is not None and ordering <= prior_key:
                raise DataLifecycleError("Portable children are not strictly key-sorted.")
            prior_key = ordering
    return portable_identity


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_history_and_messages_are_nested_and_replanned_under_their_owners
# @tests tests_tooling/test_008_data_lifecycle.py::test_archive_validation_counts_children_without_separate_identity_pages
# @matrix portable-archive portable-json : owner-scoped-children
def validate_child_record(child_type: str, child: dict[str, Any]) -> dict[str, Any]:
    """Validate one owner-scoped history or message row."""
    if child_type not in {
        "task_history",
        "document_history",
        "message",
    } or not isinstance(child, dict):
        raise DataLifecycleError("Portable child type is invalid.")
    if set(child) != {"key", "exclude_from_indexes", "properties"}:
        raise DataLifecycleError("Portable child envelope is invalid.")
    key = child["key"]
    if (
        not isinstance(key, dict)
        or len(key) != 1
        or set(key) not in ({"id"}, {"name"})
        or ("id" in key and (not isinstance(key["id"], int) or isinstance(key["id"], bool) or key["id"] <= 0))
        or ("name" in key and (not isinstance(key["name"], str) or not key["name"]))
    ):
        raise DataLifecycleError("Portable child key is invalid.")
    exclusions = child["exclude_from_indexes"]
    if (
        not isinstance(exclusions, list)
        or not all(isinstance(value, str) and value for value in exclusions)
        or exclusions != sorted(set(exclusions))
    ):
        raise DataLifecycleError("Portable child index exclusions are invalid.")
    if not isinstance(child["properties"], dict) or "hash" in child["properties"]:
        raise DataLifecycleError("Portable child properties are invalid.")
    return key


# @testable false
# @covered-by installer/data_lifecycle/archive.py::build_archive
# @reason the bundled schema is consumed and validated by the archive workflow
def load_schema() -> dict[str, Any]:
    path = Path(__file__).with_name("schema_v1.json")
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "DecodedEntity",
    "MAX_SHARD_BYTES",
    "MAX_SHARD_RECORDS",
    "MissingReference",
    "PORTABLE_FORMAT",
    "PORTABLE_SCHEMA_VERSION",
    "PortableIdentity",
    "PortableReference",
    "ShardWriter",
    "ValueCodec",
    "canonical_json",
    "escape_reference_string",
    "load_schema",
    "portable_name",
    "parse_reference_string",
    "reference_string",
    "unportable_name",
    "unescape_reference_string",
    "validate_child_record",
    "validate_entity_record",
]
