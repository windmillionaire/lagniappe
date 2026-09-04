"""Descriptor-safe local-file opening and resumable Google Storage uploads."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import stat
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

import httpx

from .errors import AdapterError, FileBoundaryError, TransportError
from .limits import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_STRUCTURED_RESULT_BYTES,
    MAX_UPLOAD_CHUNK_BYTES,
    MAX_UPLOAD_CHUNKS_PER_FILE,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_FILE_BYTES,
    MAX_UPLOAD_RECOVERY_ATTEMPTS,
    MAX_UPLOAD_STATUS_PROBES,
    MAX_UPLOAD_TOTAL_BYTES,
    MIN_UPLOAD_CHUNK_BYTES,
    UPLOAD_OPERATION_TIMEOUT_SECONDS,
    UPLOAD_TIMEOUT_SECONDS,
)
from .url_security import quote_path_segment, validate_storage_url


_DIRECTORY_FLAGS = (
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
_READ_BLOCK_BYTES = 64 * 1024
_UPLOAD_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
class _RESTLike(Protocol):
    storage_client: httpx.AsyncClient

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
    async def request_json(
        self,
        method: str,
        target: str,
        *,
        body: Any = None,
        max_bytes: int = MAX_STRUCTURED_RESULT_BYTES,
    ) -> tuple[Any, str | None]: ...


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::OpenedFileBatch
def _file_error(
    code: str, message: str, *, index: int | None = None
) -> FileBoundaryError:
    details = {"file_index": index} if index is not None else None
    return FileBoundaryError(code, message, details=details)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::OpenedFileBatch
def _absolute_components(
    path: Path, *, root: bool, index: int | None = None
) -> tuple[str, ...]:
    """Parse a Linux absolute path without resolving it or accepting traversal."""
    value = os.fspath(path)
    if not value or "\x00" in value:
        raise _file_error(
            "invalid_local_path", "A local file path is empty or invalid.", index=index
        )
    candidate = Path(value)
    parts = candidate.parts
    if not candidate.is_absolute() or not parts or parts[0] != "/":
        kind = "Allowed roots" if root else "Local file paths"
        raise _file_error(
            "invalid_local_path", f"{kind} must be absolute Linux paths.", index=index
        )
    components = tuple(parts[1:])
    if any(part in {"", ".", ".."} for part in components):
        raise _file_error(
            "invalid_local_path", "Local path traversal is not allowed.", index=index
        )
    return components


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::OpenedFileBatch
def _open_directory_components(components: tuple[str, ...]) -> int:
    """Open one absolute directory through no-follow component handles."""
    current = -1
    try:
        current = os.open("/", _DIRECTORY_FLAGS)
        for component in components:
            following = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
            os.close(current)
            current = following
        metadata = os.fstat(current)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("not a directory")
        return current
    except (OSError, ValueError) as error:
        if current >= 0:
            os.close(current)
        raise _file_error(
            "unsafe_allowed_root",
            "An allowed root is missing, symlinked, or not a directory.",
        ) from error


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::OpenedFileBatch
@dataclass(slots=True)
class _OpenedRoot:
    fd: int
    components: tuple[str, ...] = field(repr=False)

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::OpenedFileBatch
    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::OpenedFileBatch
def _read_descriptor_block(
    descriptor: int,
    *,
    offset: int,
    length: int,
    index: int,
) -> bytes:
    """Read one bounded descriptor block without trusting pathname state."""
    block = bytearray()
    try:
        while len(block) < length:
            part = os.pread(descriptor, length - len(block), offset + len(block))
            if not part:
                raise _file_error(
                    "local_file_changed",
                    "A selected local file became shorter during upload.",
                    index=index,
                )
            block.extend(part)
    except FileBoundaryError:
        raise
    except OSError as error:
        raise _file_error(
            "local_file_read_failed",
            "A selected local file could not be read during upload.",
            index=index,
        ) from error
    return bytes(block)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::OpenedFileBatch
async def _capture_descriptor_hashes(
    descriptor: int,
    metadata: os.stat_result,
    *,
    index: int,
) -> tuple[bytes, ...]:
    """Capture a bounded-memory byte identity while metadata is stable."""
    hashes = []
    for offset in range(0, metadata.st_size, _READ_BLOCK_BYTES):
        length = min(_READ_BLOCK_BYTES, metadata.st_size - offset)
        block = _read_descriptor_block(
            descriptor,
            offset=offset,
            length=length,
            index=index,
        )
        hashes.append(hashlib.sha256(block).digest())
        # Descriptor hashing is intentionally performed without executor
        # threads for restricted client sandboxes, but every bounded block is
        # a cancellation point for the stdio request task.
        await asyncio.sleep(0)
    try:
        current = os.fstat(descriptor)
    except OSError as error:
        raise _file_error(
            "local_file_changed",
            "A selected local file became unavailable during upload.",
            index=index,
        ) from error
    if any(
        current_value != original_value
        for current_value, original_value in (
            (current.st_dev, metadata.st_dev),
            (current.st_ino, metadata.st_ino),
            (current.st_mode, metadata.st_mode),
            (current.st_size, metadata.st_size),
            (current.st_mtime_ns, metadata.st_mtime_ns),
            (current.st_ctime_ns, metadata.st_ctime_ns),
            (current.st_nlink, metadata.st_nlink),
        )
    ):
        raise _file_error(
            "local_file_changed",
            "A selected local file changed while it was being opened.",
            index=index,
        )
    return tuple(hashes)


# @testable true
# @pair mcp-adapter:product-contract
# @tests clients/lagniappe_mcp/tests/test_files.py::test_opened_batch_rejects_unsafe_paths_and_duplicate_objects
# @tests clients/lagniappe_mcp/tests/test_files.py::test_replacing_path_after_open_still_uploads_the_open_descriptor
# @tests clients/lagniappe_mcp/tests/test_files.py::test_open_descriptor_rejects_same_size_rewrite_with_restored_mtime
# @tests clients/lagniappe_mcp/tests/test_files.py::test_unlinked_rewritten_descriptor_fails_content_identity_check
# @matrix mcp-upload : nofollow roots components regular duplicate descriptor-lifetime mutation-snapshot byte-identity
@dataclass(slots=True)
class OpenedFile:
    """One regular file whose verified descriptor remains the byte authority."""

    fd: int
    filename: str
    content_type: str
    size: int
    device: int = field(repr=False)
    inode: int = field(repr=False)
    mode: int = field(repr=False)
    modified_ns: int = field(repr=False)
    changed_ns: int = field(repr=False)
    link_count: int = field(repr=False)
    block_hashes: tuple[bytes, ...] = field(repr=False)

    @property
    def declaration(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
        }

    def verify_unchanged(self, *, index: int) -> None:
        try:
            current = os.fstat(self.fd)
        except OSError as error:
            raise _file_error(
                "local_file_changed",
                "A selected local file became unavailable during upload.",
                index=index,
            ) from error
        changed = (
            current.st_dev != self.device
            or current.st_ino != self.inode
            or current.st_mode != self.mode
            or current.st_size != self.size
            or current.st_mtime_ns != self.modified_ns
        )
        # Replacing the selected pathname after it is opened can legitimately
        # lower only the descriptor's link count and update ctime. The original
        # open descriptor remains authoritative in that case. Every other ctime
        # transition (including a same-size rewrite with restored mtime) fails.
        if not changed and current.st_ctime_ns != self.changed_ns:
            if 0 <= current.st_nlink < self.link_count:
                self.link_count = current.st_nlink
                self.changed_ns = current.st_ctime_ns
            else:
                changed = True
        if changed:
            raise _file_error(
                "local_file_changed",
                "A selected local file changed during upload.",
                index=index,
            )

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


# @testable true
# @pair mcp-adapter:product-contract
# @tests clients/lagniappe_mcp/tests/test_files.py::test_opened_batch_rejects_unsafe_paths_and_duplicate_objects
# @tests clients/lagniappe_mcp/tests/test_files.py::test_opened_batch_rejects_every_non_regular_or_unapproved_input
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_rejects_contract_count_before_opening_paths
# @tests clients/lagniappe_mcp/tests/test_files.py::test_oversized_file_is_rejected_before_descriptor_read
# @tests clients/lagniappe_mcp/tests/test_files.py::test_cancellation_during_byte_snapshot_closes_descriptors
# @matrix mcp-upload : root-authorization batch-preflight cancellation cleanup regular missing empty traversal directory special byte-identity
class OpenedFileBatch:
    """Trusted root handles and files retained for one complete upload batch."""

    def __init__(self, roots: list[_OpenedRoot], files: list[OpenedFile]) -> None:
        self._roots = roots
        self.files = files

    @classmethod
    async def open(
        cls,
        allowed_roots: Sequence[Path],
        file_items: object,
        *,
        max_file_bytes: int | None = None,
        max_total_bytes: int | None = None,
    ) -> OpenedFileBatch:
        if not allowed_roots:
            raise _file_error(
                "no_allowed_roots",
                "Local uploads require at least one explicitly configured allowed root.",
            )
        if (
            not isinstance(file_items, list)
            or not file_items
            or any(
                not isinstance(item, dict) or set(item) != {"path"}
                for item in file_items
            )
        ):
            raise _file_error(
                "invalid_local_files",
                "files must be a non-empty array of objects containing only path.",
            )

        roots: list[_OpenedRoot] = []
        files: list[OpenedFile] = []
        try:
            for configured in allowed_roots:
                components = _absolute_components(Path(configured), root=True)
                roots.append(
                    _OpenedRoot(_open_directory_components(components), components)
                )
            roots.sort(key=lambda item: len(item.components), reverse=True)

            identities: set[tuple[int, int]] = set()
            total_bytes = 0
            for index, item in enumerate(file_items):
                raw_path = item.get("path")
                if not isinstance(raw_path, str) or not raw_path:
                    raise _file_error(
                        "invalid_local_path",
                        "Each local file requires a non-empty string path.",
                        index=index,
                    )
                components = _absolute_components(
                    Path(raw_path), root=False, index=index
                )
                selected = next(
                    (
                        root
                        for root in roots
                        if len(components) > len(root.components)
                        and components[: len(root.components)] == root.components
                    ),
                    None,
                )
                if selected is None:
                    raise _file_error(
                        "outside_allowed_roots",
                        "A selected local file is outside the configured allowed roots.",
                        index=index,
                    )
                relative = components[len(selected.components) :]
                opened = cls._open_file(selected, relative, index=index)
                try:
                    identity = (opened.device, opened.inode)
                    if identity in identities:
                        raise _file_error(
                            "duplicate_local_file",
                            "The upload batch contains the same file more than once.",
                            index=index,
                        )
                    if max_file_bytes is not None and opened.size > max_file_bytes:
                        raise _file_error(
                            "file_too_large",
                            "A selected file exceeds the current per-file upload limit.",
                            index=index,
                        )
                    total_bytes += opened.size
                    if max_total_bytes is not None and total_bytes > max_total_bytes:
                        raise _file_error(
                            "files_too_large",
                            "The selected files exceed the current Plan total-size limit.",
                            index=index,
                        )
                    try:
                        snapshot_metadata = os.fstat(opened.fd)
                    except OSError as error:
                        raise _file_error(
                            "local_file_changed",
                            "A selected local file became unavailable while it was being opened.",
                            index=index,
                        ) from error
                    if any(
                        current_value != original_value
                        for current_value, original_value in (
                            (snapshot_metadata.st_dev, opened.device),
                            (snapshot_metadata.st_ino, opened.inode),
                            (snapshot_metadata.st_mode, opened.mode),
                            (snapshot_metadata.st_size, opened.size),
                            (snapshot_metadata.st_mtime_ns, opened.modified_ns),
                            (snapshot_metadata.st_ctime_ns, opened.changed_ns),
                            (snapshot_metadata.st_nlink, opened.link_count),
                        )
                    ):
                        raise _file_error(
                            "local_file_changed",
                            "A selected local file changed while it was being opened.",
                            index=index,
                        )
                    opened.block_hashes = await _capture_descriptor_hashes(
                        opened.fd,
                        snapshot_metadata,
                        index=index,
                    )
                except BaseException:
                    opened.close()
                    raise
                identities.add(identity)
                files.append(opened)
            return cls(roots, files)
        except BaseException:
            for opened in files:
                opened.close()
            for opened_root in roots:
                opened_root.close()
            raise

    @staticmethod
    def _open_file(
        root: _OpenedRoot, components: tuple[str, ...], *, index: int
    ) -> OpenedFile:
        parent_fd = os.dup(root.fd)
        descriptor = -1
        try:
            for component in components[:-1]:
                following = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = following
            descriptor = os.open(components[-1], _FILE_FLAGS, dir_fd=parent_fd)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise _file_error(
                    "invalid_local_file",
                    "A selected local path is not a regular file.",
                    index=index,
                )
            if metadata.st_size <= 0:
                raise _file_error(
                    "empty_local_file",
                    "Empty local files cannot be uploaded.",
                    index=index,
                )
            filename = components[-1]
            content_type = mimetypes.guess_type(filename, strict=False)[0]
            return OpenedFile(
                fd=descriptor,
                filename=filename,
                content_type=content_type or "application/octet-stream",
                size=metadata.st_size,
                device=metadata.st_dev,
                inode=metadata.st_ino,
                mode=metadata.st_mode,
                modified_ns=metadata.st_mtime_ns,
                changed_ns=metadata.st_ctime_ns,
                link_count=metadata.st_nlink,
                block_hashes=(),
            )
        except FileBoundaryError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        except (OSError, ValueError) as error:
            if descriptor >= 0:
                os.close(descriptor)
            raise _file_error(
                "unsafe_local_file",
                "A selected local file is missing, symlinked, or inaccessible.",
                index=index,
            ) from error
        finally:
            os.close(parent_fd)

    def close(self) -> None:
        for opened in self.files:
            opened.close()
        for root in self._roots:
            root.close()

    def __enter__(self) -> OpenedFileBatch:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# @testable true
# @pair mcp-adapter:product-contract
# @tests clients/lagniappe_mcp/tests/test_files.py::test_opened_batch_rejects_unsafe_paths_and_duplicate_objects
def validate_allowed_roots(allowed_roots: Sequence[Path]) -> None:
    """Revalidate configured roots without opening or naming any file beneath them."""
    opened: list[int] = []
    try:
        for configured in allowed_roots:
            components = _absolute_components(Path(configured), root=True)
            opened.append(_open_directory_components(components))
    finally:
        for descriptor in opened:
            os.close(descriptor)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
class _DescriptorChunkStream(httpx.AsyncByteStream):
    """Re-readable bounded request content sourced only from one open descriptor."""

    def __init__(
        self, opened: OpenedFile, start: int, length: int, *, index: int
    ) -> None:
        self.opened = opened
        self.start = start
        self.length = length
        self.index = index
        self.bytes_read = 0

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
    async def __aiter__(self):
        while self.bytes_read < self.length:
            absolute_offset = self.start + self.bytes_read
            block_index = absolute_offset // _READ_BLOCK_BYTES
            block_offset = block_index * _READ_BLOCK_BYTES
            block_length = min(
                _READ_BLOCK_BYTES,
                self.opened.size - block_offset,
            )
            # Read and authenticate the complete fixed block before yielding
            # any overlapping bytes. This keeps memory bounded while making a
            # resumed range subject to the same open-time byte identity.
            block = _read_descriptor_block(
                self.opened.fd,
                offset=block_offset,
                length=block_length,
                index=self.index,
            )
            if (
                block_index >= len(self.opened.block_hashes)
                or hashlib.sha256(block).digest()
                != self.opened.block_hashes[block_index]
            ):
                raise _file_error(
                    "local_file_changed",
                    "A selected local file's contents changed during upload.",
                    index=self.index,
                )
            slice_start = absolute_offset - block_offset
            count = min(
                block_length - slice_start,
                self.length - self.bytes_read,
            )
            payload = block[slice_start : slice_start + count]
            self.bytes_read += len(payload)
            yield payload

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
    async def aclose(self) -> None:
        return None


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
def _strict_int(value: object, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


# @testable true
# @pair mcp-adapter:product-contract
# @matrix mcp-upload : batch-preflight local-limits
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_rejects_server_limits_above_frozen_local_ceilings_before_open
def _bounded_contract_limits(contract: Mapping[str, Any]) -> tuple[int, int, int]:
    limits = contract.get("limits")
    if not isinstance(limits, Mapping):
        raise TransportError(
            "invalid_contract", "The Plan contract omitted upload limits."
        )
    max_files = _strict_int(limits.get("max_files"), minimum=1)
    max_file_bytes = _strict_int(limits.get("max_file_bytes"), minimum=1)
    max_total_bytes = _strict_int(limits.get("max_total_file_bytes"), minimum=1)
    if (
        max_files is None
        or max_files > MAX_UPLOAD_FILES
        or max_file_bytes is None
        or max_file_bytes > MAX_UPLOAD_FILE_BYTES
        or max_total_bytes is None
        or max_total_bytes > MAX_UPLOAD_TOTAL_BYTES
        or max_file_bytes > max_total_bytes
    ):
        raise TransportError(
            "invalid_contract",
            "The Plan contract contains upload limits outside local safety bounds.",
        )
    return max_files, max_file_bytes, max_total_bytes


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
def _valid_chunk_size(value: object, *, file_size: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    if value < MIN_UPLOAD_CHUNK_BYTES or value > MAX_UPLOAD_CHUNK_BYTES:
        return False
    return (file_size + value - 1) // value <= MAX_UPLOAD_CHUNKS_PER_FILE


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
def _preflight_requested_count(contract: Mapping[str, Any], file_items: object) -> None:
    """Reject an oversized batch before consuming one descriptor per item."""
    if (
        contract.get("tool") != "organize"
        or contract.get("uploads_supported") is not True
    ):
        raise _file_error(
            "uploads_not_supported", "This Plan does not support local file uploads."
        )
    if not isinstance(file_items, list):
        return
    inventory = contract.get("upload_inventory")
    if not isinstance(inventory, Mapping):
        raise TransportError(
            "invalid_contract", "The Plan contract omitted upload limits or inventory."
        )
    if (
        inventory.get("status") != "finalized"
        or inventory.get("authoritative") is not True
    ):
        raise TransportError(
            "uploads_pending", "The Plan already has an unfinished upload batch."
        )
    max_files, _max_file_bytes, _max_total_bytes = _bounded_contract_limits(contract)
    current_files = inventory.get("files")
    current_count = _strict_int(inventory.get("count"))
    if (
        not isinstance(current_files, list)
        or current_count is None
        or current_count != len(current_files)
        or current_count > max_files
    ):
        raise TransportError(
            "invalid_contract",
            "The Plan contract contains invalid upload limits or inventory.",
        )
    if current_count + len(file_items) > max_files:
        raise _file_error(
            "too_many_files",
            "The upload batch exceeds the current Plan file-count limit.",
        )


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
def _preflight_contract(
    contract: Mapping[str, Any], files: Sequence[OpenedFile]
) -> tuple[int, int]:
    if (
        contract.get("tool") != "organize"
        or contract.get("uploads_supported") is not True
    ):
        raise _file_error(
            "uploads_not_supported", "This Plan does not support local file uploads."
        )
    inventory = contract.get("upload_inventory")
    if not isinstance(inventory, Mapping):
        raise TransportError(
            "invalid_contract", "The Plan contract omitted upload limits or inventory."
        )
    if (
        inventory.get("status") != "finalized"
        or inventory.get("authoritative") is not True
    ):
        raise TransportError(
            "uploads_pending", "The Plan already has an unfinished upload batch."
        )

    max_files, max_file_bytes, max_total_bytes = _bounded_contract_limits(contract)
    current_files = inventory.get("files")
    current_count = _strict_int(inventory.get("count"))
    if (
        not isinstance(current_files, list)
        or current_count is None
        or current_count != len(current_files)
        or current_count > max_files
    ):
        raise TransportError(
            "invalid_contract",
            "The Plan contract contains invalid upload limits or inventory.",
        )
    current_total = 0
    for current in current_files:
        if not isinstance(current, Mapping):
            raise TransportError(
                "invalid_contract",
                "The Plan contract contains an invalid file inventory.",
            )
        size = _strict_int(current.get("size"))
        if size is None or size > max_file_bytes:
            raise TransportError(
                "invalid_contract",
                "The Plan contract contains an invalid file inventory.",
            )
        current_total += size
        if current_total > max_total_bytes:
            raise TransportError(
                "invalid_contract",
                "The Plan contract inventory exceeds its upload limits.",
            )

    if current_count + len(files) > max_files:
        raise _file_error(
            "too_many_files",
            "The upload batch exceeds the current Plan file-count limit.",
        )
    if any(opened.size > max_file_bytes for opened in files):
        raise _file_error(
            "file_too_large",
            "A selected file exceeds the current per-file upload limit.",
        )
    if current_total + sum(opened.size for opened in files) > max_total_bytes:
        raise _file_error(
            "files_too_large",
            "The selected files exceed the current Plan total-size limit.",
        )
    return max_file_bytes, max_total_bytes - current_total


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
def _confirmed_offset(response: httpx.Response, *, previous: int, maximum: int) -> int:
    value = response.headers.get("range")
    if value is None:
        confirmed = 0
    else:
        prefix = "bytes=0-"
        if not value.startswith(prefix) or not value[len(prefix) :].isdigit():
            raise TransportError(
                "invalid_upload_offset", "Storage returned an invalid resumable offset."
            )
        confirmed = int(value[len(prefix) :]) + 1
    if confirmed < previous or confirmed > maximum:
        raise TransportError(
            "invalid_upload_offset",
            "Storage returned a regressing or oversized resumable offset.",
        )
    return confirmed


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
async def _storage_send(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Mapping[str, str],
    content: httpx.AsyncByteStream,
    deadline: float,
) -> httpx.Response:
    timeout = httpx.Timeout(
        UPLOAD_TIMEOUT_SECONDS,
        connect=CONNECT_TIMEOUT_SECONDS,
    )
    request = httpx.Request(
        "PUT",
        url,
        headers=dict(headers),
        content=content,
        extensions={"timeout": timeout.as_dict()},
    )
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return await asyncio.wait_for(
        client.send(
            request,
            stream=True,
            auth=None,
            follow_redirects=False,
        ),
        timeout=remaining,
    )


# @testable true
# @pair mcp-adapter:product-contract
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_honors_chunks_and_returns_authoritative_inventory
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_recovers_only_after_a_verified_status_probe
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_rejects_offset_regression_without_finalizing
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_probe_cannot_skip_beyond_the_ambiguous_chunk
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_rejects_a_chunk_below_the_frozen_efficiency_floor
# @tests clients/lagniappe_mcp/tests/test_files.py::test_post_session_recovery_failures_are_not_retryable_as_whole_tool_calls
# @matrix mcp-upload : content-range 308 monotonic probe retry final-2xx local-limits upload-session no-false-finalization
class ResumableUploader:
    """Bounded GCS resumable protocol over an already-created session."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def upload(
        self,
        opened: OpenedFile,
        *,
        index: int,
        session_url: str,
        chunk_size: int,
        deadline: float | None = None,
    ) -> None:
        url = validate_storage_url(session_url, upload=True)
        if not _valid_chunk_size(chunk_size, file_size=opened.size):
            raise TransportError(
                "invalid_upload_session",
                "The API returned an invalid upload chunk size.",
            )

        if deadline is None:
            deadline = (
                asyncio.get_running_loop().time() + UPLOAD_OPERATION_TIMEOUT_SECONDS
            )
        cursor = 0
        recovery_attempts = 0
        no_progress = 0
        while cursor < opened.size:
            opened.verify_unchanged(index=index)
            length = min(chunk_size, opened.size - cursor)
            end = cursor + length - 1
            stream = _DescriptorChunkStream(opened, cursor, length, index=index)
            try:
                response = await _storage_send(
                    self.client,
                    url,
                    headers={
                        "Content-Length": str(length),
                        "Content-Type": opened.content_type,
                        "Content-Range": f"bytes {cursor}-{end}/{opened.size}",
                    },
                    content=stream,
                    deadline=deadline,
                )
            except asyncio.CancelledError:
                raise
            except AdapterError:
                raise
            except (TimeoutError, httpx.TimeoutException, httpx.TransportError) as error:
                recovery_attempts += 1
                if recovery_attempts > MAX_UPLOAD_RECOVERY_ATTEMPTS:
                    raise TransportError(
                        "upload_recovery_exhausted",
                        "The upload connection failed and its recovery budget was exhausted.",
                        retryable=False,
                    ) from error
                cursor, complete = await self._probe(
                    url,
                    total=opened.size,
                    previous=cursor,
                    maximum=end + 1,
                    deadline=deadline,
                )
                if complete:
                    opened.verify_unchanged(index=index)
                    return
                continue

            try:
                if stream.bytes_read != length:
                    raise _file_error(
                        "local_file_changed",
                        "A selected local file byte count changed during upload.",
                        index=index,
                    )
                if 200 <= response.status_code < 300:
                    if end + 1 != opened.size:
                        raise TransportError(
                            "invalid_upload_response",
                            "Storage completed an upload before all declared bytes were sent.",
                        )
                    opened.verify_unchanged(index=index)
                    return
                if response.status_code == 308:
                    confirmed = _confirmed_offset(
                        response, previous=cursor, maximum=end + 1
                    )
                    if confirmed == cursor:
                        no_progress += 1
                        if no_progress > MAX_UPLOAD_RECOVERY_ATTEMPTS:
                            raise TransportError(
                                "upload_no_progress",
                                "Storage did not make progress within the upload retry budget.",
                                retryable=False,
                            )
                    else:
                        no_progress = 0
                    cursor = confirmed
                    if cursor == opened.size:
                        cursor, complete = await self._probe(
                            url,
                            total=opened.size,
                                previous=cursor,
                                maximum=opened.size,
                                deadline=deadline,
                            )
                        if not complete:
                            raise TransportError(
                                "upload_not_complete",
                                "Storage did not confirm the final upload with a successful response.",
                            )
                        opened.verify_unchanged(index=index)
                        return
                    continue
                if 300 <= response.status_code < 400:
                    raise TransportError(
                        "redirect_rejected", "Storage redirects are not allowed."
                    )
                raise TransportError(
                    "upload_failed",
                    "Storage rejected a resumable upload chunk.",
                    status=response.status_code,
                )
            finally:
                await response.aclose()

        raise TransportError(
            "upload_not_complete", "Storage did not confirm upload completion."
        )

    async def _probe(
        self,
        url: str,
        *,
        total: int,
        previous: int,
        maximum: int,
        deadline: float,
    ) -> tuple[int, bool]:
        last_error: httpx.HTTPError | None = None
        for _attempt in range(MAX_UPLOAD_STATUS_PROBES):
            try:
                response = await _storage_send(
                    self.client,
                    url,
                    headers={
                        "Content-Length": "0",
                        "Content-Range": f"bytes */{total}",
                    },
                    content=_EmptyStream(),
                    deadline=deadline,
                )
            except asyncio.CancelledError:
                raise
            except (TimeoutError, httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                continue
            try:
                if 200 <= response.status_code < 300:
                    if maximum != total:
                        raise TransportError(
                            "invalid_upload_response",
                            "Storage completed an upload before all declared bytes were sent.",
                        )
                    return total, True
                if response.status_code == 308:
                    return _confirmed_offset(
                        response, previous=previous, maximum=maximum
                    ), False
                if 300 <= response.status_code < 400:
                    raise TransportError(
                        "redirect_rejected", "Storage redirects are not allowed."
                    )
                raise TransportError(
                    "upload_probe_failed",
                    "Storage rejected a resumable upload status probe.",
                    status=response.status_code,
                )
            finally:
                await response.aclose()
        raise TransportError(
            "upload_probe_failed",
            "The resumable upload status could not be verified.",
            retryable=False,
        ) from last_error


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
class _EmptyStream(httpx.AsyncByteStream):
    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
    async def __aiter__(self):
        if False:
            yield b""

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::ResumableUploader
    async def aclose(self) -> None:
        return None


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
def _validate_sessions(
    value: Any, plan_id: str, files: Sequence[OpenedFile]
) -> tuple[str, list[tuple[str, int]]]:
    if not isinstance(value, Mapping) or value.get("plan_id") != plan_id:
        raise TransportError(
            "invalid_upload_session",
            "The API returned an invalid upload-session response.",
        )
    upload_batch_id = value.get("upload_batch_id")
    if (
        not isinstance(upload_batch_id, str)
        or not _UPLOAD_BATCH_ID_PATTERN.fullmatch(upload_batch_id)
    ):
        raise TransportError(
            "invalid_upload_session",
            "The API omitted a valid upload batch identity.",
        )
    uploads = value.get("uploads")
    if not isinstance(uploads, list) or len(uploads) != len(files):
        raise TransportError(
            "invalid_upload_session",
            "The API returned the wrong number of upload sessions.",
        )
    sessions: list[tuple[str, int]] = []
    seen_sessions: set[tuple[str, str]] = set()
    for index, (entry, opened) in enumerate(zip(uploads, files, strict=True)):
        if not isinstance(entry, Mapping):
            raise TransportError(
                "invalid_upload_session", "The API returned an invalid upload session."
            )
        returned_index = entry.get("index")
        chunk_size = entry.get("chunk_size")
        if (
            isinstance(returned_index, bool)
            or returned_index != index
            or entry.get("filename") != opened.filename
            or not _valid_chunk_size(chunk_size, file_size=opened.size)
        ):
            raise TransportError(
                "invalid_upload_session",
                "The API returned mismatched upload-session metadata.",
            )
        session_url = entry.get("session_url")
        if not isinstance(session_url, str):
            raise TransportError(
                "invalid_upload_session", "The API omitted an upload session URL."
            )
        safe_url = validate_storage_url(session_url, upload=True)
        parsed_session = urlsplit(safe_url)
        session_parameters = dict(
            parse_qsl(parsed_session.query, keep_blank_values=True)
        )
        session_identity = (
            parsed_session.path,
            session_parameters["upload_id"],
        )
        if session_identity in seen_sessions:
            raise TransportError(
                "invalid_upload_session", "The API returned a duplicate upload session."
            )
        seen_sessions.add(session_identity)
        sessions.append((safe_url, chunk_size))
    return upload_batch_id, sessions


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
def _validate_finalized_inventory(
    finalized: Mapping[str, Any],
    contract: Mapping[str, Any],
    files: Sequence[OpenedFile],
) -> None:
    """Prove an ambiguous success contains this complete uploaded batch."""
    inventory = contract.get("upload_inventory")
    prior = inventory.get("files") if isinstance(inventory, Mapping) else None
    current = finalized.get("files")
    if not isinstance(prior, list) or not isinstance(current, list):
        raise TransportError(
            "invalid_response", "The API returned invalid finalized file inventory."
        )

    # @testable false
    # @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::_validate_finalized_inventory
    # @reason inventory identity normalization is owned by final-batch validation
    def identity(item: object) -> tuple[str, str, int] | None:
        if not isinstance(item, Mapping):
            return None
        filename = item.get("filename")
        mimetype = item.get("mimetype")
        size = _strict_int(item.get("size"), minimum=1)
        if not isinstance(filename, str) or not isinstance(mimetype, str) or size is None:
            return None
        return filename, mimetype, size

    expected = Counter(identity(item) for item in prior)
    expected.update((item.filename, item.content_type, item.size) for item in files)
    actual = Counter(identity(item) for item in current)
    if None in expected or None in actual or actual != expected:
        raise TransportError(
            "upload_finalization_unknown",
            "Upload finalization did not return the complete expected file inventory.",
            retryable=False,
        )


# @testable true
# @pair mcp-adapter:product-contract
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_honors_chunks_and_returns_authoritative_inventory
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_rejects_contract_count_before_opening_paths
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_rejects_offset_regression_without_finalizing
# @tests clients/lagniappe_mcp/tests/test_files.py::test_ambiguous_finalization_reads_plan_state_without_replaying
# @tests clients/lagniappe_mcp/tests/test_files.py::test_ambiguous_finalization_rejects_same_metadata_from_replaced_batch
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_cancellation_and_partial_failure_never_finalize
# @tests clients/lagniappe_mcp/tests/test_files.py::test_oversized_file_is_rejected_before_descriptor_read
# @tests clients/lagniappe_mcp/tests/test_files.py::test_cancellation_during_byte_snapshot_closes_descriptors
# @tests clients/lagniappe_mcp/tests/test_files.py::test_upload_uses_one_total_wall_clock_deadline
# @matrix mcp-upload : authoritative-status create-once finalize-once last-writer preflight safe-result upload-all upload-batch-identity cancellation partial-failure no-false-finalization byte-identity timeout retry
async def upload_local_files(
    rest: _RESTLike,
    *,
    plan_id: str,
    file_items: object,
    allowed_roots: Sequence[Path],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Upload one explicit batch and return final Plan state plus file inventory."""
    deadline = asyncio.get_running_loop().time() + UPLOAD_OPERATION_TIMEOUT_SECONDS
    try:
        async with asyncio.timeout_at(deadline):
            return await _upload_local_files(
                rest,
                plan_id=plan_id,
                file_items=file_items,
                allowed_roots=allowed_roots,
                contract=contract,
                deadline=deadline,
            )
    except TimeoutError as error:
        raise TransportError(
            "upload_timeout",
            "The local upload operation exceeded its total deadline.",
            retryable=False,
        ) from error


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/files.py::upload_local_files
async def _upload_local_files(
    rest: _RESTLike,
    *,
    plan_id: str,
    file_items: object,
    allowed_roots: Sequence[Path],
    contract: Mapping[str, Any],
    deadline: float,
) -> dict[str, Any]:
    encoded_plan_id = quote_path_segment(plan_id)
    _preflight_requested_count(contract, file_items)
    max_file_bytes, max_batch_bytes = _preflight_contract(contract, ())
    batch = await OpenedFileBatch.open(
        allowed_roots,
        file_items,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_batch_bytes,
    )
    with batch:
        _preflight_contract(contract, batch.files)
        declarations = [opened.declaration for opened in batch.files]
        created, _request_id = await rest.request_json(
            "POST",
            f"plans/{encoded_plan_id}/uploads",
            body={"files": declarations},
        )
        upload_batch_id, sessions = _validate_sessions(created, plan_id, batch.files)
        uploader = ResumableUploader(rest.storage_client)
        for index, (opened, session) in enumerate(
            zip(batch.files, sessions, strict=True)
        ):
            await uploader.upload(
                opened,
                index=index,
                session_url=session[0],
                chunk_size=session[1],
                deadline=deadline,
            )

        try:
            finalized, _request_id = await rest.request_json(
                "POST",
                f"plans/{encoded_plan_id}/uploads/finalize",
                body={"upload_batch_id": upload_batch_id},
            )
        except TransportError as error:
            # A timeout or connection loss can happen after the API committed
            # finalization.  Never replay that write blindly: inspect the
            # authoritative Plan once and accept it only when no batch remains
            # pending.  Other transport failures are unambiguous and retain
            # their original classification.
            if error.code not in {"api_timeout", "api_unavailable"}:
                raise
            try:
                finalized, _request_id = await rest.request_json(
                    "GET",
                    f"plans/{encoded_plan_id}",
                )
            except AdapterError as status_error:
                raise TransportError(
                    "upload_finalization_unknown",
                    "Upload bytes completed, but finalization state could not be confirmed.",
                    retryable=False,
                ) from status_error
            if not isinstance(finalized, dict) or finalized.get(
                "uploads_pending"
            ) is not False:
                raise TransportError(
                    "upload_finalization_unknown",
                    "Upload bytes completed, but finalization was not confirmed.",
                    retryable=False,
                ) from error
        if (
            not isinstance(finalized, dict)
            or finalized.get("id") != plan_id
            or finalized.get("uploads_pending") is not False
            or finalized.get("upload_batch_id") != upload_batch_id
            or not isinstance(finalized.get("files"), list)
        ):
            raise TransportError(
                "upload_finalization_unknown",
                "The API did not confirm this upload batch as finalized.",
                retryable=False,
            )
        _validate_finalized_inventory(finalized, contract, batch.files)
        finalized = dict(finalized)
        finalized.pop("upload_batch_id")
        return {
            "plan": finalized,
            "upload_inventory": finalized["files"],
        }
