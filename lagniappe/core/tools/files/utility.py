"""File encoding and MIME detection."""

from codecs import getincrementaldecoder
from contextlib import suppress
import re
from typing import TYPE_CHECKING, BinaryIO, Protocol

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage
import filetype

from .constants import ENCODINGS, TEXT_MIMETYPES


class SampleReader(Protocol):
    def read_sample(self, size: int, /) -> bytes: ...


MIME_SAMPLE_BYTES = 8192
GENERIC_MIMETYPES = {None, "", "application/octet-stream", "text/plain"}
_TEXT_DOCUMENT_EXTENSIONS = {"txt", "md", "json", "vcf"}
_BINARY_CONTROLS = re.compile(rb"[\x00-\x08\x0b\x0e-\x1f\x7f]")


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
        sample = _upload_sample(upload)
        kind = filetype.guess(sample)
        if kind:
            return kind.mime
        extension = (filename or "").rpartition(".")[2].casefold()
        if encoding:
            return TEXT_MIMETYPES.get(extension, "text/plain")
        # Some browsers supply no media type or encoding for ordinary documents.
        # The prefix can end in the middle of a valid UTF-8 character.
        if extension in _TEXT_DOCUMENT_EXTENSIONS and sample and not _BINARY_CONTROLS.search(sample):
            try:
                getincrementaldecoder("utf-8")().decode(sample, final=len(sample) < MIME_SAMPLE_BYTES)
            except UnicodeDecodeError:
                return mimetype
            return TEXT_MIMETYPES[extension]
    return mimetype
