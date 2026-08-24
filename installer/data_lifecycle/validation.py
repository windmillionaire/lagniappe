"""Standalone structural, relationship, security, checksum, and key audits."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from config.datastore import decode_urlsafe_key

from .portable import (
    MAX_SHARD_BYTES,
    MAX_SHARD_RECORDS,
    PORTABLE_FORMAT,
    PORTABLE_SCHEMA_VERSION,
    PortableIdentity,
    canonical_json,
    parse_reference_string,
    portable_name,
    validate_entity_record,
)
from .provider import DataLifecycleError, validate_backup_id


TEXT_MEDIA_PREFIXES = ("text/",)
TEXT_MEDIA_TYPES = {
    "application/json",
    "application/javascript",
    "application/schema+json",
}
TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")
OUTBOUND_PATTERN = re.compile(
    rb"(?i)(?:href|src|action)\s*=\s*['\"]\s*(?:[a-z][a-z0-9+.-]*:|//)"
)


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason parser callbacks are exercised by complete offline-link validation
class _ArchiveLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, _tag, attrs):
        for name, value in attrs:
            if name.casefold() in {"href", "src"} and value:
                self.links.append(value)


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason link traversal is one phase of complete offline archive validation
def _validate_html_links(reader, paths):
    available = set(paths)
    for page in sorted(path for path in available if path.startswith("site/") and path.endswith(".html")):
        try:
            text = reader.read(page).decode("utf-8")
        except UnicodeDecodeError as error:
            raise DataLifecycleError(f"Offline HTML is not UTF-8: {page}") from error
        parser = _ArchiveLinkParser()
        parser.feed(text)
        base = PurePosixPath(page).parent
        for raw in parser.links:
            link = str(raw).split("#", 1)[0].split("?", 1)[0]
            if not link:
                continue
            if ":" in link.split("/", 1)[0] or link.startswith(("/", "\\", "//")):
                raise DataLifecycleError(f"Offline HTML contains an outbound or absolute link: {page}")
            combined = PurePosixPath(os.path.normpath((base / link).as_posix()).replace("\\", "/"))
            target = _safe_path(combined.as_posix())
            if target not in available:
                raise DataLifecycleError(f"Offline HTML link target is missing: {page} -> {raw}")


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason path containment is enforced throughout the public validator
def _safe_path(value: str) -> str:
    value = str(value or "")
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DataLifecycleError(f"Unsafe archive path: {value!r}")
    return path.as_posix()


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason directory access is an internal archive-reader implementation
class _DirectoryReader:
    def __init__(self, path):
        self.root = Path(path)

    def paths(self):
        values = []
        for path in self.root.rglob("*"):
            if path.is_symlink():
                raise DataLifecycleError(f"Archive contains a symlink: {path}")
            if path.is_dir():
                continue
            if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
                raise DataLifecycleError(f"Archive contains a non-regular entry: {path}")
            values.append(path.relative_to(self.root).as_posix())
        return values

    def read(self, path):
        target = self.root.joinpath(*PurePosixPath(_safe_path(path)).parts)
        if target.is_symlink() or not target.is_file():
            raise DataLifecycleError(f"Archive file is missing: {path}")
        return target.read_bytes()


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason ZIP access is an internal archive-reader implementation
class _ZipReader:
    def __init__(self, path):
        self.archive = zipfile.ZipFile(path, "r")
        self.infos = self.archive.infolist()
        if not self.infos or self.infos[-1].filename != "manifest.json":
            raise DataLifecycleError("ZIP completion manifest must be its final entry.")

    def paths(self):
        values = []
        seen = set()
        for info in self.infos:
            path = _safe_path(info.filename)
            if path in seen:
                raise DataLifecycleError(f"ZIP contains duplicate entry: {path}")
            seen.add(path)
            if info.is_dir():
                continue
            mode = info.external_attr >> 16
            if mode and not stat.S_ISREG(mode):
                raise DataLifecycleError(f"ZIP contains a non-regular entry: {path}")
            if info.flag_bits & 0x1:
                raise DataLifecycleError("Encrypted ZIP archives are not supported.")
            values.append(path)
        return values

    def read(self, path):
        try:
            return self.archive.read(_safe_path(path))
        except KeyError as error:
            raise DataLifecycleError(f"Archive file is missing: {path}") from error

    def close(self):
        self.archive.close()


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason archive-container selection is exercised by directory and ZIP validation
def _reader(path):
    path = Path(path)
    if path.is_dir():
        return _DirectoryReader(path)
    if path.is_file() and zipfile.is_zipfile(path):
        return _ZipReader(path)
    raise DataLifecycleError("Archive path must be a directory bundle or ZIP file.")


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason strict JSON loading is an internal validation phase
def _json(reader, path):
    try:
        return json.loads(reader.read(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DataLifecycleError(f"Archive JSON is invalid: {path}") from error


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason recursive reference discovery is exercised by relationship validation
def _walk_refs(value):
    if isinstance(value, str):
        if value.startswith("ref:"):
            yield parse_reference_string(value).identity()
        elif value[:1] in {"{", "["}:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return
            yield from _walk_refs(parsed)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_refs(item)
    elif isinstance(value, dict):
        if "$ref" in value:
            if len(value) != 1:
                raise DataLifecycleError("Portable reference tag has sibling fields.")
            reference = value["$ref"]
            if not isinstance(reference, dict) or not {"type", "id"}.issubset(reference):
                raise DataLifecycleError("Portable reference tag is malformed.")
            if set(reference) - {"namespace", "type", "id"}:
                raise DataLifecycleError("Portable reference tag has unsupported fields.")
            identity = PortableIdentity(
                str(reference.get("namespace") or ""),
                str(reference.get("type") or ""),
                str(reference.get("id") or ""),
            )
            if not identity.type or not identity.id:
                raise DataLifecycleError("Portable reference identity is incomplete.")
            yield identity
        else:
            for key, item in value.items():
                if isinstance(key, str) and key.startswith("ref:"):
                    yield parse_reference_string(key).identity()
                yield from _walk_refs(item)


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason placeholder traversal is exercised by warning-agreement validation
def _walk_missing_refs(value):
    if isinstance(value, str):
        match = re.fullmatch(r"missing:([^:]+):([0-9a-f]{64})", value)
        if match:
            yield f"missing-{match.group(2)[:12]}"
        elif value[:1] in {"{", "["}:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return
            yield from _walk_missing_refs(parsed)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_missing_refs(item)
    elif isinstance(value, dict):
        if "$missing_ref" in value:
            if len(value) != 1:
                raise DataLifecycleError("Portable missing-reference marker has sibling fields.")
            missing = value["$missing_ref"]
            if (
                not isinstance(missing, dict)
                or set(missing) != {"type", "digest", "warning_id"}
                or not str(missing.get("type") or "")
                or not re.fullmatch(r"[0-9a-f]{64}", str(missing.get("digest") or ""))
                or not str(missing.get("warning_id") or "")
            ):
                raise DataLifecycleError("Portable missing-reference marker is malformed.")
            yield str(missing["warning_id"])
        else:
            for item in value.values():
                yield from _walk_missing_refs(item)


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason token discovery is exercised by the exhaustive public key audit
def _key_audit(path, payload):
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return
    for token in TOKEN_PATTERN.findall(text):
        try:
            decode_urlsafe_key(token)
        except Exception:
            continue
        raise DataLifecycleError(f"Textual archive file contains a Datastore key token: {path}")


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_archive_validation_rejects_traversal_extra_files_bad_checksums_and_keys
# @tests tests_tooling/test_008_data_lifecycle.py::test_archive_validation_accepts_canonical_directory_and_zip
# @tests tests_tooling/test_008_data_lifecycle.py::test_archive_validation_counts_children_without_separate_identity_pages
# @pairs portable-archive:validation portable-archive:path-safety portable-archive:key-audit portable-archive:owner-scoped-children
def validate_archive(path) -> dict:
    """Validate a complete directory/ZIP bundle without provider access."""
    reader = _reader(path)
    try:
        actual_paths = reader.paths()
        folded = {}
        for raw in actual_paths:
            safe = _safe_path(raw)
            collision = folded.get(safe.casefold())
            if collision and collision != safe:
                raise DataLifecycleError(f"Archive paths collide case-insensitively: {collision}, {safe}")
            folded[safe.casefold()] = safe
        if "manifest.json" not in actual_paths:
            raise DataLifecycleError("Archive completion manifest is missing.")
        manifest = _json(reader, "manifest.json")
        if (
            manifest.get("format") != PORTABLE_FORMAT
            or manifest.get("schema_version") != PORTABLE_SCHEMA_VERSION
            or manifest.get("status") != "complete"
        ):
            raise DataLifecycleError("Archive completion manifest is invalid.")
        declared_items = manifest.get("files")
        if not isinstance(declared_items, list):
            raise DataLifecycleError("Archive manifest file inventory is invalid.")
        declared = {}
        for item in declared_items:
            if not isinstance(item, dict):
                raise DataLifecycleError("Archive manifest file descriptor is invalid.")
            file_path = _safe_path(item.get("path"))
            if file_path == "manifest.json" or file_path in declared:
                raise DataLifecycleError(f"Archive manifest declares an invalid duplicate: {file_path}")
            declared[file_path] = item
        if set(actual_paths) != {*declared, "manifest.json"}:
            extra = sorted(set(actual_paths) - {*declared, "manifest.json"})
            missing = sorted(set(declared) - set(actual_paths))
            raise DataLifecycleError(f"Archive file inventory mismatch (extra={extra}, missing={missing}).")
        for file_path, descriptor in declared.items():
            payload = reader.read(file_path)
            if len(payload) != descriptor.get("size"):
                raise DataLifecycleError(f"Archive size mismatch: {file_path}")
            if hashlib.sha256(payload).hexdigest() != descriptor.get("sha256"):
                raise DataLifecycleError(f"Archive checksum mismatch: {file_path}")
            media_type = str(descriptor.get("media_type") or "")
            if media_type.startswith(TEXT_MEDIA_PREFIXES) or media_type in TEXT_MEDIA_TYPES:
                _key_audit(file_path, payload)
            if file_path.startswith("site/") and file_path.endswith((".html", ".js")):
                if OUTBOUND_PATTERN.search(payload):
                    raise DataLifecycleError(f"Offline site contains an outbound or active URL: {file_path}")
        _validate_html_links(reader, actual_paths)
        _key_audit("manifest.json", reader.read("manifest.json"))

        catalog = _json(reader, "data/archive.json")
        schema = _json(reader, "data/schema.json")
        if catalog.get("format") != PORTABLE_FORMAT or catalog.get("schema_version") != PORTABLE_SCHEMA_VERSION:
            raise DataLifecycleError("Portable catalog version is invalid.")
        required_catalog_fields = {
            "format",
            "schema_version",
            "archive_id",
            "source_backup_id",
            "source_application_version",
            "export_consistency",
            "created_at",
            "asset_collection",
            "warnings",
            "feature_flags",
            "shards",
            "type_counts",
            "assets",
        }
        if not required_catalog_fields.issubset(catalog):
            raise DataLifecycleError("Portable catalog is incomplete.")
        validate_backup_id(catalog["archive_id"])
        validate_backup_id(catalog["source_backup_id"])
        if catalog["archive_id"] != catalog["source_backup_id"]:
            raise DataLifecycleError("Portable archive and source backup IDs disagree.")
        if (
            manifest.get("archive_id") != catalog["archive_id"]
            or manifest.get("source_backup_id") != catalog["source_backup_id"]
            or manifest.get("created_at") != catalog["created_at"]
            or manifest.get("export_consistency") != catalog["export_consistency"]
            or manifest.get("asset_collection") != catalog["asset_collection"]
        ):
            raise DataLifecycleError("Portable catalog and completion manifest disagree.")
        if catalog["export_consistency"] != "point-in-time":
            raise DataLifecycleError("Portable catalog consistency contract is invalid.")
        collection = catalog["asset_collection"]
        if (
            not isinstance(collection, dict)
            or set(collection) != {"started_at", "completed_at", "consistency"}
            or collection.get("consistency") != "recovery-set-generations"
        ):
            raise DataLifecycleError("Portable asset collection window is invalid.")
        if schema.get("$id") != "https://lagniappe.app/schema/portable-v1.json":
            raise DataLifecycleError("Portable machine schema identity is invalid.")
        forbidden_catalog_fields = {
            "project_id",
            "source_project",
            "database_id",
            "source_database_id",
            "bucket",
            "bucket_name",
            "object_path",
            "operation_name",
            "credentials",
        }
        if forbidden_catalog_fields.intersection(catalog):
            raise DataLifecycleError("Portable catalog contains provider-bound fields.")
        if manifest.get("catalog_sha256") != hashlib.sha256(reader.read("data/archive.json")).hexdigest():
            raise DataLifecycleError("Archive catalog checksum does not match the manifest.")
        if manifest.get("schema_sha256") != hashlib.sha256(reader.read("data/schema.json")).hexdigest():
            raise DataLifecycleError("Archive schema checksum does not match the manifest.")

        identities = set()
        child_owners = set()
        records = []
        missing_reference_warnings = set()
        type_counts = {}
        shard_paths = set()
        prior_type = None
        prior_number = 0
        for shard in catalog.get("shards") or []:
            if not isinstance(shard, dict) or set(shard) != {
                "type", "path", "count", "bytes", "sha256"
            }:
                raise DataLifecycleError("Portable shard descriptor is invalid.")
            shard_path = _safe_path(shard.get("path"))
            if shard_path in shard_paths or shard_path not in declared:
                raise DataLifecycleError(f"Portable shard path is duplicate or undeclared: {shard_path}")
            shard_paths.add(shard_path)
            shard_type = str(shard.get("type") or "")
            match = re.fullmatch(r"data/entities/([^/]+)/(\d{6})\.json", shard_path)
            if not match or not shard_type:
                raise DataLifecycleError(f"Portable shard naming is invalid: {shard_path}")
            current_number = int(match.group(2))
            if shard_type != prior_type:
                if prior_type is not None and shard_type <= prior_type:
                    raise DataLifecycleError("Portable shard types are not strictly sorted.")
                prior_type = shard_type
                prior_number = 0
            if current_number != prior_number + 1:
                raise DataLifecycleError(f"Portable shard numbering is not contiguous: {shard_path}")
            prior_number = current_number
            payload = reader.read(shard_path)
            if len(payload) > MAX_SHARD_BYTES or len(payload) != shard.get("bytes"):
                raise DataLifecycleError(f"Portable shard size is invalid: {shard_path}")
            if hashlib.sha256(payload).hexdigest() != shard.get("sha256"):
                raise DataLifecycleError(f"Portable shard checksum is invalid: {shard_path}")
            shard_records = _json(reader, shard_path)
            if not isinstance(shard_records, list) or not 1 <= len(shard_records) <= MAX_SHARD_RECORDS:
                raise DataLifecycleError(f"Portable shard record count is invalid: {shard_path}")
            if len(shard_records) != shard.get("count") or canonical_json(shard_records) != payload:
                raise DataLifecycleError(f"Portable shard is not canonical: {shard_path}")
            prior = None
            for record in shard_records:
                identity = validate_entity_record(record)
                if identity.type != shard_type:
                    raise DataLifecycleError(f"Portable record type disagrees with its shard: {shard_path}")
                if identity in identities:
                    raise DataLifecycleError(f"Duplicate portable identity: {identity}")
                current = (identity.namespace, identity.id)
                if prior is not None and current <= prior:
                    raise DataLifecycleError(f"Portable shard ordering is invalid: {shard_path}")
                prior = current
                identities.add(identity)
                records.append(record)
                missing_reference_warnings.update(
                    _walk_missing_refs(record["properties"])
                )
                type_counts[identity.type] = type_counts.get(identity.type, 0) + 1
                for child_type, children in (record.get("children") or {}).items():
                    for child in children:
                        owner = canonical_json(
                            {
                                "type": child_type,
                                "parent": identity.as_dict(),
                                "key": child["key"],
                            }
                        )
                        if owner in child_owners:
                            raise DataLifecycleError("Duplicate portable child identity.")
                        child_owners.add(owner)
                        type_counts[child_type] = type_counts.get(child_type, 0) + 1
                        missing_reference_warnings.update(
                            _walk_missing_refs(child["properties"])
                        )
        if type_counts != catalog.get("type_counts"):
            raise DataLifecycleError("Portable catalog type counts are invalid.")
        for identity in identities:
            page_path = (
                f"site/{portable_name(identity.type)}/"
                f"{portable_name(identity.id)}/index.html"
            )
            if page_path not in declared:
                raise DataLifecycleError(f"Portable entity presentation page is missing: {identity}")
        if "site/index.html" not in declared or "site/search-index.js" not in declared:
            raise DataLifecycleError("Offline archive index or search data is missing.")
        for record in records:
            for ancestor in record["identity"].get("ancestors") or []:
                references = list(_walk_refs(ancestor))
                if len(references) != 1 or references[0] not in identities:
                    raise DataLifecycleError("Portable entity has an unresolved structural ancestor.")
            for reference in _walk_refs(record["properties"]):
                if reference not in identities:
                    raise DataLifecycleError(f"Portable entity has an unresolved required reference: {reference}")
            for children in (record.get("children") or {}).values():
                for child in children:
                    for reference in _walk_refs(child["properties"]):
                        if reference not in identities:
                            raise DataLifecycleError(
                                f"Portable child has an unresolved required reference: {reference}"
                            )
        assets = {item.get("logical_id"): item for item in catalog.get("assets") or []}
        if None in assets or len(assets) != len(catalog.get("assets") or []):
            raise DataLifecycleError("Portable asset descriptors are duplicated or invalid.")
        for asset in assets.values():
            entity = asset.get("entity") or {}
            if "parent" in entity:
                owner = canonical_json(entity)
                if owner not in child_owners:
                    raise DataLifecycleError("Portable child asset owner is unresolved.")
            else:
                asset_identity = PortableIdentity(
                    str(entity.get("namespace") or ""),
                    str(entity.get("type") or ""),
                    str(entity.get("id") or ""),
                )
                if asset_identity not in identities:
                    raise DataLifecycleError("Portable asset owner identity is unresolved.")
            if asset.get("status") == "available":
                asset_path = _safe_path(asset.get("path"))
                if asset_path not in declared:
                    raise DataLifecycleError(f"Portable asset path is undeclared: {asset_path}")
                payload = reader.read(asset_path)
                if len(payload) != asset.get("size") or hashlib.sha256(payload).hexdigest() != asset.get("sha256"):
                    raise DataLifecycleError(f"Portable asset payload is invalid: {asset_path}")
                media_type = str(asset.get("media_type") or "")
                if media_type.startswith(TEXT_MEDIA_PREFIXES) or media_type in TEXT_MEDIA_TYPES:
                    _key_audit(asset_path, payload)
                canonical = asset.get("canonical_document")
                if canonical:
                    canonical = _safe_path(canonical)
                    if canonical not in declared:
                        raise DataLifecycleError(f"Canonical document is undeclared: {canonical}")
            elif asset.get("status") != "unavailable" or not asset.get("warning_id"):
                raise DataLifecycleError("Unavailable asset has no warning marker.")
        catalog_warnings = catalog.get("warnings") or []
        manifest_warnings = manifest.get("warnings") or []
        warning_ids = {
            str(item.get("id") or "") for item in catalog_warnings
            if isinstance(item, dict)
        }
        manifest_warning_ids = {
            str(item.get("id") or "") for item in manifest_warnings
            if isinstance(item, dict)
        }
        if len(warning_ids) != len(catalog_warnings) or len(manifest_warning_ids) != len(manifest_warnings):
            raise DataLifecycleError("Portable warning inventories contain duplicates or malformed rows.")
        if not warning_ids or "" in warning_ids:
            if catalog.get("warnings"):
                raise DataLifecycleError("Portable warnings are malformed.")
        if warning_ids != manifest_warning_ids:
            raise DataLifecycleError("Archive warning inventories disagree.")
        if not missing_reference_warnings.issubset(warning_ids):
            raise DataLifecycleError("Missing-reference warning is absent from the catalog.")
        for asset in assets.values():
            if asset.get("status") != "available" and asset.get("warning_id") not in warning_ids:
                raise DataLifecycleError("Unavailable asset warning is absent from the catalog.")
        counts = manifest.get("counts") or {}
        expected_counts = {
            "entities": len(identities) + len(child_owners),
            "shards": len(shard_paths),
            "assets": len(assets),
            "pages": len([path for path in actual_paths if path.startswith("site/") and path.endswith(".html")]),
            "warnings": len(warning_ids),
        }
        if any(counts.get(name) != value for name, value in expected_counts.items()):
            raise DataLifecycleError("Archive manifest counts do not match its contents.")
        if not manifest.get("key_audit_passed"):
            raise DataLifecycleError("Archive manifest does not record the exhaustive key audit.")
        return {
            "status": manifest.get("archive_status"),
            "archive_id": manifest.get("archive_id"),
            "entities": len(identities) + len(child_owners),
            "files": len(declared),
        }
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()


# @testable false
# @covered-by installer/data_lifecycle/validation.py::validate_archive
# @reason descriptors are produced by archive publication and consumed by validation
def file_descriptor(path: Path, root: Path):
    relative = path.relative_to(root).as_posix()
    payload = path.read_bytes()
    media_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
    return {
        "path": _safe_path(relative),
        "size": len(payload),
        "media_type": media_type,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


__all__ = ["file_descriptor", "validate_archive"]
