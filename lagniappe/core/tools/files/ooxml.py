"""Bounded text extraction for Office Open XML files."""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
import os
import posixpath
import re
import struct
import tempfile
import time
import zipfile
from xml.parsers import expat

from ...definitions.file_consumers import LARGE_ASSET_BYTES


DOCX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OOXML_MIMETYPES = {DOCX_MIMETYPE: "docx", XLSX_MIMETYPE: "xlsx"}
OOXML_EXTENSIONS = {"docx": "docx", "xlsx": "xlsx"}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORKSHEET_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
)

MIB = 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
SPOOL_MEMORY_BYTES = MIB
EOCD_SIGNATURE = b"PK\x05\x06"
EOCD_STRUCT = struct.Struct("<4s4H2LH")
CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
CENTRAL_DIRECTORY_STRUCT = struct.Struct("<4s4B4HL2L5H2L")
ZIP64_UINT16 = 0xFFFF
ZIP64_UINT32 = 0xFFFFFFFF
ALLOWED_COMPRESSION_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}

CELL_REF_RE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
MAX_EXCEL_COLUMN = 16_384
MAX_EXCEL_ROW = 1_048_576


@dataclass(frozen=True)
class OOXMLPolicy:
    """Fixed resource contract for OOXML extraction."""

    compressed_bytes: int = LARGE_ASSET_BYTES
    central_directory_bytes: int = 4 * MIB
    member_count: int = 4_096
    member_name_bytes: int = 1_024
    member_bytes: int = 64 * MIB
    archive_bytes: int = 256 * MIB
    compression_ratio: float = 1_000.0
    compression_ratio_min_bytes: int = MIB
    xml_bytes: int = 64 * MIB
    xml_depth: int = 128
    xml_elements: int = 1_000_000
    seconds: float = 5.0
    sheets: int = 256
    rows: int = 100_000
    cells: int = 250_000
    shared_strings: int = 100_000
    shared_characters: int = 4_000_000
    output_characters: int = 200_000


OOXML_POLICY = OOXMLPolicy()


class OOXMLTruncationReason(Enum):
    """Why a safe extraction returned only a useful prefix."""

    OUTPUT = "output"
    XML_BYTES = "xml_bytes"
    ELEMENTS = "elements"
    SHEETS = "sheets"
    ROWS = "rows"
    CELLS = "cells"
    DEADLINE = "deadline"


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_output_budget_returns_typed_partial_result
# @pair files:partial-result
@dataclass(frozen=True)
class OOXMLExtractionResult:
    """Extracted text and explicit partial-result metadata."""

    text: str
    truncation_reason: OOXMLTruncationReason | None = None

    # @testable true
    # @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_output_budget_returns_typed_partial_result
    # @pair files:partial-result
    @property
    def truncated(self):
        return self.truncation_reason is not None


class OOXMLExtractionError(ValueError):
    """Raised when a supported OOXML file cannot be read safely as text."""


class _OOXMLPolicyError(ValueError):
    """Internal package or parser policy failure."""


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
class _PartialExtraction(Exception):
    """Internal bounded traversal stop with a visible reason."""

    def __init__(self, reason):
        super().__init__(reason.value)
        self.reason = reason


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_returns_partial_text_for_worksheet_work_limits
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_production_policy_defaults_are_fixed
# @matrix files : ooxml partial-result policy
@dataclass
class _ExtractionBudget:
    policy: OOXMLPolicy
    max_characters: int
    started_at: float
    xml_bytes: int = 0
    elements: int = 0
    sheets: int = 0
    rows: int = 0
    cells: int = 0

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def check_deadline(self):
        if time.monotonic() - self.started_at > self.policy.seconds:
            raise _PartialExtraction(OOXMLTruncationReason.DEADLINE)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def add_xml_bytes(self, size):
        if self.xml_bytes + size > self.policy.xml_bytes:
            raise _PartialExtraction(OOXMLTruncationReason.XML_BYTES)
        self.xml_bytes += size
        self.check_deadline()

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def add_element(self):
        self.elements += 1
        if self.elements > self.policy.xml_elements:
            raise _PartialExtraction(OOXMLTruncationReason.ELEMENTS)
        if self.elements % 256 == 0:
            self.check_deadline()

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def add_sheet(self):
        self.sheets += 1
        if self.sheets > self.policy.sheets:
            raise _PartialExtraction(OOXMLTruncationReason.SHEETS)
        self.check_deadline()

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def add_row(self):
        self.rows += 1
        if self.rows > self.policy.rows:
            raise _PartialExtraction(OOXMLTruncationReason.ROWS)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def add_cell(self):
        self.cells += 1
        if self.cells > self.policy.cells:
            raise _PartialExtraction(OOXMLTruncationReason.CELLS)


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_output_limit_does_not_parse_later_worksheets
# @matrix files : ooxml output-budget partial-result
class _TextOutput:
    def __init__(self, max_characters):
        self.max_characters = max_characters
        self.parts = []
        self.length = 0
        self.has_lines = False

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def _append(self, value):
        if not value:
            return
        remaining = self.max_characters - self.length
        if remaining <= 0:
            raise _PartialExtraction(OOXMLTruncationReason.OUTPUT)
        if len(value) > remaining:
            self.parts.append(value[:remaining])
            self.length += remaining
            raise _PartialExtraction(OOXMLTruncationReason.OUTPUT)
        self.parts.append(value)
        self.length += len(value)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def add_line(self, line):
        if not line or not line.strip():
            return
        prefix = "\n" if self.has_lines else ""
        self.has_lines = True
        self._append(f"{prefix}{line}")

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    @property
    def text(self):
        return "".join(self.parts).strip()


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
class _CappedText:
    def __init__(self, limit):
        self.limit = limit
        self.parts = []
        self.length = 0

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def append(self, value):
        if not value:
            return
        remaining = self.limit - self.length
        if remaining <= 0:
            return
        kept = value[:remaining]
        self.parts.append(kept)
        self.length += len(kept)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    @property
    def text(self):
        return "".join(self.parts)


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_summary_generation_uses_docx_text_fallback
# @tests tests_unit/test_015_ai_tools.py::test_ooxml_xlsx_extraction_preserves_rows_tabs_and_shared_strings
# @matrix ai files : ooxml summary-fallback
def is_supported_ooxml(filename=None, mimetype=None):
    """Return whether filename or MIME type identifies a supported OOXML file."""
    return _ooxml_kind(filename=filename, mimetype=mimetype) is not None


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_happy_paths_preserve_docx_and_xlsx_order
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_output_budget_returns_typed_partial_result
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_unsafe_archive_members_before_parsing
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_forbidden_or_malformed_xml
# @matrix files : bounded-resources docx ooxml partial-result xlsx
def extract_ooxml(content, filename=None, mimetype=None, *, max_characters=None):
    """Extract bounded rough text and partial-result metadata from DOCX/XLSX."""
    kind = _ooxml_kind(filename=filename, mimetype=mimetype)
    if kind is None:
        return None

    policy = OOXML_POLICY
    if max_characters is None:
        max_characters = policy.output_characters
    if (
        isinstance(max_characters, bool)
        or not isinstance(max_characters, int)
        or not 1 <= max_characters <= policy.output_characters
    ):
        raise ValueError(
            f"max_characters must be between 1 and {policy.output_characters}."
        )

    output = _TextOutput(max_characters)
    budget = _ExtractionBudget(policy, max_characters, time.monotonic())
    label = filename or "Office file"

    try:
        with _content_source(content, budget) as (stream, compressed_size):
            member_count = _preflight_central_directory(stream, compressed_size, budget)
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                members = _inspect_archive(archive, member_count, budget)
                if kind == "docx":
                    _extract_docx_text(archive, members, output, budget)
                elif kind == "xlsx":
                    _extract_xlsx_text(archive, members, output, budget)
    except _PartialExtraction as partial:
        text = output.text
        if text:
            return OOXMLExtractionResult(text, partial.reason)
        raise OOXMLExtractionError(f"Could not extract text from {label}.") from partial
    except OOXMLExtractionError:
        raise
    except (
        EOFError,
        OSError,
        RuntimeError,
        struct.error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        expat.ExpatError,
        _OOXMLPolicyError,
    ) as error:
        raise OOXMLExtractionError(f"Could not extract text from {label}.") from error

    return OOXMLExtractionResult(output.text)


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_summary_generation_uses_docx_text_fallback
# @tests tests_unit/test_015_ai_tools.py::test_ai_summary_generation_reports_ooxml_extraction_errors
# @tests tests_unit/test_015_ai_tools.py::test_ooxml_xlsx_extraction_preserves_rows_tabs_and_shared_strings
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_happy_paths_preserve_docx_and_xlsx_order
# @matrix files : compatibility docx ooxml summary-fallback xlsx
# @pair ai:ooxml
def extract_ooxml_text(content, filename=None, mimetype=None):
    """Compatibility wrapper returning only bounded extracted text."""
    result = extract_ooxml(content, filename=filename, mimetype=mimetype)
    return result.text if result is not None else None


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::is_supported_ooxml
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
# @reason type routing is owned by the public OOXML helpers
def _ooxml_kind(filename=None, mimetype=None):
    mimetype = (mimetype or "").lower()
    if mimetype in OOXML_MIMETYPES:
        return OOXML_MIMETYPES[mimetype]
    filename = str(filename or "").lower().rsplit("/", 1)[-1]
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    return OOXML_EXTENSIONS.get(extension)


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_bounds_input_streams_and_preserves_seekable_ownership
# @matrix files : compressed-limit input-stream ooxml
@contextmanager
def _content_source(content, budget):
    policy = budget.policy
    if isinstance(content, (bytes, bytearray, memoryview)):
        if len(content) > policy.compressed_bytes:
            raise _OOXMLPolicyError("Compressed OOXML input exceeds its byte limit.")
        stream = BytesIO(bytes(content))
        try:
            yield stream, len(content)
        finally:
            stream.close()
        return

    if not hasattr(content, "read"):
        raise _OOXMLPolicyError("OOXML content must be bytes or a readable file.")

    original_position = None
    try:
        original_position = content.tell()
        content.seek(0, os.SEEK_END)
        size = int(content.tell())
        content.seek(0)
    except (AttributeError, OSError, TypeError, ValueError):
        if original_position is not None:
            try:
                content.seek(original_position)
            except (AttributeError, OSError, TypeError, ValueError):
                pass
    else:
        if size < 0 or size > policy.compressed_bytes:
            try:
                content.seek(original_position)
            except (AttributeError, OSError, TypeError, ValueError):
                pass
            raise _OOXMLPolicyError("Compressed OOXML input exceeds its byte limit.")
        try:
            yield content, size
        finally:
            try:
                content.seek(original_position)
            except (AttributeError, OSError, TypeError, ValueError):
                pass
        return

    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b") as spool:
        size = 0
        while True:
            budget.check_deadline()
            remaining = policy.compressed_bytes + 1 - size
            chunk = content.read(min(READ_CHUNK_BYTES, remaining))
            if chunk in (b"", None):
                break
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise _OOXMLPolicyError("OOXML streams must return bytes.")
            chunk = bytes(chunk)
            spool.write(chunk)
            size += len(chunk)
            if size > policy.compressed_bytes:
                raise _OOXMLPolicyError("Compressed OOXML input exceeds its byte limit.")
        spool.seek(0)
        yield spool, size


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_central_directory_count_mismatch
# @matrix files : archive-safety central-directory ooxml
def _preflight_central_directory(stream, size, budget):
    policy = budget.policy
    if size < EOCD_STRUCT.size:
        raise _OOXMLPolicyError("OOXML input has no ZIP end record.")

    tail_size = min(size, EOCD_STRUCT.size + ZIP64_UINT16)
    stream.seek(size - tail_size)
    tail = stream.read(tail_size)
    offset = tail.rfind(EOCD_SIGNATURE)
    if offset < 0 or len(tail) - offset < EOCD_STRUCT.size:
        raise _OOXMLPolicyError("OOXML input has no ZIP end record.")

    fields = EOCD_STRUCT.unpack_from(tail, offset)
    (
        signature,
        disk_number,
        directory_disk,
        disk_entries,
        total_entries,
        directory_size,
        directory_offset,
        comment_size,
    ) = fields
    if signature != EOCD_SIGNATURE:
        raise _OOXMLPolicyError("OOXML input has an invalid ZIP end record.")
    if offset + EOCD_STRUCT.size + comment_size != len(tail):
        raise _OOXMLPolicyError("OOXML ZIP trailing data is not supported.")
    if disk_number or directory_disk or disk_entries != total_entries:
        raise _OOXMLPolicyError("Multidisk OOXML archives are not supported.")
    if total_entries == ZIP64_UINT16 or (
        directory_size == ZIP64_UINT32 or directory_offset == ZIP64_UINT32
    ):
        raise _OOXMLPolicyError("ZIP64 OOXML archives are not supported.")
    if total_entries > policy.member_count:
        raise _OOXMLPolicyError("OOXML archive has too many members.")
    if directory_size > policy.central_directory_bytes:
        raise _OOXMLPolicyError("OOXML central directory exceeds its byte limit.")

    eocd_offset = size - tail_size + offset
    if directory_offset + directory_size != eocd_offset:
        raise _OOXMLPolicyError("OOXML ZIP layout is not canonical.")

    stream.seek(directory_offset)
    directory = stream.read(directory_size)
    if len(directory) != directory_size:
        raise _OOXMLPolicyError("OOXML central directory is incomplete.")

    position = 0
    counted_entries = 0
    while position < len(directory):
        if len(directory) - position < CENTRAL_DIRECTORY_STRUCT.size:
            raise _OOXMLPolicyError("OOXML central directory entry is incomplete.")
        entry = CENTRAL_DIRECTORY_STRUCT.unpack_from(directory, position)
        if entry[0] != CENTRAL_DIRECTORY_SIGNATURE:
            raise _OOXMLPolicyError("OOXML central directory entry is invalid.")
        compressed_size = entry[10]
        file_size = entry[11]
        filename_size = entry[12]
        extra_size = entry[13]
        entry_comment_size = entry[14]
        disk_start = entry[15]
        header_offset = entry[18]
        if filename_size > policy.member_name_bytes:
            raise _OOXMLPolicyError("OOXML member name exceeds its byte limit.")
        if (
            compressed_size == ZIP64_UINT32
            or file_size == ZIP64_UINT32
            or header_offset == ZIP64_UINT32
            or disk_start == ZIP64_UINT16
        ):
            raise _OOXMLPolicyError("ZIP64 OOXML members are not supported.")
        entry_size = (
            CENTRAL_DIRECTORY_STRUCT.size
            + filename_size
            + extra_size
            + entry_comment_size
        )
        if entry_size > len(directory) - position:
            raise _OOXMLPolicyError("OOXML central directory entry is incomplete.")
        position += entry_size
        counted_entries += 1
        if counted_entries > policy.member_count:
            raise _OOXMLPolicyError("OOXML archive has too many members.")

    if position != len(directory) or counted_entries != total_entries:
        raise _OOXMLPolicyError("OOXML central directory count is inconsistent.")
    budget.check_deadline()
    return counted_entries


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_unsafe_archive_members_before_parsing
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_unsupported_compression_and_expansion
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_stream_reader_rejects_bytes_beyond_member_declaration
# @matrix files : archive-safety expansion ooxml streamed-member
def _inspect_archive(archive, expected_count, budget):
    policy = budget.policy
    infos = archive.infolist()
    if len(infos) != expected_count:
        raise _OOXMLPolicyError("OOXML archive member count changed after preflight.")

    members = {}
    canonical_names = {}
    total_size = 0
    for index, info in enumerate(infos):
        if index % 256 == 0:
            budget.check_deadline()
        name = _canonical_member_name(info)
        folded = name.casefold()
        if folded in canonical_names:
            raise _OOXMLPolicyError("OOXML archive contains ambiguous member names.")
        canonical_names[folded] = name
        if info.flag_bits & 0x1:
            raise _OOXMLPolicyError("Encrypted OOXML archive members are unsupported.")
        if info.compress_type not in ALLOWED_COMPRESSION_METHODS:
            raise _OOXMLPolicyError("OOXML member compression method is unsupported.")
        if info.file_size < 0 or info.compress_size < 0:
            raise _OOXMLPolicyError("OOXML archive contains invalid member sizes.")
        if info.file_size > policy.member_bytes:
            raise _OOXMLPolicyError("OOXML member exceeds its byte limit.")
        total_size += info.file_size
        if total_size > policy.archive_bytes:
            raise _OOXMLPolicyError("OOXML archive expansion exceeds its byte limit.")
        if info.file_size and not info.compress_size:
            raise _OOXMLPolicyError("OOXML member has an invalid compression ratio.")
        if (
            info.file_size >= policy.compression_ratio_min_bytes
            and info.file_size / info.compress_size > policy.compression_ratio
        ):
            raise _OOXMLPolicyError("OOXML member compression ratio is suspicious.")
        if not info.is_dir():
            members[name] = info
    return members


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
# @reason path normalization is exercised through public archive tests
def _canonical_member_name(info):
    original = str(getattr(info, "orig_filename", info.filename))
    filename = str(info.filename)
    if not original or "\x00" in original or original != filename:
        raise _OOXMLPolicyError("OOXML archive contains an invalid member name.")
    if original.startswith("/") or "\\" in original:
        raise _OOXMLPolicyError("OOXML archive member path is unsafe.")
    is_directory = original.endswith("/")
    candidate = original[:-1] if is_directory else original
    if not candidate or any(part in {"", ".", ".."} for part in candidate.split("/")):
        raise _OOXMLPolicyError("OOXML archive member path is unsafe.")
    if posixpath.normpath(candidate) != candidate:
        raise _OOXMLPolicyError("OOXML archive member path is unsafe.")
    return candidate


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_forbidden_or_malformed_xml
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_excessive_xml_depth
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_returns_partial_text_for_xml_work_limits
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_returns_partial_text_when_deadline_expires
# @matrix files : deadline ooxml partial-result xml-safety
def _parse_xml_member(archive, info, handler, budget):
    policy = budget.policy
    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True
    depth = 0

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def reject_xml_feature(*_args):
        raise _OOXMLPolicyError("OOXML XML contains a forbidden declaration.")

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def start_element(name, attributes):
        nonlocal depth
        depth += 1
        if depth > policy.xml_depth:
            raise _OOXMLPolicyError("OOXML XML nesting exceeds its limit.")
        budget.add_element()
        handler.start(name, attributes)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def end_element(name):
        nonlocal depth
        handler.end(name)
        depth -= 1

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = handler.data
    parser.StartDoctypeDeclHandler = reject_xml_feature
    parser.EntityDeclHandler = reject_xml_feature
    parser.UnparsedEntityDeclHandler = reject_xml_feature
    parser.NotationDeclHandler = reject_xml_feature
    parser.ExternalEntityRefHandler = reject_xml_feature
    parser.SkippedEntityHandler = reject_xml_feature
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    member_bytes = 0
    with archive.open(info) as member:
        while True:
            budget.check_deadline()
            chunk = member.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            member_bytes += len(chunk)
            if member_bytes > policy.member_bytes or member_bytes > info.file_size:
                raise _OOXMLPolicyError("OOXML member exceeded its declared size.")
            budget.add_xml_bytes(len(chunk))
            parser.Parse(chunk, False)
        if member_bytes != info.file_size:
            raise _OOXMLPolicyError("OOXML member size did not match its declaration.")
        parser.Parse(b"", True)
    budget.check_deadline()
    return handler.finish()


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
def _w_tag(local_name):
    return f"{W_NS}}}{local_name}"


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
def _s_tag(local_name):
    return f"{S_NS}}}{local_name}"


W_BODY = _w_tag("body")
W_PARAGRAPH = _w_tag("p")
W_TABLE = _w_tag("tbl")
W_ROW = _w_tag("tr")
W_CELL = _w_tag("tc")
W_TEXT = _w_tag("t")
W_TAB = _w_tag("tab")
W_BREAK = _w_tag("br")
W_CARRIAGE_RETURN = _w_tag("cr")
S_SHEET = _s_tag("sheet")
S_SHARED_ITEM = _s_tag("si")
S_TEXT = _s_tag("t")
S_ROW = _s_tag("row")
S_CELL = _s_tag("c")
S_VALUE = _s_tag("v")
RELATIONSHIP = f"{PKG_REL_NS}}}Relationship"
RELATIONSHIP_ID = f"{R_NS}}}id"


@dataclass
class _ParagraphState:
    depth: int
    direct: bool
    text: _CappedText


@dataclass
class _CellState:
    depth: int
    text: _CappedText


@dataclass
class _RowState:
    depth: int
    line: _CappedText
    cell_count: int
    descendants: _CappedText


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
class _DocxHandler:
    def __init__(self, output, budget):
        self.output = output
        self.budget = budget
        self.stack = []
        self.body_index = None
        self.paragraphs = []
        self.cells = []
        self.rows = []
        self.text_depth = 0

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def _top_body_child(self):
        if self.body_index is None or len(self.stack) <= self.body_index + 1:
            return None
        return self.stack[self.body_index + 1]

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def start(self, name, _attributes):
        parent = self.stack[-1] if self.stack else None
        self.stack.append(name)
        depth = len(self.stack)
        if name == W_BODY and self.body_index is None:
            self.body_index = depth - 1
        top = self._top_body_child()
        included = top in {W_PARAGRAPH, W_TABLE}
        if name == W_ROW and top == W_TABLE:
            limit = self.budget.max_characters + 1
            self.rows.append(
                _RowState(depth, _CappedText(limit), 0, _CappedText(limit))
            )
        elif name == W_CELL and top == W_TABLE:
            self.cells.append(
                _CellState(depth, _CappedText(self.budget.max_characters + 1))
            )
        elif name == W_PARAGRAPH and included:
            self.paragraphs.append(
                _ParagraphState(
                    depth,
                    parent == W_BODY,
                    _CappedText(self.budget.max_characters + 1),
                )
            )
        elif name == W_TEXT and self.paragraphs:
            self.text_depth += 1
        elif name == W_TAB and self.paragraphs:
            self.paragraphs[-1].text.append("\t")
        elif name in {W_BREAK, W_CARRIAGE_RETURN} and self.paragraphs:
            self.paragraphs[-1].text.append("\n")

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def end(self, name):
        depth = len(self.stack)
        top = self._top_body_child()
        if name == W_TEXT and self.text_depth:
            self.text_depth -= 1
        elif (
            name == W_PARAGRAPH
            and self.paragraphs
            and self.paragraphs[-1].depth == depth
        ):
            paragraph = self.paragraphs.pop()
            text = paragraph.text.text.strip()
            if paragraph.direct:
                self.output.add_line(text)
            elif top == W_TABLE and text:
                for cell in self.cells:
                    if cell.text.length:
                        cell.text.append(" ")
                    cell.text.append(text)
        elif name == W_CELL and self.cells and self.cells[-1].depth == depth:
            cell = self.cells.pop()
            if self.rows:
                row = self.rows[-1]
                if row.cell_count:
                    row.line.append("\t")
                row.line.append(cell.text.text)
                row.cell_count += 1
        elif name == W_ROW and self.rows and self.rows[-1].depth == depth:
            row = self.rows.pop()
            line = row.line.text.strip()
            descendants = row.descendants.text.strip()
            if self.rows:
                parent = self.rows[-1].descendants
                if parent.length and (line or descendants):
                    parent.append("\n")
                if line:
                    parent.append(line)
                if line and descendants:
                    parent.append("\n")
                parent.append(descendants)
            else:
                self.output.add_line(line)
                self.output.add_line(descendants)
        if name == W_BODY and self.body_index == depth - 1:
            self.body_index = None
        self.stack.pop()

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def data(self, value):
        if self.text_depth and self.paragraphs:
            self.paragraphs[-1].text.append(value)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def finish(self):
        return None


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
class _WorkbookHandler:
    def __init__(self, policy):
        self.policy = policy
        self.relationship_ids = []
        self.seen = set()

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def start(self, name, attributes):
        if name != S_SHEET:
            return
        if len(self.relationship_ids) > self.policy.sheets:
            return
        relationship_id = attributes.get(RELATIONSHIP_ID)
        if not relationship_id or relationship_id in self.seen:
            raise _OOXMLPolicyError("OOXML workbook sheet relationships are invalid.")
        self.seen.add(relationship_id)
        if len(self.relationship_ids) <= self.policy.sheets:
            self.relationship_ids.append(relationship_id)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def end(self, _name):
        return None

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def data(self, _value):
        return None

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def finish(self):
        return self.relationship_ids


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
class _RelationshipsHandler:
    def __init__(self, wanted_ids):
        self.wanted_ids = set(wanted_ids)
        self.relationships = {}

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def start(self, name, attributes):
        if name != RELATIONSHIP:
            return
        relationship_id = attributes.get("Id")
        if relationship_id not in self.wanted_ids:
            return
        if relationship_id in self.relationships:
            raise _OOXMLPolicyError("OOXML workbook relationships are ambiguous.")
        self.relationships[relationship_id] = {
            "type": attributes.get("Type"),
            "target": attributes.get("Target"),
            "target_mode": attributes.get("TargetMode"),
        }

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def end(self, _name):
        return None

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def data(self, _value):
        return None

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def finish(self):
        return self.relationships


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
class _SharedStringsHandler:
    def __init__(self, policy):
        self.policy = policy
        self.strings = []
        self.current = None
        self.text_depth = 0
        self.characters = 0

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def start(self, name, _attributes):
        if name == S_SHARED_ITEM:
            if self.current is not None:
                raise _OOXMLPolicyError("OOXML shared strings are malformed.")
            self.current = []
        elif name == S_TEXT and self.current is not None:
            self.text_depth += 1

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def end(self, name):
        if name == S_TEXT and self.text_depth:
            self.text_depth -= 1
        elif name == S_SHARED_ITEM and self.current is not None:
            if len(self.strings) >= self.policy.shared_strings:
                raise _OOXMLPolicyError("OOXML shared string count exceeds its limit.")
            self.strings.append("".join(self.current))
            self.current = None

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def data(self, value):
        if not self.text_depth or self.current is None or not value:
            return
        if self.characters + len(value) > self.policy.shared_characters:
            raise _OOXMLPolicyError("OOXML shared string text exceeds its limit.")
        self.current.append(value)
        self.characters += len(value)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def finish(self):
        return self.strings


@dataclass
class _WorksheetCell:
    depth: int
    reference: str | None
    cell_type: str | None
    value: _CappedText
    inline: _CappedText
    value_depth: int = 0
    inline_depth: int = 0


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
class _WorksheetHandler:
    def __init__(self, shared_strings, output, budget):
        self.shared_strings = shared_strings
        self.output = output
        self.budget = budget
        self.depth = 0
        self.row_depth = None
        self.row_values = None
        self.row_length = 0
        self.cell = None

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def start(self, name, attributes):
        self.depth += 1
        if name == S_ROW and self.row_values is None:
            self.budget.add_row()
            self.row_depth = self.depth
            self.row_values = {}
            self.row_length = 0
        elif name == S_CELL and self.row_values is not None and self.cell is None:
            self.budget.add_cell()
            limit = self.budget.max_characters + 1
            self.cell = _WorksheetCell(
                self.depth,
                attributes.get("r"),
                attributes.get("t"),
                _CappedText(limit),
                _CappedText(limit),
            )
        elif name == S_VALUE and self.cell is not None:
            self.cell.value_depth += 1
        elif name == S_TEXT and self.cell is not None:
            self.cell.inline_depth += 1

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def end(self, name):
        if name == S_VALUE and self.cell is not None and self.cell.value_depth:
            self.cell.value_depth -= 1
        elif name == S_TEXT and self.cell is not None and self.cell.inline_depth:
            self.cell.inline_depth -= 1
        elif name == S_CELL and self.cell is not None and self.cell.depth == self.depth:
            self._finish_cell()
        elif name == S_ROW and self.row_values is not None and self.row_depth == self.depth:
            self._finish_row()
        self.depth -= 1

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def data(self, value):
        if self.cell is None:
            return
        if self.cell.value_depth:
            self.cell.value.append(value)
        elif self.cell.inline_depth:
            self.cell.inline.append(value)

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def _finish_cell(self):
        cell = self.cell
        index = _column_index(cell.reference)
        if index is None:
            index = self.row_length
            if index >= MAX_EXCEL_COLUMN:
                raise _OOXMLPolicyError("OOXML row exceeds the Excel column limit.")
        value = cell.inline.text if cell.cell_type == "inlineStr" else cell.value.text
        if cell.cell_type == "s" and value:
            try:
                value = self.shared_strings[int(value)]
            except (ValueError, IndexError):
                pass
        self.row_values[index] = value
        self.row_length = max(self.row_length, index + 1)
        self.cell = None

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def _finish_row(self):
        line = _CappedText(self.budget.max_characters + 1)
        previous_index = None
        for index, value in sorted(self.row_values.items()):
            if value == "":
                continue
            tab_count = index if previous_index is None else index - previous_index
            line.append("\t" * tab_count)
            line.append(value)
            previous_index = index
        self.output.add_line(line.text)
        self.row_depth = None
        self.row_values = None
        self.row_length = 0

    # @testable false
    # @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
    def finish(self):
        return None


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
# @reason DOCX streaming behavior is exercised through public extraction tests
def _extract_docx_text(archive, members, output, budget):
    info = members.get("word/document.xml")
    if info is None:
        raise _OOXMLPolicyError("OOXML document part is missing.")
    _parse_xml_member(archive, info, _DocxHandler(output, budget), budget)


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
# @reason XLSX package traversal is exercised through public extraction tests
def _extract_xlsx_text(archive, members, output, budget):
    sheet_paths = _workbook_sheet_paths(archive, members, budget)
    shared_strings = _shared_strings(archive, members, budget)
    for path in sheet_paths:
        budget.add_sheet()
        info = members.get(path)
        if info is None:
            raise _OOXMLPolicyError("OOXML worksheet part is missing.")
        _parse_xml_member(
            archive,
            info,
            _WorksheetHandler(shared_strings, output, budget),
            budget,
        )


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_unsafe_worksheet_relationships
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_fallback_worksheets_use_natural_order
# @matrix files : fallback ooxml relationships xlsx
# @reason workbook relationship policy is exercised through XLSX extraction tests
def _workbook_sheet_paths(archive, members, budget):
    workbook_info = members.get("xl/workbook.xml")
    relationships_info = members.get("xl/_rels/workbook.xml.rels")
    if workbook_info is None or relationships_info is None:
        return _fallback_sheet_paths(members)

    relationship_ids = _parse_xml_member(
        archive,
        workbook_info,
        _WorkbookHandler(budget.policy),
        budget,
    )
    relationships = _parse_xml_member(
        archive,
        relationships_info,
        _RelationshipsHandler(relationship_ids),
        budget,
    )

    paths = []
    seen_paths = set()
    for relationship_id in relationship_ids:
        relationship = relationships.get(relationship_id)
        if relationship is None:
            raise _OOXMLPolicyError("OOXML worksheet relationship is missing.")
        if relationship["type"] not in {None, WORKSHEET_REL_TYPE}:
            raise _OOXMLPolicyError("OOXML worksheet relationship type is invalid.")
        target_mode = relationship["target_mode"]
        if target_mode and target_mode.casefold() != "internal":
            raise _OOXMLPolicyError("External OOXML worksheets are unsupported.")
        path = _worksheet_target_path(relationship["target"])
        if path in seen_paths or path not in members:
            raise _OOXMLPolicyError("OOXML worksheet relationship target is invalid.")
        seen_paths.add(path)
        paths.append(path)
    return paths


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
# @reason fallback ordering is part of XLSX extraction behavior
def _fallback_sheet_paths(members):
    paths = [
        name
        for name in members
        if name.startswith("xl/worksheets/") and name.endswith(".xml")
    ]
    return sorted(paths, key=_natural_key)


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
# @reason relationship target normalization is exercised through extraction tests
def _worksheet_target_path(target):
    if (
        not target
        or "\x00" in target
        or "\\" in target
        or "?" in target
        or "#" in target
    ):
        raise _OOXMLPolicyError("OOXML worksheet relationship target is unsafe.")
    target_path = target.lstrip("/") if target.startswith("/") else target
    if any(part in {"", ".", ".."} for part in target_path.split("/")):
        raise _OOXMLPolicyError("OOXML worksheet relationship target is unsafe.")
    candidate = (
        target_path if target.startswith("/") else posixpath.join("xl", target_path)
    )
    path = posixpath.normpath(candidate)
    if not path.startswith("xl/worksheets/") or not path.endswith(".xml"):
        raise _OOXMLPolicyError("OOXML worksheet relationship target is unsafe.")
    return path


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_bounds_shared_string_storage_and_fanout
# @matrix files : ooxml shared-strings xlsx
def _shared_strings(archive, members, budget):
    info = members.get("xl/sharedStrings.xml")
    if info is None:
        return []
    return _parse_xml_member(
        archive,
        info,
        _SharedStringsHandler(budget.policy),
        budget,
    )


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml
# @reason natural sorting is support logic for XLSX fallback paths
def _natural_key(value):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


# @testable true
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_rejects_out_of_domain_cell_references
# @tests tests_unit/test_015d_ooxml_extraction.py::test_ooxml_accepts_xfd_without_unbounded_padding
# @matrix files : cell-reference ooxml sparse-row xlsx
def _column_index(cell_ref):
    if cell_ref in (None, ""):
        return None
    match = CELL_REF_RE.fullmatch(str(cell_ref))
    if not match:
        raise _OOXMLPolicyError("OOXML cell reference is invalid.")
    total = 0
    for char in match.group(1):
        total = total * 26 + ord(char) - ord("A") + 1
    row = int(match.group(2))
    if total > MAX_EXCEL_COLUMN or row > MAX_EXCEL_ROW:
        raise _OOXMLPolicyError("OOXML cell reference exceeds Excel limits.")
    return total - 1
