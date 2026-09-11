"""Remote upload capability validation and exact-batch finalization."""

import asyncio
from copy import deepcopy

import pytest

from lagniappe_mcp import terminal_files
from lagniappe_mcp.errors import AdapterError
from lagniappe_mcp.limits import MIN_UPLOAD_CHUNK_BYTES


def _manifest():
    return {
        "plan_id": "plan-1",
        "upload_batch_id": "a" * 32,
        "files": [{"filename": "notes.txt", "content_type": "text/plain", "size": 5}],
        "uploads": [
            {
                "index": 0,
                "filename": "notes.txt",
                "chunk_size": MIN_UPLOAD_CHUNK_BYTES,
                "session_url": "https://storage.googleapis.com/upload/storage/v1/b/bucket/o?uploadType=resumable&upload_id=private",
            }
        ],
    }


# @matrix mcp-upload : terminal validation token-separation
def test_manifest_allows_only_validated_storage_writes_and_never_oauth_secrets():
    manifest = _manifest()
    assert (
        terminal_files.validate_manifest(manifest, bearer="oauth-secret")[0] == "a" * 32
    )
    for target in (
        "https://attacker.test/upload?upload_id=x",
        "http://storage.googleapis.com/upload/storage/v1/b/bucket/o?upload_id=x",
        "https://storage.googleapis.com/upload/storage/v1/b/bucket/o?uploadType=resumable&upload_id=oauth-secret",
    ):
        value = deepcopy(manifest)
        value["uploads"][0]["session_url"] = target
        with pytest.raises(AdapterError):
            terminal_files.validate_manifest(value, bearer="oauth-secret")
    for mutate in (
        lambda value: value["uploads"][0].update(filename="wrong.txt"),
        lambda value: value["uploads"][0].update(index=1),
        lambda value: value["uploads"][0].update(authorization="oauth-secret"),
        lambda value: value["files"][0].update(content_type="oauth-secret"),
        lambda value: value.update(plan_id="oauth-secret"),
    ):
        value = deepcopy(manifest)
        mutate(value)
        with pytest.raises(AdapterError):
            terminal_files.validate_manifest(value, bearer="oauth-secret")


# @matrix mcp-upload : terminal finalize-once upload-batch-identity
@pytest.mark.parametrize(
    "raw",
    [
        {"id": "plan-1", "uploads_pending": True, "upload_batch_id": "a" * 32},
        {"id": "plan-1", "uploads_pending": False, "upload_batch_id": "b" * 32},
        {"id": "other-plan", "uploads_pending": False, "upload_batch_id": "a" * 32},
    ],
)
@pytest.mark.parametrize("ambiguous", [False, True])
def test_terminal_finalize_never_accepts_incomplete_or_replaced_batch(raw, ambiguous):
    from types import SimpleNamespace
    from lagniappe_mcp.errors import TransportError

    calls = []

    async def request(method, route, **kwargs):
        calls.append((method, route))
        if method == "POST" and ambiguous:
            raise TransportError("api_timeout", "ambiguous")
        return raw, None

    adapter = SimpleNamespace(rest=SimpleNamespace(request_json=request))
    with pytest.raises(AdapterError, match="did not confirm"):
        asyncio.run(
            terminal_files.finalize_uploads(
                adapter,
                {
                    "plan_id": "plan-1",
                    "upload_batch_id": "a" * 32,
                },
            )
        )
    assert calls == [("POST", "plans/plan-1/uploads/finalize")] + (
        [("GET", "plans/plan-1")] if ambiguous else []
    )
