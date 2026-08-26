"""Generation-bound referenced-asset collection for portable archives."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import mimetypes
import os
from pathlib import Path, PurePosixPath
import posixpath
from urllib.parse import unquote, urlsplit

from .portable import portable_name
from .provider import DataLifecycleError
from .staging import normalize_text
from .state import ArchiveState, secure_directory


DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
GENERATION_RETRY_LIMIT = 3


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_asset_collection_is_generation_bound_resumable_and_deduplicated
# @matrix portable-archive : assets generation-binding resume
class AssetCollector:
    """Download only staged references and publish verified content-addressed bytes."""

    def __init__(self, state: ArchiveState, output_root, buckets, *, chunk_size=DOWNLOAD_CHUNK_BYTES):
        if state.connection is None:
            raise DataLifecycleError("Archive staging database is not open.")
        self.state = state
        self.output_root = secure_directory(output_root)
        self.buckets = dict(buckets)
        self.chunk_size = max(256 * 1024, int(chunk_size))
        self.started_at = None
        self.completed_at = None

    def collect(self):
        self.started_at = self._now()
        warnings = []
        rows = list(self.state.connection.execute("SELECT * FROM assets ORDER BY logical_id"))
        for row in rows:
            try:
                self._collect_one(row)
            except Exception as error:
                if row["required"]:
                    raise DataLifecycleError(
                        f"Required archive asset {row['logical_name']!r} is unavailable: {error}"
                    ) from error
                warning = {
                    "id": f"asset-{row['logical_id'][:12]}",
                    "code": "asset-unavailable",
                    "logical_id": row["logical_id"],
                    "message": str(error),
                }
                warnings.append(warning)
                self.state.connection.execute(
                    "UPDATE assets SET state='unavailable' WHERE logical_id=?",
                    (row["logical_id"],),
                )
                self.state.connection.execute(
                    "INSERT OR REPLACE INTO warnings(id, code, details) VALUES(?, ?, ?)",
                    (warning["id"], warning["code"], self._json(warning)),
                )
                self.state.connection.commit()
        self._normalize_canonical_documents()
        self.completed_at = self._now()
        return self.descriptors(), warnings

    def _collect_one(self, row):
        bucket = self.buckets.get(row["source_role"])
        if bucket is None:
            raise DataLifecycleError(f"Unknown source bucket role {row['source_role']!r}.")
        part_dir = secure_directory(self.output_root / ".parts")
        part = part_dir / f"{row['logical_id']}.part"
        for _attempt in range(GENERATION_RETRY_LIMIT):
            expected_generation = str(row["generation"] or "")
            try:
                blob = bucket.blob(
                    row["source_path"],
                    generation=(int(expected_generation) if expected_generation else None),
                )
            except TypeError:
                blob = bucket.blob(row["source_path"])
            blob.reload()
            generation = str(blob.generation or "")
            size = int(blob.size or 0)
            if not generation or size < 0:
                raise DataLifecycleError("Provider asset metadata is incomplete.")
            if expected_generation and expected_generation != generation:
                raise DataLifecycleError(
                    "Referenced asset generation is no longer available."
                )
            self.state.connection.execute(
                "UPDATE assets SET generation=?, media_type=?, size=?, state='downloading' WHERE logical_id=?",
                (generation, blob.content_type, size, row["logical_id"]),
            )
            self.state.connection.commit()
            offset = part.stat().st_size if part.exists() else 0
            if offset > size:
                part.unlink(missing_ok=True)
                offset = 0
            try:
                with part.open("ab") as output:
                    if os.name != "nt":
                        os.chmod(part, 0o600)
                    while offset < size:
                        end = min(offset + self.chunk_size, size) - 1
                        payload = blob.download_as_bytes(
                            start=offset,
                            end=end,
                            if_generation_match=int(generation),
                            checksum=None,
                        )
                        if not payload:
                            raise DataLifecycleError("Asset range download returned no bytes.")
                        output.write(payload)
                        output.flush()
                        os.fsync(output.fileno())
                        offset += len(payload)
            except Exception:
                part.unlink(missing_ok=True)
                continue
            if part.stat().st_size != size:
                part.unlink(missing_ok=True)
                continue
            media_type = str(blob.content_type or mimetypes.guess_type(row["logical_name"])[0] or "application/octet-stream")
            if media_type.startswith("text/") or media_type in {
                "application/json",
                "application/javascript",
                "application/xml",
            }:
                try:
                    normalized = normalize_text(self.state, part.read_text(encoding="utf-8"))
                except UnicodeDecodeError as error:
                    raise DataLifecycleError("Textual archive asset is not UTF-8.") from error
                part.write_text(normalized, encoding="utf-8", newline="\n")
            archive_size = part.stat().st_size
            payload_digest = self._sha256_file(part)
            safe_name = portable_name(row["logical_name"])
            existing = self.state.connection.execute(
                "SELECT local_path FROM assets WHERE state='available' AND sha256=? LIMIT 1",
                (payload_digest,),
            ).fetchone()
            relative = PurePosixPath(existing["local_path"]) if existing else PurePosixPath(
                "assets", "sha256", payload_digest[:2], payload_digest, safe_name
            )
            target = self.output_root / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target.exists():
                if self._sha256_file(target) != payload_digest:
                    raise DataLifecycleError("Content-addressed asset collision detected.")
                part.unlink(missing_ok=True)
            else:
                os.replace(part, target)
                if os.name != "nt":
                    os.chmod(target, 0o600)
            canonical_path = None
            if row["asset_type"] == "html" and row["logical_name"] == "document":
                owner_digest = hashlib.sha256(row["owner"].encode("utf-8")).hexdigest()
                owner = self._owner(row)
                canonical_relative = PurePosixPath(
                    "data",
                    "documents",
                    portable_name(owner["type"]),
                    owner_digest,
                    f"{portable_name(row['logical_name'])}.html",
                )
                canonical_target = self.output_root / canonical_relative
                canonical_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                canonical_target.write_bytes(target.read_bytes())
                if os.name != "nt":
                    os.chmod(canonical_target, 0o600)
                canonical_path = canonical_relative.as_posix()
            self.state.connection.execute(
                "UPDATE assets SET state='available', generation=?, media_type=?, size=?, sha256=?, local_path=? "
                "WHERE logical_id=?",
                (generation, media_type, archive_size, payload_digest, relative.as_posix(), row["logical_id"]),
            )
            self.state.connection.execute(
                "DELETE FROM warnings WHERE id=?",
                (f"asset-{row['logical_id'][:12]}",),
            )
            if canonical_path:
                self.state.set_metadata(f"canonical:{row['logical_id']}", canonical_path)
            else:
                self.state.connection.commit()
            return
        raise DataLifecycleError("Asset changed or failed throughout the bounded generation retry policy.")

    def descriptors(self):
        descriptors = []
        for row in self.state.connection.execute("SELECT * FROM assets ORDER BY logical_id"):
            descriptor = {
                "logical_id": row["logical_id"],
                "entity": self._owner(row),
                "name": row["logical_name"],
                "type": row["asset_type"],
                "status": row["state"],
            }
            if row["state"] == "available":
                descriptor.update(
                    {
                        "generation": row["generation"],
                        "media_type": row["media_type"],
                        "size": row["size"],
                        "sha256": row["sha256"],
                        "path": row["local_path"],
                    }
                )
                canonical = self.state.get_metadata(f"canonical:{row['logical_id']}")
                if canonical:
                    descriptor["canonical_document"] = canonical
            else:
                descriptor["warning_id"] = f"asset-{row['logical_id'][:12]}"
            descriptors.append(descriptor)
        return descriptors

    def _normalize_canonical_documents(self):
        from installer.package_install import install_if_missing

        install_if_missing(
            "bs4",
            "HTML parser for portable archive documents",
            package_name="beautifulsoup4",
        )
        from bs4 import BeautifulSoup

        documents = list(
            self.state.connection.execute(
                "SELECT * FROM assets WHERE state='available' AND asset_type='html' "
                "AND logical_name='document' ORDER BY logical_id"
            )
        )
        for document in documents:
            canonical_path = self.state.get_metadata(
                f"canonical:{document['logical_id']}"
            )
            if not canonical_path:
                raise DataLifecycleError("Available canonical document has no portable payload.")
            canonical = self.output_root / PurePosixPath(canonical_path)
            soup = BeautifulSoup(canonical.read_text(encoding="utf-8"), "html.parser")
            rows = list(
                self.state.connection.execute(
                    "SELECT * FROM assets WHERE owner=?",
                    (document["owner"],),
                )
            )
            aliases = {}
            path_aliases = {}
            for row in rows:
                if row["state"] == "available":
                    replacement = posixpath.relpath(
                        row["local_path"], posixpath.dirname(canonical_path)
                    )
                else:
                    replacement = f"missing-asset:asset-{row['logical_id'][:12]}"
                source_path = str(row["source_path"] or "").lstrip("/")
                if source_path:
                    path_aliases[source_path] = replacement
                for alias in {
                    source_path,
                    f"/{source_path}",
                    str(row["logical_name"] or ""),
                    str(row["logical_id"] or ""),
                }:
                    if alias:
                        aliases[alias] = replacement
                bucket = self.buckets.get(row["source_role"])
                bucket_name = str(getattr(bucket, "name", "") or "")
                if bucket_name and source_path:
                    aliases[f"gs://{bucket_name}/{source_path}"] = replacement
                    aliases[f"https://storage.googleapis.com/{bucket_name}/{source_path}"] = replacement
            for tag in soup.find_all(True):
                for attribute in ("href", "src", "poster"):
                    raw = str(tag.attrs.get(attribute) or "").strip()
                    if not raw:
                        continue
                    replacement = aliases.get(raw)
                    if replacement is None:
                        parsed_path = unquote(urlsplit(raw).path).lstrip("/")
                        replacement = next(
                            (
                                target
                                for source, target in path_aliases.items()
                                if parsed_path.endswith(source)
                            ),
                            None,
                        )
                    if replacement is not None:
                        tag.attrs[attribute] = replacement
            canonical.write_text(str(soup), encoding="utf-8", newline="\n")

    @staticmethod
    def _owner(row):
        import json

        try:
            owner = json.loads(row["owner"])
        except (json.JSONDecodeError, TypeError) as error:
            raise DataLifecycleError("Portable asset owner is malformed.") from error
        if not isinstance(owner, dict):
            raise DataLifecycleError("Portable asset owner must be an object.")
        return owner

    @staticmethod
    def _sha256_file(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _json(value):
        import json

        return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = ["AssetCollector", "DOWNLOAD_CHUNK_BYTES", "GENERATION_RETRY_LIMIT"]
