from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx
import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from lagniappe_mcp.errors import FileBoundaryError, TransportError  # noqa: E402
import lagniappe_mcp.files as file_module  # noqa: E402
from lagniappe_mcp.files import (  # noqa: E402
    OpenedFileBatch,
    ResumableUploader,
    upload_local_files,
)
from lagniappe_mcp.limits import (  # noqa: E402
    MAX_UPLOAD_FILE_BYTES,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_TOTAL_BYTES,
    MIN_UPLOAD_CHUNK_BYTES as FROZEN_MIN_UPLOAD_CHUNK_BYTES,
    UPLOAD_OPERATION_TIMEOUT_SECONDS as FROZEN_UPLOAD_OPERATION_TIMEOUT_SECONDS,
)


SESSION_URL = (
    "https://storage.googleapis.com/upload/storage/v1/b/example-bucket/o"
    "?uploadType=resumable&upload_id=opaque"
)
UPLOAD_BATCH_ID = "batch-aaaaaaaaaaaaaaaa"


@pytest.fixture(autouse=True)
def _compact_protocol_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep protocol-state fixtures tiny; dedicated tests restore the real floor."""
    monkeypatch.setattr(file_module, "MIN_UPLOAD_CHUNK_BYTES", 4)


def _contract(*, current_files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    files = list(current_files or [])
    return {
        "tool": "organize",
        "uploads_supported": True,
        "limits": {
            "max_files": 5,
            "max_file_bytes": 1024,
            "max_total_file_bytes": 4096,
        },
        "upload_inventory": {
            "status": "finalized",
            "authoritative": True,
            "count": len(files),
            "files": files,
        },
    }


class _StorageClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict[str, Any]] = []

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool,
        auth: object,
        follow_redirects: bool,
    ) -> httpx.Response:
        body = b"".join([chunk async for chunk in request.stream])
        self.requests.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": body,
                "stream": stream,
                "auth": auth,
                "follow_redirects": follow_redirects,
            }
        )
        outcome = self.outcomes.pop(0)
        if outcome == "reset":
            raise httpx.ReadError("connection reset", request=request)
        if outcome == "cancel":
            raise asyncio.CancelledError
        status, headers = outcome
        return httpx.Response(status, headers=headers, request=request)


class _RESTClient:
    def __init__(
        self,
        storage: _StorageClient,
        *,
        plan_id: str = "plan-1",
        chunk_size: int = 4,
    ) -> None:
        self.storage_client = storage
        self.plan_id = plan_id
        self.chunk_size = chunk_size
        self.calls: list[tuple[str, str, Any]] = []

    async def request_json(
        self,
        method: str,
        target: str,
        *,
        body: Any = None,
        max_bytes: int = 0,
    ) -> tuple[Any, str | None]:
        self.calls.append((method, target, body))
        if target.endswith("/uploads"):
            declarations = body["files"]
            return (
                {
                    "plan_id": self.plan_id,
                    "upload_batch_id": UPLOAD_BATCH_ID,
                    "uploads": [
                        {
                            "index": index,
                            "filename": item["filename"],
                            "session_url": SESSION_URL.replace(
                                "opaque", f"opaque-{index}"
                            ),
                            "chunk_size": self.chunk_size,
                        }
                        for index, item in enumerate(declarations)
                    ],
                },
                "request-create",
            )
        if target.endswith("/uploads/finalize"):
            declarations = self.calls[0][2]["files"]
            return (
                {
                    "id": self.plan_id,
                    "uploads_pending": False,
                    "upload_batch_id": UPLOAD_BATCH_ID,
                    "files": [
                        {
                            "ref": "hash:abcdefghijkl",
                            "name": item["filename"],
                            "filename": item["filename"],
                            "mimetype": item["content_type"],
                            "size": item["size"],
                        }
                        for item in declarations
                    ],
                },
                "request-finalize",
            )
        raise AssertionError(target)


# @matrix mcp-upload : nofollow roots components regular duplicate root-authorization batch-preflight cleanup
# @pair mcp-adapter:product-contract
def test_opened_batch_rejects_unsafe_paths_and_duplicate_objects(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    original = safe / "original.txt"
    original.write_text("content")

    root_link = tmp_path / "root-link"
    root_link.symlink_to(safe, target_is_directory=True)
    with pytest.raises(FileBoundaryError, match="allowed root") as root_error:
        asyncio.run(
            OpenedFileBatch.open(
                [root_link],
                [{"path": str(root_link / original.name)}],
            )
        )
    assert root_error.value.code == "unsafe_allowed_root"

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.txt").write_text("other")
    (safe / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileBoundaryError) as component_error:
        asyncio.run(
            OpenedFileBatch.open(
                [safe],
                [{"path": str(safe / "linked" / "other.txt")}],
            )
        )
    assert component_error.value.code == "unsafe_local_file"

    alias = safe / "alias.txt"
    os.link(original, alias)
    with pytest.raises(FileBoundaryError) as duplicate_error:
        asyncio.run(
            OpenedFileBatch.open(
                [safe],
                [{"path": str(original)}, {"path": str(alias)}],
            )
        )
    assert duplicate_error.value.code == "duplicate_local_file"
    assert str(tmp_path) not in duplicate_error.value.render()


# @matrix mcp-upload : regular missing empty traversal directory special cleanup
# @pair mcp-adapter:product-contract
def test_opened_batch_rejects_every_non_regular_or_unapproved_input(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe"
    safe.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    empty = safe / "empty.txt"
    empty.touch()
    directory = safe / "directory"
    directory.mkdir()
    fifo = safe / "named-pipe"
    os.mkfifo(fifo)

    cases = (
        ([], [{"path": str(outside)}], "no_allowed_roots"),
        ([safe], [{"path": "relative.txt"}], "invalid_local_path"),
        ([safe], [{"path": str(safe / ".." / "outside.txt")}], "invalid_local_path"),
        ([safe], [{"path": str(outside)}], "outside_allowed_roots"),
        ([safe], [{"path": str(safe / "missing.txt")}], "unsafe_local_file"),
        ([safe], [{"path": str(empty)}], "empty_local_file"),
        ([safe], [{"path": str(directory)}], "invalid_local_file"),
        ([safe], [{"path": str(fifo)}], "invalid_local_file"),
    )
    for roots, items, code in cases:
        with pytest.raises(FileBoundaryError) as caught:
            asyncio.run(OpenedFileBatch.open(roots, items))
        assert caught.value.code == code
        assert str(tmp_path) not in caught.value.render()


# @matrix mcp-upload : content-range 308 final-2xx preflight create-once upload-all finalize-once safe-result
# @pair mcp-adapter:product-contract
def test_upload_honors_chunks_and_returns_authoritative_inventory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.txt"
    selected.write_bytes(b"abcdefghij")
    storage = _StorageClient(
        [
            (308, {"Range": "bytes=0-3"}),
            (308, {"Range": "bytes=0-7"}),
            (200, {}),
        ]
    )
    rest = _RESTClient(storage)

    result = asyncio.run(
        upload_local_files(
            rest,
            plan_id="plan-1",
            file_items=[{"path": str(selected)}],
            allowed_roots=[root],
            contract=_contract(),
        )
    )

    assert [request["body"] for request in storage.requests] == [
        b"abcd",
        b"efgh",
        b"ij",
    ]
    assert [request["headers"]["content-range"] for request in storage.requests] == [
        "bytes 0-3/10",
        "bytes 4-7/10",
        "bytes 8-9/10",
    ]
    for request in storage.requests:
        assert request["auth"] is None
        assert request["follow_redirects"] is False
        assert "authorization" not in request["headers"]
        assert "cookie" not in request["headers"]
    assert len(rest.calls) == 2
    assert rest.calls[0][0:2] == ("POST", "plans/plan-1/uploads")
    assert rest.calls[1] == (
        "POST",
        "plans/plan-1/uploads/finalize",
        {"upload_batch_id": UPLOAD_BATCH_ID},
    )
    assert result["upload_inventory"] == result["plan"]["files"]
    assert result["upload_inventory"][0]["filename"] == "payload.txt"
    assert str(tmp_path) not in json.dumps(rest.calls)
    assert str(tmp_path) not in json.dumps(result)
    assert "upload_batch_id" not in json.dumps(result)


# @matrix mcp-upload : batch-preflight preflight
# @pair mcp-adapter:product-contract
def test_upload_rejects_contract_count_before_opening_paths(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    storage = _StorageClient([])
    rest = _RESTClient(storage)
    requested = [{"path": str(root / f"missing-{index}")} for index in range(6)]

    with pytest.raises(FileBoundaryError) as error:
        asyncio.run(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=requested,
                allowed_roots=[root],
                contract=_contract(),
            )
        )

    assert error.value.code == "too_many_files"
    assert rest.calls == []
    assert storage.requests == []


# @matrix mcp-upload : batch-preflight local-limits
# @pair mcp-adapter:product-contract
def test_upload_rejects_server_limits_above_frozen_local_ceilings_before_open(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    requested = [{"path": str(root / "missing.bin")}]

    for field, value in (
        ("max_files", MAX_UPLOAD_FILES + 1),
        ("max_file_bytes", MAX_UPLOAD_FILE_BYTES + 1),
        ("max_total_file_bytes", MAX_UPLOAD_TOTAL_BYTES + 1),
    ):
        contract = _contract()
        contract["limits"][field] = value
        storage = _StorageClient([])
        rest = _RESTClient(storage)
        with pytest.raises(TransportError) as error:
            asyncio.run(
                upload_local_files(
                    rest,
                    plan_id="plan-1",
                    file_items=requested,
                    allowed_roots=[root],
                    contract=contract,
                )
            )
        assert error.value.code == "invalid_contract"
        assert rest.calls == []
        assert storage.requests == []


# @matrix mcp-upload : local-limits upload-session
# @pair mcp-adapter:product-contract
def test_upload_rejects_a_chunk_below_the_frozen_efficiency_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"content")
    monkeypatch.setattr(
        file_module,
        "MIN_UPLOAD_CHUNK_BYTES",
        FROZEN_MIN_UPLOAD_CHUNK_BYTES,
    )
    storage = _StorageClient([])
    rest = _RESTClient(storage, chunk_size=FROZEN_MIN_UPLOAD_CHUNK_BYTES - 1)

    with pytest.raises(TransportError) as error:
        asyncio.run(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )

    assert error.value.code == "invalid_upload_session"
    assert [target for _, target, _ in rest.calls] == ["plans/plan-1/uploads"]
    assert storage.requests == []


# @matrix mcp-upload : batch-preflight byte-identity
# @pair mcp-adapter:product-contract
def test_oversized_file_is_rejected_before_descriptor_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "oversized.bin"
    selected.write_bytes(b"x" * 1025)
    storage = _StorageClient([])
    rest = _RESTClient(storage)

    def unexpected_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("oversized descriptor must not be read")

    monkeypatch.setattr(file_module.os, "pread", unexpected_read)
    with pytest.raises(FileBoundaryError) as error:
        asyncio.run(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )

    assert error.value.code == "file_too_large"
    assert rest.calls == []
    assert storage.requests == []


# @matrix mcp-upload : cancellation cleanup byte-identity
# @pair mcp-adapter:product-contract
def test_cancellation_during_byte_snapshot_closes_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"x" * (3 * 64 * 1024))
    storage = _StorageClient([])
    rest = _RESTClient(storage)
    contract = _contract()
    contract["limits"] = {
        "max_files": 5,
        "max_file_bytes": 1024 * 1024,
        "max_total_file_bytes": 2 * 1024 * 1024,
    }
    original_read = file_module._read_descriptor_block
    read_descriptors: list[int] = []

    def recording_read(descriptor: int, **kwargs: Any) -> bytes:
        read_descriptors.append(descriptor)
        return original_read(descriptor, **kwargs)

    monkeypatch.setattr(file_module, "_read_descriptor_block", recording_read)

    async def cancel_during_snapshot() -> None:
        task = asyncio.create_task(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=contract,
            )
        )
        while not read_descriptors:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_during_snapshot())

    with pytest.raises(OSError):
        os.fstat(read_descriptors[0])
    assert rest.calls == []
    assert storage.requests == []


# @matrix mcp-upload : probe retry
# @pair mcp-adapter:product-contract
def test_upload_recovers_only_after_a_verified_status_probe(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"abcdefgh")
    storage = _StorageClient(
        [
            "reset",
            (308, {"Range": "bytes=0-1"}),
            (308, {"Range": "bytes=0-5"}),
            (200, {}),
        ]
    )
    rest = _RESTClient(storage)

    asyncio.run(
        upload_local_files(
            rest,
            plan_id="plan-1",
            file_items=[{"path": str(selected)}],
            allowed_roots=[root],
            contract=_contract(),
        )
    )

    assert [request["headers"]["content-range"] for request in storage.requests] == [
        "bytes 0-3/8",
        "bytes */8",
        "bytes 2-5/8",
        "bytes 6-7/8",
    ]
    assert [request["body"] for request in storage.requests] == [
        b"abcd",
        b"",
        b"cdef",
        b"gh",
    ]
    assert len(rest.calls) == 2


# @matrix mcp-upload : monotonic
# @pair mcp-adapter:product-contract
def test_upload_rejects_offset_regression_without_finalizing(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"abcdefgh")
    storage = _StorageClient(
        [
            (308, {"Range": "bytes=0-3"}),
            (308, {"Range": "bytes=0-2"}),
        ]
    )
    rest = _RESTClient(storage)

    with pytest.raises(TransportError) as error:
        asyncio.run(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )

    assert error.value.code == "invalid_upload_offset"
    assert len(rest.calls) == 1


# @matrix mcp-upload : monotonic probe
# @pair mcp-adapter:product-contract
def test_upload_probe_cannot_skip_beyond_the_ambiguous_chunk(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"abcdefgh")
    storage = _StorageClient(
        [
            "reset",
            (308, {"Range": "bytes=0-5"}),
        ]
    )
    rest = _RESTClient(storage)

    with pytest.raises(TransportError) as error:
        asyncio.run(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )

    assert error.value.code == "invalid_upload_offset"
    assert [request["headers"]["content-range"] for request in storage.requests] == [
        "bytes 0-3/8",
        "bytes */8",
    ]
    assert len(rest.calls) == 1


# @matrix mcp-upload : retry no-false-finalization
# @pair mcp-adapter:product-contract
def test_post_session_recovery_failures_are_not_retryable_as_whole_tool_calls(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"abcdefgh")
    cases = (
        (
            ["reset", (308, {}), "reset", (308, {}), "reset"],
            "upload_recovery_exhausted",
        ),
        ([(308, {}), (308, {}), (308, {})], "upload_no_progress"),
        (["reset", "reset", "reset", "reset"], "upload_probe_failed"),
    )

    for outcomes, code in cases:
        storage = _StorageClient(outcomes)
        rest = _RESTClient(storage)
        with pytest.raises(TransportError) as error:
            asyncio.run(
                upload_local_files(
                    rest,
                    plan_id="plan-1",
                    file_items=[{"path": str(selected)}],
                    allowed_roots=[root],
                    contract=_contract(),
                )
            )
        assert error.value.code == code
        assert error.value.retryable is False
        assert [target for _, target, _ in rest.calls] == ["plans/plan-1/uploads"]


# @matrix mcp-upload : timeout retry no-false-finalization
# @pair mcp-adapter:product-contract
def test_upload_uses_one_total_wall_clock_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert FROZEN_UPLOAD_OPERATION_TIMEOUT_SECONDS < 300
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"abcdefgh")

    class SlowStorage(_StorageClient):
        async def send(self, *args: Any, **kwargs: Any) -> httpx.Response:
            await asyncio.sleep(0.1)
            return await super().send(*args, **kwargs)

    monkeypatch.setattr(file_module, "UPLOAD_OPERATION_TIMEOUT_SECONDS", 0.01)
    storage = SlowStorage([(200, {})])
    rest = _RESTClient(storage)

    with pytest.raises(TransportError) as error:
        asyncio.run(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )

    assert error.value.code == "upload_timeout"
    assert error.value.retryable is False
    assert [target for _, target, _ in rest.calls] == ["plans/plan-1/uploads"]


# @matrix mcp-upload : cancellation partial-failure no-false-finalization
# @pair mcp-adapter:product-contract
def test_upload_cancellation_and_partial_failure_never_finalize(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    first = root / "first.bin"
    second = root / "second.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"b")

    cancelled = _RESTClient(_StorageClient(["cancel"]), chunk_size=4)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            upload_local_files(
                cancelled,
                plan_id="plan-1",
                file_items=[{"path": str(first)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )
    assert [target for _, target, _ in cancelled.calls] == ["plans/plan-1/uploads"]

    partial = _RESTClient(_StorageClient([(200, {}), (500, {})]), chunk_size=4)
    with pytest.raises(TransportError) as failed:
        asyncio.run(
            upload_local_files(
                partial,
                plan_id="plan-1",
                file_items=[{"path": str(first)}, {"path": str(second)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )
    assert failed.value.code == "upload_failed"
    assert [target for _, target, _ in partial.calls] == ["plans/plan-1/uploads"]


# @matrix mcp-upload : finalize-once authoritative-status
# @pair mcp-adapter:product-contract
def test_ambiguous_finalization_reads_plan_state_without_replaying(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"complete")
    storage = _StorageClient([(308, {"Range": "bytes=0-3"}), (200, {})])

    class AmbiguousFinalizeREST(_RESTClient):
        async def request_json(
            self,
            method: str,
            target: str,
            *,
            body: Any = None,
            max_bytes: int = 0,
        ) -> tuple[Any, str | None]:
            if target.endswith("/uploads/finalize"):
                self.calls.append((method, target, body))
                raise TransportError(
                    "api_timeout", "The finalization response was lost."
                )
            if method == "GET" and target == "plans/plan-1":
                self.calls.append((method, target, body))
                return (
                    {
                        "id": "plan-1",
                        "uploads_pending": False,
                        "upload_batch_id": UPLOAD_BATCH_ID,
                        "files": [
                            {
                                "ref": "hash:abcdefghijkl",
                                "name": "payload.bin",
                                "filename": "payload.bin",
                                "mimetype": "application/octet-stream",
                                "size": 8,
                            }
                        ],
                    },
                    "request-status",
                )
            return await super().request_json(
                method, target, body=body, max_bytes=max_bytes
            )

    rest = AmbiguousFinalizeREST(storage)
    result = asyncio.run(
        upload_local_files(
            rest,
            plan_id="plan-1",
            file_items=[{"path": str(selected)}],
            allowed_roots=[root],
            contract=_contract(),
        )
    )

    assert result["plan"]["uploads_pending"] is False
    assert [call[:2] for call in rest.calls] == [
        ("POST", "plans/plan-1/uploads"),
        ("POST", "plans/plan-1/uploads/finalize"),
        ("GET", "plans/plan-1"),
    ]

    class MissingBatchREST(AmbiguousFinalizeREST):
        async def request_json(self, method: str, target: str, **kwargs: Any):
            value, request_id = await super().request_json(method, target, **kwargs)
            if method == "GET" and target == "plans/plan-1":
                value["files"] = []
            return value, request_id

    missing = MissingBatchREST(
        _StorageClient([(308, {"Range": "bytes=0-3"}), (200, {})])
    )
    with pytest.raises(TransportError) as unknown:
        asyncio.run(
            upload_local_files(
                missing,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )
    assert unknown.value.code == "upload_finalization_unknown"
    assert sum(target.endswith("/uploads/finalize") for _, target, _ in missing.calls) == 1


# @matrix mcp-upload : authoritative-status finalize-once last-writer upload-batch-identity
# @pair mcp-adapter:product-contract
def test_ambiguous_finalization_rejects_same_metadata_from_replaced_batch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    first_bytes = b"AAAA"
    replacement_bytes = b"BBBB"
    assert first_bytes != replacement_bytes
    assert len(first_bytes) == len(replacement_bytes)
    selected.write_bytes(first_bytes)
    storage = _StorageClient([(200, {})])

    class ReplacedBatchREST(_RESTClient):
        async def request_json(
            self,
            method: str,
            target: str,
            *,
            body: Any = None,
            max_bytes: int = 0,
        ) -> tuple[Any, str | None]:
            if target.endswith("/uploads/finalize"):
                self.calls.append((method, target, body))
                raise TransportError(
                    "api_timeout", "The finalization response was lost."
                )
            if method == "GET" and target == "plans/plan-1":
                self.calls.append((method, target, body))
                return (
                    {
                        "id": "plan-1",
                        "uploads_pending": False,
                        "upload_batch_id": "batch-bbbbbbbbbbbbbbbb",
                        # A racing caller used indistinguishable declaration
                        # metadata but its session received replacement_bytes.
                        "files": [
                            {
                                "ref": "hash:abcdefghijkl",
                                "name": "payload.bin",
                                "filename": "payload.bin",
                                "mimetype": "application/octet-stream",
                                "size": len(replacement_bytes),
                            }
                        ],
                    },
                    "request-status",
                )
            return await super().request_json(
                method,
                target,
                body=body,
                max_bytes=max_bytes,
            )

    rest = ReplacedBatchREST(storage, chunk_size=64)
    with pytest.raises(TransportError) as error:
        asyncio.run(
            upload_local_files(
                rest,
                plan_id="plan-1",
                file_items=[{"path": str(selected)}],
                allowed_roots=[root],
                contract=_contract(),
            )
        )

    assert error.value.code == "upload_finalization_unknown"
    assert UPLOAD_BATCH_ID not in error.value.render()
    assert [call[:2] for call in rest.calls] == [
        ("POST", "plans/plan-1/uploads"),
        ("POST", "plans/plan-1/uploads/finalize"),
        ("GET", "plans/plan-1"),
    ]


# @matrix mcp-upload : descriptor-lifetime
# @pair mcp-adapter:product-contract
def test_replacing_path_after_open_still_uploads_the_open_descriptor(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"original")
    replacement = root / "replacement.bin"
    replacement.write_bytes(b"replaced")
    storage = _StorageClient([(200, {})])

    with asyncio.run(
        OpenedFileBatch.open([root], [{"path": str(selected)}])
    ) as batch:
        os.replace(replacement, selected)
        asyncio.run(
            ResumableUploader(storage).upload(
                batch.files[0],
                index=0,
                session_url=SESSION_URL,
                chunk_size=64,
            )
        )

    assert storage.requests[0]["body"] == b"original"


# @matrix mcp-upload : descriptor-lifetime mutation-snapshot
# @pair mcp-adapter:product-contract
def test_open_descriptor_rejects_same_size_rewrite_with_restored_mtime(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"original")

    with asyncio.run(
        OpenedFileBatch.open([root], [{"path": str(selected)}])
    ) as batch:
        opened = batch.files[0]
        metadata = os.fstat(opened.fd)
        selected.write_bytes(b"changed!")
        os.utime(
            selected,
            ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
            follow_symlinks=False,
        )
        assert os.fstat(opened.fd).st_ctime_ns != opened.changed_ns
        with pytest.raises(FileBoundaryError) as changed:
            opened.verify_unchanged(index=0)
        assert changed.value.code == "local_file_changed"


# @matrix mcp-upload : descriptor-lifetime mutation-snapshot byte-identity
# @pair mcp-adapter:product-contract
def test_unlinked_rewritten_descriptor_fails_content_identity_check(
    tmp_path: Path,
) -> None:
    root = tmp_path / "approved"
    root.mkdir()
    selected = root / "payload.bin"
    selected.write_bytes(b"original")
    replacement = root / "replacement.bin"
    replacement.write_bytes(b"new-path")
    storage = _StorageClient([(200, {})])

    with asyncio.run(
        OpenedFileBatch.open([root], [{"path": str(selected)}])
    ) as batch:
        opened = batch.files[0]
        metadata = os.fstat(opened.fd)
        selected.write_bytes(b"changed!")
        os.utime(
            selected,
            ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
            follow_symlinks=False,
        )
        os.replace(replacement, selected)

        # A path replacement legitimately changes only ctime/link count from
        # the descriptor's perspective, so metadata alone cannot distinguish
        # this combined rewrite-and-unlink attack.
        opened.verify_unchanged(index=0)
        with pytest.raises(FileBoundaryError) as changed:
            asyncio.run(
                ResumableUploader(storage).upload(
                    opened,
                    index=0,
                    session_url=SESSION_URL,
                    chunk_size=64,
                )
            )

    assert changed.value.code == "local_file_changed"
    assert storage.requests == []
