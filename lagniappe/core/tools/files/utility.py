"""File encoding and MIME detection."""

from contextlib import suppress
from typing import TYPE_CHECKING, BinaryIO, Protocol

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage
import filetype

from .constants import ENCODINGS, TEXT_MIMETYPES


class SampleReader(Protocol):
    def read_sample(self, size: int, /) -> bytes: ...


MIME_SAMPLE_BYTES = 8192
GENERIC_MIMETYPES = {None, "", "application/octet-stream", "text/plain"}


def _upload_sample(upload, size=MIME_SAMPLE_BYTES):
    if hasattr(upload, "read_sample"):
        return upload.read_sample(size)
    position = None
    with suppress(Exception):
        position = upload.tell()
    upload.seek(0)
    sample = upload.read(size)
    with suppress(Exception):
        upload.seek(position or 0)
    return sample or b""


def determine_encoding(upload: BinaryIO | SampleReader | FileStorage) -> str | None:
    """Detect the character encoding of an uploaded file by trial decoding."""
    sample = _upload_sample(upload, 1024)
    for encoding in ENCODINGS:
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return None


def determine_mimetype(upload: BinaryIO | SampleReader | FileStorage, filename: str | None, mimetype: str | None, encoding: str | None) -> str:
    """Resolve an upload MIME type from magic bytes and its extension."""
    mimetype = str(mimetype or "").partition(";")[0].strip().casefold()
    if mimetype in GENERIC_MIMETYPES:
        kind = filetype.guess(_upload_sample(upload))
        if kind:
            return kind.mime
        if encoding:
            extension = (filename or "").split(".")[-1]
            return TEXT_MIMETYPES.get(extension, "text/plain")
    return mimetype
