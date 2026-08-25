"""Bounded DOCX/XLSX extraction contracts."""

from dataclasses import replace
from io import BytesIO
import struct
from types import SimpleNamespace
import warnings
import zipfile

import pytest

from lagniappe.core.tools.files import (
    OOXMLExtractionResult,
    OOXMLTruncationReason,
    extract_ooxml,
    extract_ooxml_text,
)
from lagniappe.core.tools.files.ooxml import OOXMLExtractionError
import lagniappe.core.tools.files.ooxml as ooxml


pytestmark = pytest.mark.unit

DOCX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DEFAULT_POLICY = ooxml.OOXML_POLICY


def _zip_bytes(members, *, compression=zipfile.ZIP_DEFLATED):
    buffer = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
            for name, value in members:
                if isinstance(value, str):
                    value = value.encode("utf-8")
                archive.writestr(name, value)
    return buffer.getvalue()


def _docx_bytes(body):
    return _zip_bytes(
        [
            (
                "word/document.xml",
                f"""
                <w:document xmlns:w="{ooxml.W_NS}">
                  <w:body>{body}</w:body>
                </w:document>
                """,
            )
        ]
    )


def _worksheet(rows):
    return f"""
        <worksheet xmlns="{ooxml.S_NS}">
          <sheetData>{rows}</sheetData>
        </worksheet>
    """


def _inline_row(row, value, *, reference="A1"):
    return f"""
        <row r="{row}">
          <c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>
        </row>
    """


def _xlsx_bytes(
    sheets,
    *,
    shared_strings=None,
    targets=None,
    relationship_type=ooxml.WORKSHEET_REL_TYPE,
    target_mode=None,
):
    targets = targets or [f"worksheets/sheet{index}.xml" for index in range(1, len(sheets) + 1)]
    sheet_tags = "".join(
        f'<sheet name="Sheet {index}" sheetId="{index}" r:id="rId{index}"/>'
        for index in range(1, len(sheets) + 1)
    )
    relationship_tags = []
    for index, target in enumerate(targets, 1):
        type_attribute = (
            f' Type="{relationship_type}"' if relationship_type is not None else ""
        )
        mode_attribute = f' TargetMode="{target_mode}"' if target_mode else ""
        relationship_tags.append(
            f'<Relationship Id="rId{index}"{type_attribute} '
            f'Target="{target}"{mode_attribute}/>'
        )
    members = [
        (
            "xl/workbook.xml",
            f"""
            <workbook xmlns="{ooxml.S_NS}" xmlns:r="{ooxml.R_NS}">
              <sheets>{sheet_tags}</sheets>
            </workbook>
            """,
        ),
        (
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{ooxml.PKG_REL_NS}">'
            f'{"".join(relationship_tags)}</Relationships>',
        ),
    ]
    if shared_strings is not None:
        items = "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
        members.append(
            (
                "xl/sharedStrings.xml",
                f'<sst xmlns="{ooxml.S_NS}">{items}</sst>',
            )
        )
    members.extend(
        (f"xl/worksheets/sheet{index}.xml", sheet)
        for index, sheet in enumerate(sheets, 1)
    )
    return _zip_bytes(members)


def _set_policy(monkeypatch, **changes):
    values = {"seconds": 60.0, **changes}
    policy = replace(DEFAULT_POLICY, **values)
    monkeypatch.setattr(ooxml, "OOXML_POLICY", policy)
    return policy


# @matrix files : compatibility docx ooxml xlsx
def test_ooxml_happy_paths_preserve_docx_and_xlsx_order():
    docx = _docx_bytes(
        """
        <w:p><w:r><w:t>Alpha</w:t><w:tab/><w:t>Beta</w:t></w:r></w:p>
        <w:tbl><w:tr>
          <w:tc><w:p><w:r><w:t>Left</w:t></w:r></w:p></w:tc>
          <w:tc><w:p><w:r><w:t>Right</w:t></w:r></w:p></w:tc>
        </w:tr></w:tbl>
        """
    )
    xlsx = _xlsx_bytes(
        [
            _worksheet(
                """
                <row r="1">
                  <c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>
                </row>
                <row r="2">
                  <c r="A2" t="s"><v>2</v></c><c r="B2"><v>2</v></c>
                </row>
                """
            )
        ],
        shared_strings=["Name", "Team", "Alice"],
    )

    docx_result = extract_ooxml(docx, filename="notes.docx")
    xlsx_result = extract_ooxml(xlsx, mimetype=XLSX_MIMETYPE)

    assert docx_result == OOXMLExtractionResult("Alpha\tBeta\nLeft\tRight")
    assert xlsx_result == OOXMLExtractionResult("Name\tTeam\nAlice\t2")
    assert extract_ooxml_text(docx, mimetype=DOCX_MIMETYPE) == docx_result.text


# @matrix files : ooxml partial-result
def test_ooxml_output_budget_returns_typed_partial_result():
    exact = _docx_bytes("<w:p><w:r><w:t>12345</w:t></w:r></w:p>")
    over = _docx_bytes(
        "<w:p><w:r><w:t>12345</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>later</w:t></w:r></w:p>"
    )

    exact_result = extract_ooxml(exact, filename="exact.docx", max_characters=5)
    partial_result = extract_ooxml(over, filename="over.docx", max_characters=5)

    assert exact_result == OOXMLExtractionResult("12345")
    assert partial_result.text == "12345"
    assert partial_result.truncated is True
    assert partial_result.truncation_reason == OOXMLTruncationReason.OUTPUT


# @matrix files : ooxml output-budget partial-result
def test_ooxml_output_limit_does_not_parse_later_worksheets():
    content = _xlsx_bytes(
        [
            _worksheet(_inline_row(1, "abcdefgh")),
            "<worksheet><broken>",
        ]
    )

    result = extract_ooxml(content, filename="early.xlsx", max_characters=5)

    assert result == OOXMLExtractionResult("abcde", OOXMLTruncationReason.OUTPUT)


# @matrix files : archive-safety bounded-resources ooxml
@pytest.mark.parametrize(
    "members",
    [
        [
            ("word/document.xml", f'<w:document xmlns:w="{ooxml.W_NS}"/>'),
            ("WORD/DOCUMENT.XML", b"duplicate"),
        ],
        [
            ("word/document.xml", f'<w:document xmlns:w="{ooxml.W_NS}"/>'),
            ("../payload.xml", b"unsafe"),
        ],
    ],
)
def test_ooxml_rejects_unsafe_archive_members_before_parsing(members):
    with pytest.raises(OOXMLExtractionError, match="Could not extract text"):
        extract_ooxml(_zip_bytes(members), filename="unsafe.docx")


# @matrix files : archive-safety central-directory ooxml
def test_ooxml_rejects_central_directory_count_mismatch(monkeypatch):
    content = bytearray(_docx_bytes("<w:p><w:r><w:t>text</w:t></w:r></w:p>"))
    end_offset = content.rfind(ooxml.EOCD_SIGNATURE)
    struct.pack_into("<H", content, end_offset + 8, 0)
    struct.pack_into("<H", content, end_offset + 10, 0)

    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(content, filename="count.docx")

    _set_policy(monkeypatch, member_count=0)
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(_docx_bytes(""), filename="members.docx")


# @matrix files : archive-safety expansion ooxml
def test_ooxml_rejects_unsupported_compression_and_expansion(monkeypatch):
    unsupported = _zip_bytes(
        [("word/document.xml", f'<w:document xmlns:w="{ooxml.W_NS}"/>')],
        compression=zipfile.ZIP_BZIP2,
    )
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(unsupported, filename="bzip.docx")

    _set_policy(monkeypatch, compression_ratio=1.0, compression_ratio_min_bytes=1)
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(
            _docx_bytes("<w:p><w:r><w:t>repeated repeated repeated</w:t></w:r></w:p>"),
            filename="ratio.docx",
        )


# @matrix files : bounded-resources ooxml xml-safety
@pytest.mark.parametrize(
    "body",
    [
        '<!DOCTYPE w:document [<!ENTITY x "expanded">]>'
        f'<w:document xmlns:w="{ooxml.W_NS}"><w:body><w:p><w:r><w:t>&x;</w:t>'
        "</w:r></w:p></w:body></w:document>",
        f'<w:document xmlns:w="{ooxml.W_NS}"><w:body><w:p></w:body></w:document>',
    ],
)
def test_ooxml_rejects_forbidden_or_malformed_xml(body):
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(_zip_bytes([("word/document.xml", body)]), filename="xml.docx")


# @matrix files : ooxml xml-safety
def test_ooxml_rejects_excessive_xml_depth(monkeypatch):
    _set_policy(monkeypatch, xml_depth=4)
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(
            _docx_bytes("<w:p><w:r><w:t>too deep</w:t></w:r></w:p>"),
            filename="deep.docx",
        )


# @matrix files : ooxml partial-result
def test_ooxml_returns_partial_text_for_xml_work_limits(monkeypatch):
    _set_policy(monkeypatch, xml_elements=5)
    element_limited = extract_ooxml(
        _docx_bytes(
            "<w:p><w:r><w:t>kept</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>later</w:t></w:r></w:p>"
        ),
        filename="elements.docx",
    )
    assert element_limited == OOXMLExtractionResult(
        "kept", OOXMLTruncationReason.ELEMENTS
    )

    _set_policy(monkeypatch, xml_bytes=ooxml.READ_CHUNK_BYTES)
    filler = "<w:p/>" * 12_000
    byte_limited = extract_ooxml(
        _docx_bytes(f"<w:p><w:r><w:t>kept</w:t></w:r></w:p>{filler}"),
        filename="bytes.docx",
    )
    assert byte_limited == OOXMLExtractionResult(
        "kept", OOXMLTruncationReason.XML_BYTES
    )


# @matrix files : deadline ooxml partial-result
def test_ooxml_returns_partial_text_when_deadline_expires(monkeypatch):
    _set_policy(monkeypatch, seconds=1.0)
    calls = 0

    def monotonic():
        nonlocal calls
        calls += 1
        return 0.0 if calls <= 5 else 2.0

    monkeypatch.setattr(ooxml.time, "monotonic", monotonic)
    result = extract_ooxml(
        _docx_bytes("<w:p><w:r><w:t>kept</w:t></w:r></w:p>"),
        filename="deadline.docx",
    )

    assert result == OOXMLExtractionResult("kept", OOXMLTruncationReason.DEADLINE)


# @matrix files : ooxml partial-result policy
def test_ooxml_returns_partial_text_for_worksheet_work_limits(monkeypatch):
    two_rows = _worksheet(_inline_row(1, "first", reference="A1") + _inline_row(2, "second", reference="A2"))

    _set_policy(monkeypatch, rows=1)
    row_limited = extract_ooxml(_xlsx_bytes([two_rows]), filename="rows.xlsx")
    assert row_limited == OOXMLExtractionResult("first", OOXMLTruncationReason.ROWS)

    _set_policy(monkeypatch, cells=1)
    cell_limited = extract_ooxml(_xlsx_bytes([two_rows]), filename="cells.xlsx")
    assert cell_limited == OOXMLExtractionResult("first", OOXMLTruncationReason.CELLS)

    _set_policy(monkeypatch, sheets=1)
    sheet_limited = extract_ooxml(
        _xlsx_bytes(
            [
                _worksheet(_inline_row(1, "first")),
                _worksheet(_inline_row(1, "second")),
            ]
        ),
        filename="sheets.xlsx",
    )
    assert sheet_limited == OOXMLExtractionResult("first", OOXMLTruncationReason.SHEETS)


# @matrix files : ooxml relationships xlsx
@pytest.mark.parametrize(
    ("target", "relationship_type", "target_mode"),
    [
        ("../word/document.xml", ooxml.WORKSHEET_REL_TYPE, None),
        ("https://example.com/sheet.xml", ooxml.WORKSHEET_REL_TYPE, "External"),
        ("worksheets/sheet1.xml", "urn:not-a-worksheet", None),
    ],
)
def test_ooxml_rejects_unsafe_worksheet_relationships(
    target, relationship_type, target_mode
):
    content = _xlsx_bytes(
        [_worksheet(_inline_row(1, "value"))],
        targets=[target],
        relationship_type=relationship_type,
        target_mode=target_mode,
    )
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(content, filename="relationship.xlsx")


# @matrix files : fallback ooxml xlsx
def test_ooxml_fallback_worksheets_use_natural_order():
    content = _zip_bytes(
        [
            ("xl/worksheets/sheet10.xml", _worksheet(_inline_row(1, "ten"))),
            ("xl/worksheets/sheet2.xml", _worksheet(_inline_row(1, "two"))),
        ]
    )

    result = extract_ooxml(content, filename="fallback.xlsx")

    assert result.text == "two\nten"


# @matrix files : cell-reference ooxml xlsx
@pytest.mark.parametrize("reference", ["XFE1", "ZZZZZZZZZZZZ1", "A1048577"])
def test_ooxml_rejects_out_of_domain_cell_references(reference):
    content = _xlsx_bytes(
        [_worksheet(_inline_row(1, "value", reference=reference))]
    )
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(content, filename="coordinates.xlsx")


# @matrix files : cell-reference ooxml sparse-row xlsx
def test_ooxml_accepts_xfd_without_unbounded_padding():
    rows = """
        <row r="1">
          <c r="A1" t="inlineStr"><is><t>left</t></is></c>
          <c r="XFD1" t="inlineStr"><is><t>right</t></is></c>
        </row>
    """
    result = extract_ooxml(_xlsx_bytes([_worksheet(rows)]), filename="xfd.xlsx")

    assert result.text.startswith("left")
    assert result.text.endswith("right")
    assert result.text.count("\t") == 16_383


# @matrix files : ooxml shared-strings xlsx
def test_ooxml_bounds_shared_string_storage_and_fanout(monkeypatch):
    shared_sheet = _worksheet(
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>0</v></c></row>'
    )
    repeated = _xlsx_bytes([shared_sheet], shared_strings=["abcdef"])
    result = extract_ooxml(repeated, filename="fanout.xlsx", max_characters=7)
    assert result.truncation_reason == OOXMLTruncationReason.OUTPUT

    _set_policy(monkeypatch, shared_strings=1)
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(
            _xlsx_bytes([shared_sheet], shared_strings=["one", "two"]),
            filename="strings.xlsx",
        )

    _set_policy(monkeypatch, shared_characters=3)
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(repeated, filename="characters.xlsx")


# @matrix files : compressed-limit input-stream ooxml
def test_ooxml_bounds_input_streams_and_preserves_seekable_ownership(monkeypatch):
    content = _docx_bytes("<w:p><w:r><w:t>streamed</w:t></w:r></w:p>")

    class TrackingStream(BytesIO):
        close_called = False

        def close(self):
            self.close_called = True
            super().close()

    seekable = TrackingStream(content)
    seekable.seek(3)
    result = extract_ooxml(seekable, filename="seekable.docx")
    assert result.text == "streamed"
    assert seekable.tell() == 3
    assert seekable.close_called is False

    class NonSeekableStream:
        def __init__(self, value):
            self.buffer = BytesIO(value)
            self.read_sizes = []

        def read(self, size):
            self.read_sizes.append(size)
            return self.buffer.read(size)

    nonseekable = NonSeekableStream(content)
    assert extract_ooxml(nonseekable, filename="spooled.docx").text == "streamed"
    assert max(nonseekable.read_sizes) <= ooxml.READ_CHUNK_BYTES

    _set_policy(monkeypatch, compressed_bytes=len(content) - 1)
    with pytest.raises(OOXMLExtractionError):
        extract_ooxml(content, filename="large.docx")


# @matrix files : archive-safety ooxml streamed-member
def test_ooxml_stream_reader_rejects_bytes_beyond_member_declaration():
    xml = (
        f'<w:document xmlns:w="{ooxml.W_NS}"><w:body/>'
        "</w:document>"
    ).encode()
    info = SimpleNamespace(file_size=len(xml) - 1)
    archive = SimpleNamespace(open=lambda _info: BytesIO(xml))
    policy = replace(ooxml.OOXML_POLICY, seconds=60.0)
    budget = ooxml._ExtractionBudget(policy, 100, ooxml.time.monotonic())
    output = ooxml._TextOutput(100)

    with pytest.raises(ooxml._OOXMLPolicyError):
        ooxml._parse_xml_member(
            archive,
            info,
            ooxml._DocxHandler(output, budget),
            budget,
        )


# @matrix files : ooxml policy
def test_ooxml_production_policy_defaults_are_fixed():
    policy = ooxml.OOXML_POLICY

    assert policy.compressed_bytes == 30 * ooxml.MIB
    assert policy.central_directory_bytes == 4 * ooxml.MIB
    assert policy.member_count == 4_096
    assert policy.member_bytes == 64 * ooxml.MIB
    assert policy.archive_bytes == 256 * ooxml.MIB
    assert policy.compression_ratio == 1_000.0
    assert policy.xml_bytes == 64 * ooxml.MIB
    assert policy.xml_depth == 128
    assert policy.xml_elements == 1_000_000
    assert policy.seconds == 5.0
    assert (policy.sheets, policy.rows, policy.cells) == (256, 100_000, 250_000)
    assert (policy.shared_strings, policy.shared_characters) == (100_000, 4_000_000)
    assert policy.output_characters == 200_000
