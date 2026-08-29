"""File encoding and MIME detection."""

import filetype

from .constants import ENCODINGS, TEXT_MIMETYPES


MIME_SAMPLE_BYTES = 8192
GENERIC_MIMETYPES = {None, "", "application/octet-stream", "text/plain"}


# @testable false
# @covered-by lagniappe/core/tools/files/utility.py::determine_encoding
# @covered-by lagniappe/core/tools/files/utility.py::determine_mimetype
# @reason sample positioning is exercised through the upload metadata helpers
def _upload_sample(upload, size=MIME_SAMPLE_BYTES):
    if hasattr(upload, "read_sample"):
        return upload.read_sample(size)
    position = None
    try:
        position = upload.tell()
    except Exception:
        pass
    upload.seek(0)
    sample = upload.read(size)
    try:
        upload.seek(position or 0)
    except Exception:
        pass
    return sample or b""


# @testable false
# @covered-by lagniappe/core/properties/file_assets.py::FileAsset
# @covered-by lagniappe/core/tools/files/utility.py::determine_mimetype
# @reason upload metadata decisions are owned by the file asset upload contract
def determine_encoding(upload):
    """Detect the character encoding of an uploaded file by trial decoding."""
    sample = _upload_sample(upload, 1024)
    for encoding in ENCODINGS:
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return None


# @testable false
# @covered-by lagniappe/core/properties/file_assets.py::FileAsset
# @reason upload metadata decisions are owned by the file asset upload contract
def determine_mimetype(upload, filename, mimetype, encoding):
    """Resolve an upload MIME type from magic bytes and its extension."""
    if mimetype in GENERIC_MIMETYPES:
        kind = filetype.guess(_upload_sample(upload))
        if kind:
            return kind.mime
        if encoding:
            extension = filename.split(".")[-1]
            return TEXT_MIMETYPES.get(extension, "text/plain")
    return mimetype
