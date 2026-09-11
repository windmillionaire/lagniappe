"""Bounded ChatGPT attachment spooling before the existing upload workflow."""

import asyncio
from contextlib import asynccontextmanager
import ipaddress
import mimetypes
from pathlib import Path
import re
import socket
import tempfile
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from lagniappe_mcp.errors import AdapterError
from lagniappe_mcp.limits import MAX_UPLOAD_FILES
from lagniappe_mcp.rest import _raw_chunks


_MAX_REDIRECTS = 3


# @testable true
# @tests tests_unit/test_033d_mcp_attachments.py::test_attachment_urls_reject_unsafe_addresses_and_pin_dns
# @matrix mcp-upload : remote ssrf dns-pinning
async def pinned_url(url):
    """Validate every DNS answer, then connect to an IP with the original TLS name."""
    try:
        if not isinstance(url, str) or not 1 <= len(url) <= 8192:
            raise ValueError()
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or "#" in url
            or "\\" in url
            or any(ord(char) <= 32 or ord(char) == 127 for char in url)
            or parsed.hostname.endswith(".")
            or "%" in parsed.netloc
        ):
            raise ValueError()
        hostname = parsed.hostname.encode("idna").decode("ascii")
        answers = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                hostname, 443, type=socket.SOCK_STREAM
            ),
            5,
        )
        addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
        if not addresses or any(
            not address.is_global
            or address.is_multicast
            or (
                isinstance(address, ipaddress.IPv6Address)
                and (
                    address.ipv4_mapped is not None
                    or address.sixtofour is not None
                    or address.teredo is not None
                )
            )
            for address in addresses
        ):
            raise ValueError()
        address = sorted(addresses, key=lambda value: (value.version, str(value)))[0]
        host = f"[{address}]" if address.version == 6 else str(address)
        return urlunsplit(
            ("https", host, parsed.path or "/", parsed.query, "")
        ), hostname
    except (ValueError, UnicodeError, OSError, TimeoutError):
        raise AdapterError(
            "unsafe_attachment_url",
            "The attachment download address could not be safely used. Reattach the file and try again.",
        ) from None


# @testable true
# @tests tests_unit/test_033d_mcp_attachments.py::test_attachment_names_and_mime_hints_do_not_select_paths
# @matrix mcp-upload : remote filename mime
def attachment_name(item, index, content_type):
    raw = item.get("file_name") or ""
    name = unicodedata.normalize("NFC", raw.replace("\\", "/").rsplit("/", 1)[-1])
    name = "".join(
        char for char in name if not unicodedata.category(char).startswith("C")
    )
    name = name.strip(" .")
    if not name or name in {".", ".."}:
        media_type = (
            (item.get("mime_type") or content_type).split(";", 1)[0].strip().casefold()
        )
        name = f"attachment-{index + 1}" + (
            mimetypes.guess_extension(media_type, strict=False) or ".bin"
        )
    # Match the local uploader's filename policy. Transport MIME hints never
    # override its extension-based declarations or the existing API validation.
    suffix = Path(name).suffix[:20]
    stem = name[: -len(suffix)] if suffix else name
    while len((stem + suffix).encode("utf-8")) > 240:
        stem = stem[:-1]
    return stem + suffix


# @testable true
# @tests tests_unit/test_033d_mcp_attachments.py::test_attachment_download_counts_actual_bytes_and_cleans_partial_files
# @tests tests_unit/test_033d_mcp_attachments.py::test_attachment_redirects_and_expiry_never_forward_credentials
# @tests tests_unit/test_033d_mcp_attachments.py::test_redirect_destinations_are_revalidated_before_connecting
# @tests tests_unit/test_033d_mcp_attachments.py::test_partial_downloads_clean_the_entire_spool_when_transfer_fails
# @matrix mcp-upload : remote streaming bounds redirects privacy ssrf cancellation cleanup
async def download_attachment(
    item, directory, index, *, cap, client_factory=httpx.AsyncClient
):
    current, seen = item["download_url"], set()
    for redirect_count in range(_MAX_REDIRECTS + 1):
        if current in seen:
            raise AdapterError(
                "attachment_redirect",
                "The attachment could not be downloaded. Reattach it and try again.",
            )
        seen.add(current)
        address_url, hostname = await pinned_url(current)
        # A fresh, credential-free pool for each host also prevents TLS-session
        # reuse between unrelated hosts sharing a resolved address.
        async with client_factory(trust_env=False, follow_redirects=False) as client:
            request = httpx.Request(
                "GET",
                address_url,
                headers={"Host": hostname, "Accept-Encoding": "identity"},
                extensions={
                    "sni_hostname": hostname,
                    "timeout": {"connect": 5, "read": 15, "write": 15, "pool": 5},
                },
            )
            response = None
            try:
                response = await client.send(
                    request, stream=True, auth=None, follow_redirects=False
                )
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirect_count == _MAX_REDIRECTS:
                        raise AdapterError(
                            "attachment_redirect",
                            "The attachment exceeded the download redirect limit.",
                        )
                    current = urljoin(current, location)
                    continue
                if response.status_code in {401, 403, 404, 410}:
                    raise AdapterError(
                        "attachment_expired",
                        "The attachment link expired or is unavailable. Reattach the file to this conversation and retry the existing Plan.",
                        retryable=True,
                    )
                if response.status_code != 200 or response.headers.get(
                    "content-encoding", "identity"
                ).casefold() not in {"", "identity"}:
                    raise AdapterError(
                        "attachment_download_failed",
                        "The attachment host did not return an uncompressed file.",
                    )
                declared = response.headers.get("content-length")
                if declared is not None and (
                    not re.fullmatch(r"[0-9]{1,20}", declared) or int(declared) > cap
                ):
                    raise AdapterError(
                        "file_too_large",
                        "The attachment exceeds the remaining upload limit.",
                    )
                path = directory / attachment_name(
                    item, index, response.headers.get("content-type", "")
                )
                count = 0
                try:
                    with path.open("xb") as spool:
                        async for chunk in _raw_chunks(response):
                            if len(chunk) > cap - count:
                                raise AdapterError(
                                    "file_too_large",
                                    "The attachment exceeds the remaining upload limit.",
                                )
                            count += len(chunk)
                            spool.write(chunk)
                            await asyncio.sleep(0)
                    if count == 0:
                        raise AdapterError(
                            "empty_attachment", "Empty attachments cannot be uploaded."
                        )
                    if declared is not None and count != int(declared):
                        raise AdapterError(
                            "attachment_incomplete",
                            "The attachment download was incomplete. Reattach it and retry.",
                            retryable=True,
                        )
                except BaseException:
                    path.unlink(missing_ok=True)
                    raise
                return path, count
            except httpx.HTTPError:
                raise AdapterError(
                    "attachment_download_failed",
                    "The attachment download failed. Reattach the file and retry.",
                    retryable=True,
                ) from None
            finally:
                if response is not None:
                    await response.aclose()
    raise AdapterError(
        "attachment_redirect", "The attachment exceeded the download redirect limit."
    )


# @testable true
# @tests tests_unit/test_033d_mcp_attachments.py::test_spooling_has_one_total_limit_and_cleans_on_cancellation
# @tests tests_unit/test_033d_mcp_attachments.py::test_partial_downloads_clean_the_entire_spool_when_transfer_fails
# @matrix mcp-upload : remote cancellation cleanup bounds duplicate
@asynccontextmanager
async def spool_attachments(items, *, max_file_bytes, max_total_bytes):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_UPLOAD_FILES:
        raise AdapterError(
            "invalid_attachments", "Choose between one and twenty attachments."
        )
    ids = [item["file_id"] for item in items]
    urls = [item["download_url"] for item in items]
    if len(set(ids)) != len(ids) or len(set(urls)) != len(urls):
        raise AdapterError(
            "duplicate_attachment", "An attachment was selected more than once."
        )
    with tempfile.TemporaryDirectory(prefix="lagniappe-mcp-") as temporary:
        paths, total = [], 0
        for index, item in enumerate(items):
            directory = Path(temporary) / str(index)
            directory.mkdir(mode=0o700)
            path, count = await download_attachment(
                item, directory, index, cap=min(max_file_bytes, max_total_bytes - total)
            )
            total += count
            paths.append({"path": str(path)})
        yield paths
