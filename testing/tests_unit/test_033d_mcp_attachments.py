"""Attachment download policy, real byte limits, and spool lifetime."""

import asyncio
from pathlib import Path
import socket

import httpx
import pytest

from lagniappe_mcp import attachments as files
from lagniappe_mcp.errors import AdapterError
from lagniappe_mcp.limits import MAX_UPLOAD_FILE_BYTES, MAX_UPLOAD_TOTAL_BYTES


ITEM = {
    "download_url": "https://files.example.com/file?temporary=private",
    "file_id": "file-1",
    "file_name": "document.txt",
}


async def _public_dns(monkeypatch, addresses=("93.184.216.34",)):
    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 443))
            for value in addresses
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, size):
        self.size = size

    async def __aiter__(self):
        for offset in range(0, self.size, 65536):
            yield b"x" * min(65536, self.size - offset)


# @matrix mcp-upload : remote ssrf dns-pinning
def test_attachment_urls_reject_unsafe_addresses_and_pin_dns(monkeypatch):
    async def scenario():
        await _public_dns(monkeypatch)
        target, hostname = await files.pinned_url(ITEM["download_url"])
        assert target == "https://93.184.216.34/file?temporary=private"
        assert hostname == "files.example.com"
        for url in (
            "http://files.example.com/a",
            "https://user@files.example.com/a",
            "https://files.example.com/a#x",
            "file:///etc/passwd",
            "https://files.example.com:444/a",
        ):
            with pytest.raises(AdapterError):
                await files.pinned_url(url)
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "192.168.0.1",
            "::1",
            "::ffff:127.0.0.1",
            "224.0.0.1",
            "100.64.0.1",
        ):
            await _public_dns(monkeypatch, ("93.184.216.34", address))
            with pytest.raises(AdapterError):
                await files.pinned_url(ITEM["download_url"])

    asyncio.run(scenario())


# @matrix mcp-upload : remote filename mime
def test_attachment_names_and_mime_hints_do_not_select_paths():
    assert files.attachment_name({"file_name": "../../etc/passwd"}, 0, "") == "passwd"
    assert (
        files.attachment_name({"file_name": "C:\\secret\\report.pdf"}, 0, "")
        == "report.pdf"
    )
    assert (
        files.attachment_name(
            {"file_name": "image.png", "mime_type": "text/html"}, 0, "text/html"
        )
        == "image.png"
    )
    assert files.attachment_name({}, 0, "image/png") == "attachment-1.png"
    assert "/" not in files.attachment_name({"file_name": "../\x00.."}, 0, "")
    assert (
        len(files.attachment_name({"file_name": "é" * 500 + ".pdf"}, 0, "").encode())
        <= 240
    )


# @matrix mcp-upload : remote streaming bounds redirects privacy
def test_attachment_download_counts_actual_bytes_and_cleans_partial_files(
    monkeypatch, tmp_path
):
    async def scenario():
        await _public_dns(monkeypatch)
        for size, allowed in (
            (MAX_UPLOAD_FILE_BYTES, True),
            (MAX_UPLOAD_FILE_BYTES + 1, False),
            (0, False),
        ):
            destination = tmp_path / str(size)
            destination.mkdir()

            def factory(**kwargs):
                return httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(200, stream=Chunks(size))
                    ),
                    **kwargs,
                )

            if allowed:
                path, count = await files.download_attachment(
                    ITEM,
                    destination,
                    0,
                    cap=MAX_UPLOAD_FILE_BYTES,
                    client_factory=factory,
                )
                assert count == path.stat().st_size == MAX_UPLOAD_FILE_BYTES
            else:
                with pytest.raises(AdapterError) as failure:
                    await files.download_attachment(
                        ITEM,
                        destination,
                        0,
                        cap=MAX_UPLOAD_FILE_BYTES,
                        client_factory=factory,
                    )
                assert ITEM["download_url"] not in str(failure.value)
                assert not list(destination.iterdir())
        for declared in ("nonsense", str(MAX_UPLOAD_FILE_BYTES + 1), "2"):
            destination = tmp_path / ("declared-" + declared)
            destination.mkdir()

            def factory(**kwargs):
                return httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(
                            200, headers={"Content-Length": declared}, stream=Chunks(4)
                        )
                    ),
                    **kwargs,
                )

            with pytest.raises(AdapterError):
                await files.download_attachment(
                    ITEM,
                    destination,
                    0,
                    cap=MAX_UPLOAD_FILE_BYTES,
                    client_factory=factory,
                )
            assert not list(destination.iterdir())

    asyncio.run(scenario())


# @matrix mcp-upload : remote ssrf redirects privacy
def test_redirect_destinations_are_revalidated_before_connecting(monkeypatch, tmp_path):
    async def scenario():
        resolutions, requests = [], []

        async def resolve(hostname, *args, **kwargs):
            resolutions.append(hostname)
            address = (
                "169.254.169.254"
                if hostname == "metadata.google.internal"
                else "93.184.216.34"
            )
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)

        def upstream(request):
            requests.append(request)
            return httpx.Response(
                302,
                headers={
                    "Location": "https://metadata.google.internal/computeMetadata/v1/instance"
                },
            )

        def factory(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(upstream), **kwargs)

        with pytest.raises(AdapterError) as failure:
            await files.download_attachment(
                ITEM, tmp_path, 0, cap=100, client_factory=factory
            )
        assert failure.value.code == "unsafe_attachment_url"
        assert resolutions == ["files.example.com", "metadata.google.internal"]
        assert len(requests) == 1
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


# @matrix mcp-upload : remote cancellation cleanup bounds
def test_partial_downloads_clean_the_entire_spool_when_transfer_fails(monkeypatch):
    async def scenario():
        await _public_dns(monkeypatch)
        original = files.download_attachment
        roots, requested_caps = [], []

        class CancelledTransfer(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial"
                raise asyncio.CancelledError

        for cancellation in (False, True):

            def factory(**kwargs):
                stream = CancelledTransfer() if cancellation else Chunks(5)
                return httpx.AsyncClient(
                    transport=httpx.MockTransport(
                        lambda request: httpx.Response(200, stream=stream)
                    ),
                    **kwargs,
                )

            async def download(item, directory, index, *, cap):
                roots.append(directory.parent)
                requested_caps.append(cap)
                return await original(
                    item, directory, index, cap=cap, client_factory=factory
                )

            monkeypatch.setattr(files, "download_attachment", download)
            items = [
                ITEM,
                {
                    **ITEM,
                    "file_id": "file-2",
                    "download_url": "https://files.example.com/second",
                },
            ]
            expected_error = asyncio.CancelledError if cancellation else AdapterError
            with pytest.raises(expected_error):
                async with files.spool_attachments(
                    items, max_file_bytes=10, max_total_bytes=9
                ):
                    pytest.fail("Incomplete files must not reach uploads/create")
            assert all(not path.exists() for path in roots)
        assert requested_caps == [9, 4, 9]

    asyncio.run(scenario())


# @matrix mcp-upload : remote streaming bounds redirects privacy
def test_attachment_redirects_and_expiry_never_forward_credentials(
    monkeypatch, tmp_path
):
    async def scenario():
        await _public_dns(monkeypatch)
        seen = []

        def upstream(request):
            seen.append(request)
            assert request.url.host == "93.184.216.34"
            assert request.extensions["sni_hostname"] == request.headers["host"]
            assert not {"authorization", "cookie", "x-lagniappe-mcp-token"} & set(
                request.headers
            )
            if len(seen) == 1:
                return httpx.Response(
                    302,
                    headers={
                        "Location": "https://other.example.com/expired",
                        "Set-Cookie": "secret=value",
                    },
                )
            return httpx.Response(403)

        def factory(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(upstream), **kwargs)

        with pytest.raises(AdapterError) as failure:
            await files.download_attachment(
                ITEM, tmp_path, 0, cap=100, client_factory=factory
            )
        assert failure.value.code == "attachment_expired"
        assert "Reattach" in str(failure.value)
        assert len(seen) == 2 and seen[1].headers["host"] == "other.example.com"
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


# @matrix mcp-upload : remote cancellation cleanup bounds duplicate
def test_spooling_has_one_total_limit_and_cleans_on_cancellation(monkeypatch):
    async def scenario():
        locations, caps = [], []

        async def download(item, directory, index, *, cap):
            locations.append(directory)
            caps.append(cap)
            path = directory / "file.txt"
            path.write_bytes(b"data")
            return path, 4

        monkeypatch.setattr(files, "download_attachment", download)
        items = [
            {
                **ITEM,
                "file_id": str(index),
                "download_url": f"https://files.example.com/{index}",
            }
            for index in range(20)
        ]
        async with files.spool_attachments(
            items, max_file_bytes=10, max_total_bytes=80
        ) as paths:
            assert len(paths) == 20 and all(
                Path(item["path"]).exists() for item in paths
            )
        assert caps[-1] == 4 and all(not directory.exists() for directory in locations)
        for invalid in ([], items + [ITEM], [ITEM, ITEM]):
            with pytest.raises(AdapterError):
                async with files.spool_attachments(
                    invalid, max_file_bytes=10, max_total_bytes=80
                ):
                    pytest.fail("Invalid batch reached upload")
        with pytest.raises(asyncio.CancelledError):
            async with files.spool_attachments(
                [ITEM], max_file_bytes=10, max_total_bytes=80
            ):
                raise asyncio.CancelledError
        assert all(not directory.exists() for directory in locations)

        sizes = [MAX_UPLOAD_FILE_BYTES, MAX_UPLOAD_TOTAL_BYTES - MAX_UPLOAD_FILE_BYTES]

        async def boundary(item, directory, index, *, cap):
            assert sizes[index] <= cap
            return directory / "placeholder", sizes[index]

        monkeypatch.setattr(files, "download_attachment", boundary)
        async with files.spool_attachments(
            items[:2],
            max_file_bytes=MAX_UPLOAD_FILE_BYTES,
            max_total_bytes=MAX_UPLOAD_TOTAL_BYTES,
        ) as paths:
            assert len(paths) == 2

    asyncio.run(scenario())
