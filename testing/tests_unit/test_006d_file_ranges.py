import pytest

from lagniappe.core.tools.files import ranges as file_ranges


# @matrix file preview : byte-range
@pytest.mark.unit
def test_parse_byte_range_standard_and_suffix_forms():
    byte_range = file_ranges.parse_byte_range("bytes=10-19", 100)

    assert byte_range.start == 10
    assert byte_range.end == 19
    assert byte_range.length == 10
    assert byte_range.content_range == "bytes 10-19/100"

    open_ended = file_ranges.parse_byte_range("bytes=95-", 100)
    assert open_ended.start == 95
    assert open_ended.end == 99

    suffix = file_ranges.parse_byte_range("bytes=-25", 100)
    assert suffix.start == 75
    assert suffix.end == 99

    oversized_suffix = file_ranges.parse_byte_range("bytes=-125", 100)
    assert oversized_suffix.start == 0
    assert oversized_suffix.end == 99


# @matrix file preview : byte-range invalid-header
@pytest.mark.unit
def test_parse_byte_range_rejects_invalid_headers():
    assert file_ranges.parse_byte_range(None, 100) is None
    assert file_ranges.parse_byte_range("", 100) is None
    assert file_ranges.parse_byte_range("items=0-10", 100) is None
    assert file_ranges.parse_byte_range("bytes=0-10,20-30", 100) is None
    assert file_ranges.parse_byte_range("bytes=-0", 100) is None
    assert file_ranges.parse_byte_range("bytes=-", 100) is None
    assert file_ranges.parse_byte_range("bytes=0-a", 100) is None
    assert file_ranges.parse_byte_range("bytes=0-10", 0) is None


# @matrix file preview : byte-range unsatisfiable
@pytest.mark.unit
def test_parse_byte_range_raises_for_unsatisfiable_ranges():
    with pytest.raises(file_ranges.UnsatisfiableByteRange):
        file_ranges.parse_byte_range("bytes=100-120", 100)

    with pytest.raises(file_ranges.UnsatisfiableByteRange):
        file_ranges.parse_byte_range("bytes=30-20", 100)
