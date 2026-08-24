"""Temporary-database scans and bounded raw archive staging."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import pickle
import re
from typing import Any

from google.cloud.datastore import Key
from config.datastore import encode_urlsafe_key

from .portable import (
    MissingReference,
    PortableIdentity,
    PortableReference,
    ValueCodec,
    canonical_json,
    escape_reference_string,
    reference_string,
)
from .provider import DataLifecycleError, validate_database_id
from .state import ArchiveState


SCAN_PAGE_SIZE = 250
INCLUDED_TYPES = {
    "users": {"user"},
    "models": {"group", "public_group", "project", "category", "users", "model", "form"},
    "instances": {"page", "task"},
    "files": {"file"},
    "filters": {"filter"},
    "history": {"task_history"},
    "activity": {"note", "report"},
    "message_conversations": {"message_conversation"},
    "messages": {"message"},
}
NESTED_TYPES = {"task_history", "message"}
KEY_IDENTIFIED_TYPES = {*NESTED_TYPES, "message_conversation"}
HASH_PATTERN = re.compile(r"\A[a-z0-9]{6,128}\Z")


# @testable false
# @covered-by installer/data_lifecycle/staging.py::stage_database
# @reason provider pagination adapter is exercised by the bounded staging contract
def _query_pages(query, *, page_size=SCAN_PAGE_SIZE, read_time=None):
    cursor = None
    while True:
        options = {"limit": page_size, "start_cursor": cursor}
        if read_time is not None:
            options["read_time"] = read_time
        iterator = query.fetch(**options)
        pages = iterator.pages
        try:
            page = next(pages)
        except StopIteration:
            return
        rows = list(page)
        if not rows:
            return
        yield rows
        cursor = iterator.next_page_token
        if not cursor or len(rows) < page_size:
            return


# @testable false
# @covered-by installer/data_lifecycle/staging.py::stage_database
# @reason namespace discovery is exercised through multi-namespace staging
def _namespaces(client, *, read_time=None) -> list[str]:
    values = {""}
    query = client.query(kind="__namespace__")
    query.keys_only()
    for page in _query_pages(query, read_time=read_time):
        for row in page:
            value = row.key.id_or_name
            if value not in (None, 1):
                values.add(str(value))
    return sorted(values)


# @testable false
# @covered-by installer/data_lifecycle/staging.py::stage_database
# @reason physical-kind discovery is exercised through excluded-kind warnings
def _physical_kinds(client, namespace: str, *, read_time=None) -> list[str]:
    values = set()
    query = client.query(kind="__kind__", namespace=namespace or None)
    query.keys_only()
    for page in _query_pages(query, read_time=read_time):
        for row in page:
            if row.key.id_or_name:
                values.add(str(row.key.id_or_name))
    return sorted(values)


# @testable false
# @covered-by installer/data_lifecycle/staging.py::stage_database
# @reason source-key serialization is private staging state only
def _urlsafe(key) -> str:
    return encode_urlsafe_key(key)


# @testable false
# @covered-by installer/data_lifecycle/staging.py::portable_records
# @reason source-key normalization is exercised by recursive key replacement
def _source_key(key, project_id: str, database_id: str):
    return Key(
        *key.flat_path,
        project=project_id,
        database=database_id,
        namespace=key.namespace,
    )


# @testable false
# @covered-by installer/data_lifecycle/staging.py::stage_database
# @reason partition-free IDs are exercised by nested-history and messaging staging
def _partitionless_id(key) -> str:
    """Return a deterministic opaque ID without project or database partition data."""
    parts = []
    path = list(key.flat_path)
    for index in range(0, len(path), 2):
        identifier = path[index + 1]
        parts.append(
            {
                "kind": str(path[index]),
                "id": identifier if isinstance(identifier, int) else None,
                "name": identifier if isinstance(identifier, str) else None,
            }
        )
    payload = canonical_json({"namespace": key.namespace or "", "path": parts})
    return f"key-{hashlib.sha256(payload).hexdigest()}"


# @testable false
# @covered-by installer/data_lifecycle/staging.py::portable_records
# @reason typed child-key tails are exercised through owner-scoped portable records
def _child_key(key) -> dict[str, Any]:
    identifier = key.id_or_name
    if isinstance(identifier, int) and not isinstance(identifier, bool):
        return {"id": identifier}
    if isinstance(identifier, str) and identifier:
        return {"name": identifier}
    raise DataLifecycleError("Portable child has an incomplete Datastore key.")


# @testable false
# @covered-by installer/data_lifecycle/staging.py::portable_records
# @reason natural conversation IDs are exercised through owner-scoped portable records
def _normalize_conversation_ids(state: ArchiveState) -> None:
    """Derive conversation IDs from portable participant identities, not source keys."""
    rows = list(
        state.connection.execute(
            "SELECT source_key, portable_id, raw FROM entities "
            "WHERE status='included' AND semantic_type='message_conversation'"
        )
    )
    for row in rows:
        entity = pickle.loads(row["raw"])
        participants = []
        for participant in entity.get("participants") or []:
            mapped = state.connection.execute(
                "SELECT namespace, semantic_type, portable_id, availability FROM key_map "
                "WHERE encoding=?",
                (_urlsafe(participant),),
            ).fetchone()
            if mapped is None or mapped["availability"] != "available" or mapped["semantic_type"] != "user":
                raise DataLifecycleError("Conversation participant has no portable user identity.")
            participants.append(
                PortableIdentity(
                    mapped["namespace"], mapped["semantic_type"], mapped["portable_id"]
                ).as_dict()
            )
        if len(participants) != 2:
            raise DataLifecycleError("Conversation requires exactly two portable participants.")
        participants.sort(key=canonical_json)
        portable_id = f"conversation-{hashlib.sha256(canonical_json(participants)).hexdigest()}"
        state.connection.execute(
            "UPDATE entities SET portable_id=? WHERE source_key=?",
            (portable_id, row["source_key"]),
        )
        state.connection.execute(
            "UPDATE key_map SET portable_id=? "
            "WHERE semantic_type='message_conversation' AND portable_id=?",
            (portable_id, row["portable_id"]),
        )


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_staging_selects_durable_types_and_builds_typed_identity_map
# @pairs portable-json:entity-selection portable-json:portable-identity portable-json:bounded-scan
def stage_database(
    client,
    state: ArchiveState,
    *,
    source_project: str,
    source_database: str,
    prefix: str = "",
    page_size: int = SCAN_PAGE_SIZE,
) -> dict[str, Any]:
    """Scan known physical kinds in bounded pages and commit each page to SQLite."""
    if state.connection is None:
        raise DataLifecycleError("Archive staging database is not open.")
    source_database = validate_database_id(source_database)
    counts = Counter()
    known_physical = {f"{prefix}{role}": role for role in INCLUDED_TYPES}
    for namespace in _namespaces(client):
        for physical_kind in _physical_kinds(client, namespace):
            if physical_kind not in known_physical:
                query = client.query(kind=physical_kind, namespace=namespace or None)
                for page in _query_pages(query, page_size=page_size):
                    counts[f"unknown-kind:{physical_kind}"] += len(page)
        for physical_kind, role in sorted(known_physical.items()):
            query = client.query(kind=physical_kind, namespace=namespace or None)
            for page in _query_pages(query, page_size=page_size):
                with state.transaction() as connection:
                    for entity in page:
                        semantic_type = str(
                            entity.get("type")
                            or entity.get("kind")
                            or ("user" if role == "users" else "")
                        ).strip()
                        included = semantic_type in INCLUDED_TYPES[role]
                        scratch_encoding = _urlsafe(entity.key)
                        source_encoding = _urlsafe(
                            _source_key(entity.key, source_project, source_database)
                        )
                        stored_hash = str(entity.get("hash") or "").strip()
                        portable_id = stored_hash
                        if not portable_id and included and semantic_type in KEY_IDENTIFIED_TYPES:
                            portable_id = _partitionless_id(entity.key)
                        if stored_hash and not HASH_PATTERN.fullmatch(stored_hash):
                            included = False
                            counts[f"invalid-hash:{semantic_type or role}"] += 1
                        status = "included" if included and portable_id else "excluded"
                        if included and not portable_id:
                            status = "required-missing"
                            counts[f"missing-hash:{semantic_type}"] += 1
                        elif not included:
                            counts[f"excluded-type:{semantic_type or '<missing>'}"] += 1
                        existing = connection.execute(
                            "SELECT 1 FROM entities WHERE source_key=?",
                            (source_encoding,),
                        ).fetchone()
                        if existing:
                            continue
                        try:
                            connection.execute(
                                "INSERT INTO entities(source_key, scratch_key, namespace, semantic_type, "
                                "portable_id, kind_role, raw, status) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    source_encoding,
                                    scratch_encoding,
                                    namespace,
                                    semantic_type or None,
                                    portable_id or None,
                                    role,
                                    pickle.dumps(entity, protocol=5),
                                    status,
                                ),
                            )
                        except Exception as error:
                            raise DataLifecycleError(
                                f"Duplicate source or typed archive identity while staging {semantic_type or role}."
                            ) from error
                        availability = (
                            "available" if status == "included" else status
                        )
                        expected_type = semantic_type or role
                        encodings = {scratch_encoding, source_encoding}
                        for encoding in encodings:
                            connection.execute(
                                "INSERT INTO key_map(encoding, namespace, semantic_type, portable_id, availability) "
                                "VALUES(?, ?, ?, ?, ?)",
                                (
                                    encoding,
                                    namespace,
                                    expected_type,
                                    portable_id or "",
                                    "nested" if status == "included" and semantic_type in NESTED_TYPES else availability,
                                ),
                            )
                        counts[status] += 1
    _normalize_conversation_ids(state)
    for key, count in sorted(counts.items()):
        if key.startswith(("unknown-kind:", "excluded-type:", "missing-hash:", "invalid-hash:")):
            warning_id = hashlib.sha256(key.encode()).hexdigest()[:12]
            state.connection.execute(
                "INSERT OR REPLACE INTO warnings(id, code, details) VALUES(?, ?, ?)",
                (warning_id, key.split(":", 1)[0], json.dumps({"category": key, "count": count}, sort_keys=True)),
            )
    state.connection.commit()
    state.set_metadata("scan_counts", dict(sorted(counts.items())))
    return dict(counts)


# @testable false
# @covered-by installer/data_lifecycle/staging.py::portable_records
# @reason staged key-map lookup is exercised through portable record conversion
class _Resolver:
    def __init__(self, state: ArchiveState):
        self.state = state
        self.known = {}
        for row in state.connection.execute(
            "SELECT encoding, namespace, semantic_type, portable_id, availability FROM key_map"
        ):
            self.known[row["encoding"]] = row

    def key(self, key) -> PortableReference | MissingReference:
        return self.encoding(_urlsafe(key))

    def encoding(self, value: str) -> PortableReference | MissingReference:
        row = self.known.get(value)
        if row is None:
            digest = hashlib.sha256(value.encode()).hexdigest()
            missing = MissingReference("unknown", digest, f"missing-{digest[:12]}")
            self._warn_missing(missing, "unknown")
            return missing
        if row["availability"] == "available":
            return PortableReference(
                row["semantic_type"], row["portable_id"], row["namespace"]
            )
        if row["availability"] == "nested":
            raise DataLifecycleError(
                f"Nested {row['semantic_type']} cannot be referenced as a top-level entity."
            )
        if row["availability"] == "required-missing":
            raise DataLifecycleError(
                f"Included {row['semantic_type']} is missing its required portable identity."
            )
        digest = hashlib.sha256(value.encode()).hexdigest()
        missing = MissingReference(
            row["semantic_type"], digest, f"missing-{digest[:12]}"
        )
        self._warn_missing(missing, row["availability"])
        return missing

    def _warn_missing(self, missing, availability):
        self.state.connection.execute(
            "INSERT OR IGNORE INTO warnings(id, code, details) VALUES(?, ?, ?)",
            (
                missing.warning_id,
                "missing-reference",
                json.dumps(
                    {
                        "type": missing.type,
                        "digest": missing.digest,
                        "availability": availability,
                    },
                    sort_keys=True,
                ),
            ),
        )

    def string(self, value: str, _path):
        if value in self.known:
            return self.encoding(value)
        if value[:1] in {"{", "["}:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                pass
            else:
                return canonical_json(self._json_contract(parsed)).decode("utf-8")
        return self._replace_text(value)

    def _replace_text(self, value, *, escape_literal=False):
        transformed = str(value)
        replaced = False
        for encoding in sorted(self.known, key=len, reverse=True):
            if encoding not in transformed:
                continue
            resolved = self.encoding(encoding)
            replacement = (
                reference_string(resolved)
                if isinstance(resolved, PortableReference)
                else f"missing:{resolved.type}:{resolved.digest}"
            )
            transformed = transformed.replace(encoding, replacement)
            replaced = True
        if escape_literal and not replaced:
            return escape_reference_string(transformed)
        return transformed

    def _json_contract(self, value):
        if isinstance(value, str):
            return self._replace_text(value, escape_literal=True)
        if isinstance(value, list):
            return [self._json_contract(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized = self._replace_text(key, escape_literal=True)
                if normalized in result:
                    raise DataLifecycleError("Portable JSON map-key normalization collision.")
                result[normalized] = self._json_contract(item)
            return result
        return value


# @testable false
# @covered-by installer/data_lifecycle/staging.py::portable_records
# @reason structural ancestor conversion is part of portable record assembly
def _ancestor_references(key, resolver):
    ancestors = []
    parent = key.parent
    lineage = []
    while parent is not None:
        lineage.append(parent)
        parent = parent.parent
    for ancestor in reversed(lineage):
        resolved = resolver.key(ancestor)
        if not isinstance(resolved, PortableReference):
            raise DataLifecycleError("Structural ancestor is excluded or unavailable.")
        ancestors.append(resolved.as_tag())
    return ancestors


# @testable false
# @covered-by installer/data_lifecycle/staging.py::portable_records
# @reason asset tag normalization is part of portable record assembly
def _asset_tags(state, owner, raw_assets):
    if not raw_assets:
        return {}
    if isinstance(raw_assets, str):
        try:
            raw_assets = json.loads(raw_assets)
        except json.JSONDecodeError as error:
            raise DataLifecycleError(f"Asset metadata is malformed for {owner}") from error
    if not isinstance(raw_assets, dict):
        raise DataLifecycleError(f"Asset metadata is not an object for {owner}")
    result = {}
    for name, definition in sorted(raw_assets.items()):
        if not isinstance(definition, dict) or not definition.get("path"):
            raise DataLifecycleError(f"Asset descriptor is incomplete for {owner}:{name}")
        logical_source = canonical_json({"owner": owner, "name": name})
        logical_id = hashlib.sha256(logical_source).hexdigest()
        role = str(definition.get("visibility") or "private")
        if role not in {"private", "public", "history"}:
            raise DataLifecycleError(f"Asset bucket role is invalid for {owner}:{name}")
        state.connection.execute(
            "INSERT OR IGNORE INTO assets(logical_id, state, owner, "
            "logical_name, asset_type, required, source_role, source_path, generation, media_type, size) "
            "VALUES(?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                logical_id,
                canonical_json(owner).decode("utf-8"),
                str(name),
                str(definition.get("type") or "file"),
                int(str(name) == "document" and str(definition.get("type")) == "html"),
                role,
                str(definition["path"]),
                str(definition.get("generation") or "") or None,
                definition.get("content_type"),
                definition.get("size"),
            ),
        )
        result[name] = {
            "$asset": {
                "logical_id": logical_id,
                "name": str(name),
                "type": str(definition.get("type") or "file"),
            }
        }
    return result


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_staging_selects_durable_types_and_builds_typed_identity_map
# @tests tests_tooling/test_008_data_lifecycle.py::test_staging_replaces_source_and_scratch_keys_recursively
# @tests tests_tooling/test_008_data_lifecycle.py::test_history_and_messages_are_nested_and_replanned_under_their_owners
# @pairs portable-json:entity-envelope portable-json:key-replacement portable-json:typed-references portable-json:owner-scoped-children portable-json:natural-identity
def portable_records(state: ArchiveState) -> list[dict[str, Any]]:
    """Build top-level records with task history and messages nested under owners."""
    if state.connection is None:
        raise DataLifecycleError("Archive staging database is not open.")
    resolver = _Resolver(state)
    codec = ValueCodec(reference_resolver=resolver.key, string_normalizer=resolver.string)
    records = []
    by_identity = {}
    rows = list(state.connection.execute(
        "SELECT * FROM entities WHERE status='included' "
        "ORDER BY semantic_type, namespace, portable_id"
    ))
    for row in (value for value in rows if value["semantic_type"] not in NESTED_TYPES):
        entity = pickle.loads(row["raw"])
        identity = PortableIdentity(row["namespace"], row["semantic_type"], row["portable_id"])
        properties = dict(entity)
        if "hash" in properties and properties["hash"] != identity.id:
            raise DataLifecycleError(f"Stored hash disagrees with portable identity: {identity}")
        raw_assets = properties.pop("assets", None)
        owner = identity.as_dict()
        if raw_assets:
            properties["assets"] = _asset_tags(state, owner, raw_assets)
        envelope_identity = {
            "type": identity.type,
            "id": identity.id,
            "namespace": identity.namespace,
            "kind_role": row["kind_role"],
            "ancestors": _ancestor_references(entity.key, resolver),
        }
        if entity.get("reserved"):
            reserved_role = str(entity.get("type") or entity.get("kind") or "").strip()
            if not reserved_role:
                raise DataLifecycleError(f"Reserved entity has no role: {identity}")
            envelope_identity["reserved_role"] = reserved_role
        record = {
            "identity": envelope_identity,
            "exclude_from_indexes": sorted(
                getattr(entity, "exclude_from_indexes", ()) or ()
            ),
            "properties": codec.encode(properties, (identity.type, identity.id)),
        }
        records.append(record)
        by_identity[identity] = record

    for row in (value for value in rows if value["semantic_type"] in NESTED_TYPES):
        entity = pickle.loads(row["raw"])
        parent = resolver.key(entity.key.parent)
        if not isinstance(parent, PortableReference):
            raise DataLifecycleError("Portable child has no included structural parent.")
        expected_parent = "task" if row["semantic_type"] == "task_history" else "message_conversation"
        if parent.type != expected_parent:
            raise DataLifecycleError(
                f"Portable {row['semantic_type']} has an invalid {parent.type} parent."
            )
        parent_record = by_identity.get(parent.identity())
        if parent_record is None:
            raise DataLifecycleError("Portable child parent record is unavailable.")
        key = _child_key(entity.key)
        properties = dict(entity)
        if properties.pop("hash", None):
            raise DataLifecycleError("Portable child rows must not carry archive-only hashes.")
        owner = {
            "type": row["semantic_type"],
            "parent": parent.identity().as_dict(),
            "key": key,
        }
        raw_assets = properties.pop("assets", None)
        if raw_assets:
            properties["assets"] = _asset_tags(state, owner, raw_assets)
        child = {
            "key": key,
            "exclude_from_indexes": sorted(
                getattr(entity, "exclude_from_indexes", ()) or ()
            ),
            "properties": codec.encode(
                properties,
                (parent.type, parent.id, row["semantic_type"], canonical_json(key).decode()),
            ),
        }
        parent_record.setdefault("children", {}).setdefault(row["semantic_type"], []).append(child)

    for record in records:
        for children in (record.get("children") or {}).values():
            children.sort(key=lambda child: canonical_json(child["key"]))
    state.connection.commit()
    return sorted(
        records,
        key=lambda record: (
            record["identity"]["type"],
            record["identity"]["namespace"],
            record["identity"]["id"],
        ),
    )


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_staging_replaces_source_and_scratch_keys_recursively
# @pair portable-json:key-replacement
def normalize_text(state: ArchiveState, value: str) -> str:
    """Replace every known source/scratch key token in one textual payload."""
    return str(_Resolver(state).string(str(value), ("text",)))


__all__ = [
    "INCLUDED_TYPES",
    "NESTED_TYPES",
    "SCAN_PAGE_SIZE",
    "normalize_text",
    "portable_records",
    "stage_database",
]
