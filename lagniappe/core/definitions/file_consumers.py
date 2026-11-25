"""Explicit byte limits for file consumers that inspect uploaded content."""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


@runtime_checkable
class _Seekable(Protocol):
    def seek(self, offset: int, whence: int = 0, /) -> object: ...
    def tell(self) -> int: ...



MIB = 1024 * 1024
LARGE_ASSET_BYTES = 30 * MIB
INDIVIDUAL_FILES_ONLY_ERROR = "Only individual files are supported"


class FileConsumer(Enum):
    """Named reasons an application path may inspect file content."""

    STORAGE_COPY = "storage-copy"
    MIME_SAMPLE = "mime-sample"
    AI_INLINE = "ai-inline"
    AI_REPORT = "ai-report"
    AI_EMAIL_ATTACHMENT = "ai-email-attachment"
    CSV_INGRESS = "csv-ingress"
    OOXML_EXTRACTION = "ooxml-extraction"
    TEXT_PREVIEW = "text-preview"
    IMAGE_FINGERPRINT = "image-fingerprint"
    SITE_IMAGE = "site-image"


@dataclass(frozen=True)
class FileConsumerCapability:
    """Resource contract for one named file consumer."""

    label: str
    max_bytes: int | None
    materializes_full_object: bool


FILE_CONSUMER_CAPABILITIES = {
    FileConsumer.STORAGE_COPY: FileConsumerCapability("storage copy", None, False),
    FileConsumer.MIME_SAMPLE: FileConsumerCapability("MIME detection", 8192, False),
    FileConsumer.AI_INLINE: FileConsumerCapability(
        "AI autofill attachment", 30 * MIB, True
    ),
    FileConsumer.AI_REPORT: FileConsumerCapability("AI report input", None, False),
    FileConsumer.AI_EMAIL_ATTACHMENT: FileConsumerCapability(
        "AI email attachment", 30 * MIB, True
    ),
    FileConsumer.CSV_INGRESS: FileConsumerCapability("CSV import", 30 * MIB, True),
    FileConsumer.OOXML_EXTRACTION: FileConsumerCapability(
        "Office document text extraction", 30 * MIB, True
    ),
    FileConsumer.TEXT_PREVIEW: FileConsumerCapability(
        "text preview", 30 * MIB, True
    ),
    FileConsumer.IMAGE_FINGERPRINT: FileConsumerCapability(
        "image fingerprinting", 100 * MIB, True
    ),
    FileConsumer.SITE_IMAGE: FileConsumerCapability(
        "site image processing", 100 * MIB, True
    ),
}


class FileConsumerLimitError(ValueError):
    """Raised before a file consumer would exceed its byte contract."""

    def __init__(
        self,
        message: str,
        *,
        consumer: FileConsumer | None,
        size: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.consumer = consumer
        self.size = size
        self.max_bytes = max_bytes


def known_file_size(source: object) -> int | None:
    """Return a file-like object's byte size without reading its contents."""
    if isinstance(source, int):
        return source
    if isinstance(source, (bytes, bytearray, memoryview)):
        return len(source)

    value = getattr(source, "size", None)
    if value not in (None, ""):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass

    value = getattr(source, "content_length", None)
    if value not in (None, ""):
        try:
            value = int(value)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    stream = getattr(source, "stream", source)
    try:
        if not isinstance(stream, _Seekable):
            return None
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(position)
        return int(size)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _megabyte_label(size):
    megabytes = size / MIB
    return str(int(megabytes)) if megabytes.is_integer() else f"{megabytes:.1f}"


def enforce_file_consumer(
    source: object,
    consumer: FileConsumer | str,
    *,
    filename: str | None = None,
    size: int | None = None,
) -> int | None:
    """Authorize a named consumer after checking size without reading bytes."""
    if not isinstance(consumer, FileConsumer):
        consumer = FileConsumer(consumer)
    capability = FILE_CONSUMER_CAPABILITIES[consumer]
    size = known_file_size(source) if size is None else int(size)

    if capability.max_bytes is not None and size is None:
        raise FileConsumerLimitError(
            f"Could not determine the file size before {capability.label}.",
            consumer=consumer,
            max_bytes=capability.max_bytes,
        )

    if capability.max_bytes is not None and size is not None and size > capability.max_bytes:
        name = f"{filename} is" if filename else "File is"
        raise FileConsumerLimitError(
            f"{name} too large for {capability.label} "
            f"({_megabyte_label(size)} MB). Maximum size is "
            f"{_megabyte_label(capability.max_bytes)} MB.",
            consumer=consumer,
            size=size,
            max_bytes=capability.max_bytes,
        )

    authorize = getattr(source, "_authorize_file_consumer", None)
    if callable(authorize):
        authorize(consumer)
    return size
