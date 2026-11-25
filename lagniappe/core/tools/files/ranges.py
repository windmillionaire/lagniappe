"""HTTP byte range helpers for file previews."""

from dataclasses import dataclass
import re

BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class UnsatisfiableByteRange(ValueError):
    """Raised when a byte range is validly formed but outside the resource."""


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int
    size: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def content_range(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.size}"


def parse_byte_range(header: str | None, size: int) -> ByteRange | None:
    """Parse a single HTTP byte range against a known resource size."""
    if not header or not isinstance(header, str):
        return None
    if size is None or size < 1:
        return None

    match = BYTE_RANGE.fullmatch(header.strip())
    if not match:
        return None

    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None

    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(size - suffix_length, 0)
            end = size - 1
    except ValueError:
        return None

    if start >= size or end < start:
        raise UnsatisfiableByteRange(header)

    return ByteRange(start=start, end=min(end, size - 1), size=size)
