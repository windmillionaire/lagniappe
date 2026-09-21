"""Read-only import planning for validated portable archive records and bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .portable import (
    TEXT_REFERENCE_PREFIX,
    DecodedEntity,
    MissingReference,
    PortableIdentity,
    PortableReference,
    ValueCodec,
    canonical_json,
    parse_reference_string,
    portable_name,
    validate_child_record,
    validate_entity_record,
)
from .provider import DataLifecycleError
from .validation import validate_archive


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_import_planner_is_source_independent_and_resolves_two_pass_references
# @tests tests_tooling/test_008_data_lifecycle.py::test_history_and_messages_are_nested_and_replanned_under_their_owners
# @matrix portable-json : import-planner natural-identity owner-scoped-children two-pass-resolution
class ImportPlanner:
    """Prove a validated v1 bundle can be represented without mutating a target."""

    RECIPE = "lagniappe-target-key/v1"

    def __init__(self, *, target_prefix="", target_namespace="", reserved_keys=None):
        self.target_prefix = str(target_prefix)
        self.target_namespace = str(target_namespace)
        self.reserved_keys = dict(reserved_keys or {})

    def plan(self, records: Iterable[dict[str, Any]], assets=()):
        records = list(records)
        identities: dict[PortableIdentity, str] = {}
        ordinary = []
        messaging = []
        for record in records:
            identity = validate_entity_record(record)
            if identity in identities:
                raise DataLifecycleError(f"Duplicate portable identity: {identity}")
            reserved_role = record["identity"].get("reserved_role")
            if reserved_role:
                target_key = self.reserved_keys.get(reserved_role)
                if not target_key:
                    raise DataLifecycleError(f"Target reserved role is unavailable: {reserved_role}")
            elif identity.type == "message_conversation":
                messaging.append((identity, record))
                continue
            else:
                parent = self._planned_parent(record, identities)
                target_key = self._ordinary_key(identity, record["identity"]["kind_role"], parent)
            identities[identity] = target_key
            ordinary.append((identity, record))

        pending = list(messaging)
        while pending:
            deferred = []
            progress = False
            for identity, record in pending:
                try:
                    target_key = self._messaging_key(identity, record, identities)
                except KeyError:
                    deferred.append((identity, record))
                    continue
                identities[identity] = target_key
                ordinary.append((identity, record))
                progress = True
            if deferred and not progress:
                raise DataLifecycleError("Messaging identities have unresolved participants or ancestors.")
            pending = deferred

        planned = []
        codec = ValueCodec()
        for identity, record in ordinary:
            self._require_ancestors(record, identities)
            decoded = codec.decode(record["properties"])
            self._resolve(decoded, identities)
            self._resolve_portable(record["properties"], identities)
            planned.append(
                {
                    "identity": identity.as_dict(),
                    "target_key": identities[identity],
                    "properties": record["properties"],
                }
            )
            planned.extend(
                self._plan_children(record, identity, identities, identities[identity])
            )
        planned_assets = [self._plan_asset(asset) for asset in assets]
        return {
            "recipe": self.RECIPE,
            "entities": planned,
            "assets": planned_assets,
            "identity_count": len(planned),
        }

    def plan_bundle(self, path):
        """Read one standalone-validated directory or ZIP and prove representability."""
        validate_archive(path)
        path = Path(path)
        if path.is_dir():
            def read(relative):
                return (path / PurePosixPath(relative)).read_bytes()

            def close():
                return None
        else:
            import zipfile

            archive = zipfile.ZipFile(path, "r")
            read = archive.read
            close = archive.close
        try:
            catalog = json.loads(read("data/archive.json"))
            records = []
            for shard in catalog["shards"]:
                records.extend(json.loads(read(shard["path"])))
            result = self.plan(records)
            result["assets"] = [
                self._plan_descriptor(asset)
                for asset in catalog.get("assets") or []
                if asset.get("status") == "available"
            ]
            return result
        finally:
            close()

    def _ordinary_key(self, identity, kind_role, parent):
        seed = canonical_json(
            {
                "recipe": self.RECIPE,
                "namespace": self.target_namespace or identity.namespace,
                "kind": f"{self.target_prefix}{kind_role}",
                "type": identity.type,
                "id": identity.id,
                "parent": parent,
            }
        )
        identifier = f"portable-v1-{identity.type}-{hashlib.sha256(seed).hexdigest()[:32]}"
        return f"{parent + '/' if parent else ''}{self.target_prefix}{kind_role}:{identifier}"

    def _planned_parent(self, record, identities):
        ancestors = record["identity"].get("ancestors") or []
        if not ancestors:
            return ""
        reference = self._tag_identity(ancestors[-1])
        if reference not in identities:
            raise DataLifecycleError("Portable structural ancestor precedes or is missing from the plan.")
        return identities[reference]

    def _require_ancestors(self, record, identities):
        for tag in record["identity"].get("ancestors") or []:
            if self._tag_identity(tag) not in identities:
                raise DataLifecycleError("Portable structural ancestor is unresolved.")

    def _messaging_key(self, identity, record, identities):
        properties = record["properties"]
        participants = properties.get("participants") or []
        targets = sorted(identities[self._tag_identity(tag)] for tag in participants)
        if len(targets) != 2:
            raise DataLifecycleError("Conversation requires two target participants.")
        identifier = hashlib.sha256("\0".join(targets).encode()).hexdigest()
        return f"{self.target_prefix}message_conversations:{identifier}"

    def _plan_children(self, record, parent_identity, identities, parent_key):
        planned = []
        for child_type, children in sorted((record.get("children") or {}).items()):
            for child in children:
                child_key = validate_child_record(child_type, child)
                properties = child["properties"]
                self._resolve(ValueCodec().decode(properties), identities)
                self._resolve_portable(properties, identities)
                if child_type in {"task_history", "document_history"}:
                    suffix = (
                        f"id:{child_key['id']}"
                        if "id" in child_key
                        else f"name:{child_key['name']}"
                    )
                    target_key = f"{parent_key}/{self.target_prefix}history:{suffix}"
                else:
                    sender = identities[self._tag_identity(properties["sender"])]
                    operation_id = str(properties.get("operation_id") or "").strip()
                    if not operation_id:
                        raise DataLifecycleError(
                            "Portable message is missing its natural operation identity."
                        )
                    identifier = hashlib.sha256(
                        f"{sender}\0{operation_id}".encode()
                    ).hexdigest()
                    target_key = f"{parent_key}/{self.target_prefix}messages:{identifier}"
                planned.append(
                    {
                        "identity": {
                            "parent": parent_identity.as_dict(),
                            "type": child_type,
                            "key": child_key,
                        },
                        "target_key": target_key,
                        "properties": properties,
                    }
                )
        return planned

    def _resolve(self, value, identities):
        if isinstance(value, PortableReference):
            if value.identity() not in identities:
                raise DataLifecycleError(f"Required portable reference is unresolved: {value}")
            return
        if isinstance(value, MissingReference):
            return
        if isinstance(value, DecodedEntity):
            self._resolve(value.properties, identities)
            return
        if isinstance(value, list):
            for item in value:
                self._resolve(item, identities)
        elif isinstance(value, dict):
            for item in value.values():
                self._resolve(item, identities)

    def _resolve_portable(self, value, identities):
        if isinstance(value, str):
            if value.startswith(TEXT_REFERENCE_PREFIX):
                identity = parse_reference_string(value).identity()
                if identity not in identities:
                    raise DataLifecycleError(
                        f"Required portable string reference is unresolved: {identity}"
                    )
            elif value[:1] in {"{", "["}:
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    return
                self._resolve_portable(parsed, identities)
            return
        if isinstance(value, list):
            for item in value:
                self._resolve_portable(item, identities)
            return
        if not isinstance(value, dict):
            return
        if set(value) == {"$ref"}:
            identity = self._tag_identity(value)
            if identity not in identities:
                raise DataLifecycleError(f"Required portable reference is unresolved: {identity}")
            return
        if set(value) == {"$missing_ref"}:
            return
        for key, item in value.items():
            if isinstance(key, str) and key.startswith(TEXT_REFERENCE_PREFIX):
                identity = parse_reference_string(key).identity()
                if identity not in identities:
                    raise DataLifecycleError(
                        f"Required portable map-key reference is unresolved: {identity}"
                    )
            self._resolve_portable(item, identities)

    @staticmethod
    def _tag_identity(tag):
        if isinstance(tag, PortableReference):
            return tag.identity()
        if isinstance(tag, dict) and "$ref" in tag:
            tag = tag["$ref"]
        return PortableIdentity(
            str(tag.get("namespace") or ""), str(tag["type"]), str(tag["id"])
        )

    @staticmethod
    def _plan_asset(asset):
        path = Path(asset["local_path"])
        if not path.is_file():
            raise DataLifecycleError(f"Portable asset payload is missing: {path}")
        payload = path.read_bytes()
        if len(payload) != int(asset["size"]) or hashlib.sha256(payload).hexdigest() != asset["sha256"]:
            raise DataLifecycleError(f"Portable asset payload does not match its descriptor: {path}")
        return {
            "sha256": asset["sha256"],
            "target_path": f"portable/{asset['sha256']}/{portable_name(asset.get('name') or path.name)}",
        }

    @staticmethod
    def _plan_descriptor(asset):
        return {
            "sha256": asset["sha256"],
            "target_path": (
                f"portable/{asset['sha256']}/"
                f"{portable_name(asset.get('name') or PurePosixPath(asset['path']).name)}"
            ),
        }


__all__ = ["ImportPlanner"]
