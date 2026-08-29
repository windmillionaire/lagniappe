"""Exact entity inventory and generation-bound asset capture for recovery sets."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import posixpath

from config.datastore import encode_urlsafe_key

from .portable import PortableReference, ValueCodec, canonical_json
from .provider import BACKUP_ROOT_PREFIX, DataLifecycleError
from .staging import _namespaces, _physical_kinds, _query_pages


COPY_CHUNK_BYTES = 8 * 1024 * 1024


# @testable false
# @covered-by installer/data_lifecycle/recovery_set.py::inventory_database
# @reason timestamp canonicalization is exercised by exact inventory generation
def _timestamp(value):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# @testable false
# @covered-by installer/data_lifecycle/recovery_set.py::inventory_database
# @reason named scratch keys are canonicalized during public inventory generation
def _canonical_key(key, source_database_id):
    if source_database_id == "(default)":
        return key
    from google.cloud.datastore import Key

    return Key(
        *key.flat_path,
        project=key.project,
        namespace=key.namespace,
    )


# @testable false
# @covered-by installer/data_lifecycle/recovery_set.py::inventory_database
# @reason reference canonicalization is part of the entity inventory digest
def _key_reference(key, source_database_id="(default)"):
    key = _canonical_key(key, source_database_id)
    return PortableReference(
        "datastore-key",
        encode_urlsafe_key(key),
        str(getattr(key, "namespace", None) or ""),
    )


# @testable false
# @covered-by installer/data_lifecycle/recovery_set.py::inventory_database
# @reason canonical entity hashing is validated through deterministic inventories
def _entity_digest(entity, source_database_id):
    codec = ValueCodec(
        reference_resolver=lambda key: _key_reference(key, source_database_id)
    )
    canonical_key = _canonical_key(entity.key, source_database_id)
    payload = {
        "key": encode_urlsafe_key(canonical_key),
        "exclude_from_indexes": sorted(
            getattr(entity, "exclude_from_indexes", ()) or ()
        ),
        "properties": codec.encode(dict(entity)),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


# @testable false
# @covered-by installer/data_lifecycle/recovery_set.py::inventory_database
# @reason descriptor extraction and validation are inventory responsibilities
def _asset_definitions(entity, source_database_id):
    canonical_owner = encode_urlsafe_key(
        _canonical_key(entity.key, source_database_id)
    )
    raw = entity.get("assets")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DataLifecycleError(
                f"Asset metadata is malformed for {canonical_owner}."
            ) from error
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise DataLifecycleError(
            f"Asset metadata is not an object for {canonical_owner}."
        )
    definitions = []
    for name, definition in sorted(raw.items()):
        if not isinstance(definition, dict) or not definition.get("path"):
            raise DataLifecycleError(
                f"Asset descriptor is incomplete for {canonical_owner}:{name}."
            )
        definitions.append(
            {
                "owner": canonical_owner,
                "name": str(name),
                "role": str(definition.get("visibility") or "private"),
                "path": str(definition["path"]),
                "generation": str(definition.get("generation") or ""),
                "required": True,
            }
        )

    if str(entity.key.kind).endswith("site") and entity.key.id_or_name == "image":
        generations = entity.get("asset_generations") or {}
        if not isinstance(generations, dict):
            raise DataLifecycleError("Site-image generation metadata is malformed.")
        for name, path in sorted(entity.items()):
            if name in {"version", "asset_generations"} or not isinstance(path, str):
                continue
            definitions.append(
                {
                    "owner": canonical_owner,
                    "name": str(name),
                    "role": "public",
                    "path": path,
                    "generation": str(generations.get(name) or ""),
                    "required": True,
                }
            )
    return definitions


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_recovery_inventory_uses_one_read_time_and_requires_asset_generations
# @tests tests_tooling/test_008_data_lifecycle.py::test_recovery_inventory_includes_uploaded_file_asset_generations
# @matrix data-lifecycle disaster-recovery file : asset-generation inventory point-in-time uploaded-file
def inventory_database(
    client,
    *,
    snapshot_time,
    page_size=250,
    source_database_id="(default)",
    point_in_time_read=True,
):
    """Read every namespace/kind at one PITR timestamp."""
    if not isinstance(snapshot_time, datetime) or snapshot_time.tzinfo is None:
        raise DataLifecycleError("Recovery inventory requires a timezone-aware read time.")
    entities = []
    assets = {}
    read_time = snapshot_time if point_in_time_read else None
    for namespace in _namespaces(client, read_time=read_time):
        for kind in _physical_kinds(client, namespace, read_time=read_time):
            query = client.query(kind=kind, namespace=namespace or None)
            for page in _query_pages(
                query,
                page_size=page_size,
                read_time=read_time,
            ):
                for entity in page:
                    key = encode_urlsafe_key(
                        _canonical_key(entity.key, source_database_id)
                    )
                    entities.append(
                        {
                            "key": key,
                            "kind": str(kind),
                            "namespace": str(namespace),
                            "type": str(entity.get("type") or entity.get("kind") or ""),
                            "created": _timestamp(entity.get("created")),
                            "sha256": _entity_digest(entity, source_database_id),
                        }
                    )
                    for definition in _asset_definitions(entity, source_database_id):
                        if definition["role"] not in {"private", "public", "history"}:
                            raise DataLifecycleError(
                                f"Asset bucket role is invalid for {key}:{definition['name']}."
                            )
                        if not definition["generation"]:
                            raise DataLifecycleError(
                                f"Referenced asset generation is missing for {key}:{definition['name']}."
                            )
                        identity = (
                            definition["role"],
                            definition["path"],
                            definition["generation"],
                        )
                        existing = assets.get(identity)
                        if existing:
                            existing["owners"].append(
                                {"key": key, "name": definition["name"]}
                            )
                        else:
                            assets[identity] = {
                                "role": definition["role"],
                                "path": definition["path"],
                                "generation": definition["generation"],
                                "owners": [{"key": key, "name": definition["name"]}],
                            }
    entities.sort(key=lambda item: item["key"])
    captured_assets = sorted(
        assets.values(),
        key=lambda item: (item["role"], item["path"], item["generation"]),
    )
    return {
        "snapshot_time": _timestamp(snapshot_time),
        "entity_count": len(entities),
        "entities": entities,
    }, captured_assets


# @testable false
# @covered-by installer/data_lifecycle/recovery_set.py::capture_assets
# @reason bounded generation-matched hashing is exercised by immutable asset capture
def _blob_sha256(blob, size):
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        end = min(offset + COPY_CHUNK_BYTES, size) - 1
        chunk = blob.download_as_bytes(
            start=offset,
            end=end,
            if_generation_match=int(blob.generation),
            checksum=None,
        )
        if not chunk:
            raise DataLifecycleError("Asset checksum read returned no bytes.")
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_capture_recovery_assets_copies_exact_generation_create_only
# @matrix data-lifecycle storage : asset-generation checksum immutable-copy
def capture_assets(
    context,
    backup_id,
    assets,
    runtime_buckets,
    *,
    progress=None,
):
    """Copy exact referenced generations into the recovery-set prefix."""
    captured = []
    total = len(assets)
    for current, asset in enumerate(assets, 1):
        if progress is not None:
            progress(current, total)
        source_bucket = runtime_buckets.get(asset["role"])
        if source_bucket is None:
            raise DataLifecycleError(f"Unknown runtime asset role {asset['role']!r}.")
        try:
            source = source_bucket.blob(
                asset["path"], generation=int(asset["generation"])
            )
        except TypeError:
            source = source_bucket.blob(asset["path"])
        source.reload()
        if str(source.generation or "") != asset["generation"]:
            raise DataLifecycleError(
                f"Referenced generation is unavailable for {asset['role']}:{asset['path']}."
            )
        size = int(source.size or 0)
        digest = _blob_sha256(source, size) if size else hashlib.sha256(b"").hexdigest()
        identity = hashlib.sha256(
            canonical_json(
                {
                    "role": asset["role"],
                    "path": asset["path"],
                    "generation": asset["generation"],
                }
            )
        ).hexdigest()
        basename = posixpath.basename(asset["path"]) or "asset"
        destination_name = (
            f"{BACKUP_ROOT_PREFIX}/{backup_id}/assets/{identity[:2]}/{identity}/{basename}"
        )
        destination = context.bucket.blob(destination_name)
        if not destination.exists():
            copied = source_bucket.copy_blob(
                source,
                context.bucket,
                destination_name,
                if_generation_match=0,
            )
            destination = copied or context.bucket.blob(destination_name)
        destination.reload()
        destination_size = int(destination.size or 0)
        destination_digest = (
            _blob_sha256(destination, destination_size)
            if destination_size
            else hashlib.sha256(b"").hexdigest()
        )
        if destination_size != size or destination_digest != digest:
            raise DataLifecycleError(
                f"Recovery asset copy conflicts for {asset['role']}:{asset['path']}."
            )
        captured.append(
            {
                **asset,
                "size": size,
                "sha256": digest,
                "recovery_object": destination_name,
                "recovery_generation": str(destination.generation or ""),
            }
        )
    return captured


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason canonical catalog bytes are owned by immutable backup publication
def catalog_bytes(payload):
    return canonical_json(payload)


# @testable false
# @covered-by installer/data_lifecycle/backup.py::create_backup
# @reason catalog checksum descriptors are owned by immutable backup publication
def catalog_descriptor(uri, payload):
    encoded = catalog_bytes(payload)
    return {
        "uri": uri,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": encoded,
    }


__all__ = [
    "capture_assets",
    "catalog_bytes",
    "catalog_descriptor",
    "inventory_database",
]
