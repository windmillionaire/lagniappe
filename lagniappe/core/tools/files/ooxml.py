"""Lightweight text extraction for Office Open XML files."""

from io import BytesIO
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET


DOCX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OOXML_MIMETYPES = {
    DOCX_MIMETYPE: "docx",
    XLSX_MIMETYPE: "xlsx",
}
OOXML_EXTENSIONS = {
    "docx": "docx",
    "xlsx": "xlsx",
}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {
    "w": W_NS,
    "s": S_NS,
    "r": R_NS,
    "rel": PKG_REL_NS,
}

CELL_REF_RE = re.compile(r"([A-Z]+)")


class OOXMLExtractionError(ValueError):
    """Raised when a supported OOXML file cannot be read as plain text."""


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_summary_generation_uses_docx_text_fallback
# @tests tests_unit/test_015_ai_tools.py::test_ooxml_xlsx_extraction_preserves_rows_tabs_and_shared_strings
# @features files ai
# @dimensions ooxml summary-fallback
def is_supported_ooxml(filename=None, mimetype=None):
    """Return whether filename or MIME type identifies a supported OOXML file."""
    kind = _ooxml_kind(filename=filename, mimetype=mimetype)
    return kind is not None


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_summary_generation_uses_docx_text_fallback
# @tests tests_unit/test_015_ai_tools.py::test_ai_summary_generation_reports_ooxml_extraction_errors
# @tests tests_unit/test_015_ai_tools.py::test_ooxml_xlsx_extraction_preserves_rows_tabs_and_shared_strings
# @features files ai
# @dimensions ooxml docx xlsx summary-fallback
def extract_ooxml_text(content, filename=None, mimetype=None):
    """Extract rough text from supported .docx or .xlsx bytes."""
    kind = _ooxml_kind(filename=filename, mimetype=mimetype)
    if kind is None:
        return None

    try:
        with zipfile.ZipFile(_content_buffer(content)) as archive:
            if kind == "docx":
                return _extract_docx_text(archive).strip()
            if kind == "xlsx":
                return _extract_xlsx_text(archive).strip()
    except OOXMLExtractionError:
        raise
    except (KeyError, ET.ParseError, zipfile.BadZipFile, ValueError) as error:
        label = filename or "Office file"
        raise OOXMLExtractionError(f"Could not extract text from {label}.") from error

    return None


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::is_supported_ooxml
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason type routing is owned by the public OOXML helpers
def _ooxml_kind(filename=None, mimetype=None):
    mimetype = (mimetype or "").lower()
    if mimetype in OOXML_MIMETYPES:
        return OOXML_MIMETYPES[mimetype]

    filename = str(filename or "").lower().rsplit("/", 1)[-1]
    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
    return OOXML_EXTENSIONS.get(extension)


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason upload/storage byte normalization is exercised through extraction tests
def _content_buffer(content):
    if isinstance(content, BytesIO):
        content.seek(0)
        return content

    if isinstance(content, (bytes, bytearray, memoryview)):
        return BytesIO(bytes(content))

    if hasattr(content, "seek") and hasattr(content, "read"):
        content.seek(0)
        return BytesIO(content.read())

    raise ValueError("OOXML content must be bytes or a readable file object.")


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason paragraph text assembly is owned by DOCX extraction behavior
def _paragraph_text(paragraph):
    parts = []
    for node in paragraph.iter():
        if node.tag == f"{{{W_NS}}}t":
            parts.append(node.text or "")
        elif node.tag == f"{{{W_NS}}}tab":
            parts.append("\t")
        elif node.tag in {f"{{{W_NS}}}br", f"{{{W_NS}}}cr"}:
            parts.append("\n")
    return "".join(parts).strip()


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason table row flattening is owned by DOCX extraction behavior
def _table_row_text(row):
    cells = []
    for cell in row.findall("w:tc", NS):
        paragraphs = [
            text
            for text in (
                _paragraph_text(paragraph)
                for paragraph in cell.findall(".//w:p", NS)
            )
            if text
        ]
        cells.append(" ".join(paragraphs))
    return "\t".join(cells).strip()


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason DOCX package traversal is owned by public extraction behavior
def _extract_docx_text(archive):
    root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find("w:body", NS)
    if body is None:
        return ""

    lines = []
    for child in body:
        if child.tag == f"{{{W_NS}}}p":
            text = _paragraph_text(child)
            if text:
                lines.append(text)
        elif child.tag == f"{{{W_NS}}}tbl":
            for row in child.findall(".//w:tr", NS):
                text = _table_row_text(row)
                if text:
                    lines.append(text)

    return "\n".join(lines)


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason workbook relationships are exercised through XLSX extraction tests
def _workbook_sheet_paths(archive):
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        return _fallback_sheet_paths(archive)

    targets = {}
    for rel in rels.findall("rel:Relationship", NS):
        target = rel.attrib.get("Target")
        if not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        targets[rel.attrib.get("Id")] = path

    paths = []
    for sheet in workbook.findall("s:sheets/s:sheet", NS):
        path = targets.get(sheet.attrib.get(f"{{{R_NS}}}id"))
        if path:
            paths.append(path)

    return paths or _fallback_sheet_paths(archive)


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason fallback ordering is part of XLSX extraction behavior
def _fallback_sheet_paths(archive):
    paths = [
        name
        for name in archive.namelist()
        if name.startswith("xl/worksheets/") and name.endswith(".xml")
    ]
    return sorted(paths, key=_natural_key)


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason natural sorting is support logic for XLSX fallback paths
def _natural_key(value):
    return [
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", value)
    ]


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason shared-string parsing is owned by XLSX extraction behavior
def _shared_strings(archive):
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    strings = []
    for item in root.findall("s:si", NS):
        strings.append("".join(node.text or "" for node in item.iter(f"{{{S_NS}}}t")))
    return strings


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason cell reference parsing is owned by XLSX extraction behavior
def _column_index(cell_ref):
    match = CELL_REF_RE.match(str(cell_ref or ""))
    if not match:
        return None

    total = 0
    for char in match.group(1):
        total = total * 26 + ord(char) - ord("A") + 1
    return total - 1


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason cell value coercion is owned by XLSX extraction behavior
def _cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = cell.find("s:is", NS)
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.iter(f"{{{S_NS}}}t"))

    value_node = cell.find("s:v", NS)
    value = value_node.text if value_node is not None and value_node.text else ""
    if cell_type == "s" and value:
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return value
    return value


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason sheet row flattening is owned by XLSX extraction behavior
def _extract_sheet_text(archive, path, shared_strings):
    root = ET.fromstring(archive.read(path))
    lines = []
    for row in root.findall(".//s:sheetData/s:row", NS):
        values = []
        for cell in row.findall("s:c", NS):
            index = _column_index(cell.attrib.get("r"))
            if index is None:
                index = len(values)
            while len(values) <= index:
                values.append("")
            values[index] = _cell_value(cell, shared_strings)

        while values and values[-1] == "":
            values.pop()
        line = "\t".join(values)
        if line.strip():
            lines.append(line)

    return "\n".join(lines)


# @testable false
# @covered-by lagniappe/core/tools/files/ooxml.py::extract_ooxml_text
# @reason XLSX package traversal is owned by public extraction behavior
def _extract_xlsx_text(archive):
    shared_strings = _shared_strings(archive)
    sheet_texts = [
        text
        for text in (
            _extract_sheet_text(archive, path, shared_strings)
            for path in _workbook_sheet_paths(archive)
        )
        if text
    ]
    return "\n".join(sheet_texts)
