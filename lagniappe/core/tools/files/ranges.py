"""HTTP byte range helpers for file previews."""

from dataclasses import dataclass
import re

BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class UnsatisfiableByteRange(ValueError):
    """Raised when a byte range is validly formed but outside the resource."""


# @testable true
# @tests tests_unit/test_006d_file_ranges.py::test_parse_byte_range_standard_and_suffix_forms
# @tests tests_unit/test_006d_file_ranges.py::test_parse_byte_range_rejects_invalid_headers
# @features file preview
# @dimensions byte-range
@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int
    size: int

    @property
    def length(self):
        return self.end - self.start + 1

    @property
    def content_range(self):
        return f"bytes {self.start}-{self.end}/{self.size}"


# @testable true
# @tests tests_unit/test_006d_file_ranges.py::test_parse_byte_range_standard_and_suffix_forms
# @tests tests_unit/test_006d_file_ranges.py::test_parse_byte_range_rejects_invalid_headers
# @tests tests_unit/test_006d_file_ranges.py::test_parse_byte_range_raises_for_unsatisfiable_ranges
# @features file preview
# @dimensions byte-range
def parse_byte_range(header, size):
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
