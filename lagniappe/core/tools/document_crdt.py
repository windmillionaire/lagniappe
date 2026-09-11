"""Append sanitized report fragments without rebuilding existing editor nodes."""

import base64
import hashlib
import json
import secrets

from bs4 import BeautifulSoup, NavigableString
from pycrdt import Doc, Map, XmlElement, XmlFragment, XmlText


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_append_preserves_existing_crdt_and_is_idempotent
# @matrix editor sync : document append idempotency offline-replay
def load_document(snapshot=None):
    doc = Doc(
        {"default": XmlFragment(), "lagniappeReports": Map()},
        client_id=secrets.randbits(32),
    )
    if snapshot:
        doc.apply_update(base64.b64decode(snapshot, validate=True))
    return doc


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_append_preserves_existing_crdt_and_is_idempotent
# @matrix editor sync : document append idempotency offline-replay
def encode_document(doc):
    return base64.b64encode(doc.get_update()).decode("ascii")


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_append_preserves_existing_crdt_and_is_idempotent
# @matrix editor sync : document append idempotency offline-replay
def merge_documents(*snapshots):
    doc = load_document()
    for snapshot in snapshots:
        if snapshot:
            doc.apply_update(base64.b64decode(snapshot, validate=True))
    return encode_document(doc)


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_report_append_retry_and_undo_preserve_content
# @matrix ai-report editor : document append retry undo conflict
def document_structure(snapshot):
    # @testable false
    # @covered-by lagniappe/core/tools/document_crdt.py::document_structure
    # @reason canonical recursive XML projection
    def project(node):
        if isinstance(node, XmlText):
            return ["text", node.diff()]
        return [
            getattr(node, "tag", "fragment"),
            dict(node.attributes) if isinstance(node, XmlElement) else {},
            [project(child) for child in node.children],
        ]

    return json.dumps(
        project(load_document(snapshot)["default"]),
        sort_keys=True,
        separators=(",", ":"),
    )


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_append_requires_a_checkpointed_collaborative_baseline
# @matrix editor sync : document append checkpoint conflict
def document_state(snapshot):
    """Compare IDs/clocks and content, not nondeterministic binary map ordering."""
    doc = load_document(snapshot)
    values = iter(doc.get_state())

    # @testable false
    # @covered-by lagniappe/core/tools/document_crdt.py::document_state
    # @reason Yjs state-vector unsigned varint decoding
    def integer():
        value = shift = 0
        for byte in values:
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
        raise ValueError("Invalid document state vector")

    vector = sorted((integer(), integer()) for _ in range(integer()))
    return vector, document_structure(snapshot), dict(doc["lagniappeReports"])


# @testable false
# @covered-by lagniappe/core/tools/document_crdt.py::append_fragment
# @reason converter is restricted to the shared sanitized Markdown renderer's output
def _append_nodes(parent, nodes, marks=None):
    marks = marks or {}
    text = None
    for node in nodes:
        if isinstance(node, NavigableString):
            value = str(node)
            if not value or (
                not value.strip()
                and (
                    isinstance(parent, XmlFragment)
                    or getattr(parent, "tag", None)
                    in {
                        "blockquote",
                        "table",
                        "tableRow",
                        "bulletList",
                        "orderedList",
                        "taskList",
                    }
                )
            ):
                continue
            if text is None:
                text = XmlText()
                parent.children.append(text)
            text.insert(len(text), value, marks)
            continue
        tag = node.name
        mark = {
            "strong": "bold",
            "em": "italic",
            "s": "strike",
            "strike": "strike",
            "del": "strike",
            "u": "underline",
            "sub": "subscript",
            "sup": "superscript",
            "code": "code",
            "a": "link",
        }.get(tag)
        if mark:
            attrs = (
                {
                    "href": node.get("href"),
                    "target": "_blank",
                    "rel": "noopener noreferrer",
                    "class": None,
                }
                if mark == "link"
                else {}
            )
            _append_nodes(parent, node.contents, {**marks, mark: attrs})
            text = None
            continue
        text = None
        attributes = {}
        kind = {
            "p": "paragraph",
            "blockquote": "blockquote",
            "ul": "bulletList",
            "ol": "orderedList",
            "li": "listItem",
            "pre": "codeBlock",
            "br": "hardBreak",
            "hr": "horizontalRule",
            "table": "table",
            "tr": "tableRow",
            "td": "tableCell",
            "th": "tableHeader",
        }.get(tag)
        if tag in {"thead", "tbody", "tfoot"}:
            _append_nodes(parent, node.contents)
            continue
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            kind, attributes = "heading", {"level": int(tag[1])}
        elif tag == "ol":
            attributes = {"start": int(node.get("start", 1))}
        elif tag == "ul" and node.get("data-type") == "taskList":
            kind = "taskList"
        elif tag == "li" and node.get("data-type") == "taskItem":
            kind, attributes = (
                "taskItem",
                {"checked": node.get("data-checked") == "true"},
            )
        elif tag in {"td", "th"}:
            attributes = {
                "colspan": int(node.get("colspan", 1)),
                "rowspan": int(node.get("rowspan", 1)),
                "colwidth": None,
            }
        if kind is None:
            raise ValueError(f"Unsupported report document element: {tag}")
        element = XmlElement(kind, attributes=attributes)
        parent.children.append(element)
        if tag == "pre":
            element.children.append(XmlText(node.get_text()))
        elif tag in {"li", "td", "th"}:
            # ProseMirror list items/cells require block children even for a
            # compact Markdown renderer's bare inline contents.
            pending = []
            contents = []
            for child in node.contents:
                if kind == "taskItem" and getattr(child, "name", None) == "label":
                    continue
                if kind == "taskItem" and getattr(child, "name", None) == "div":
                    contents.extend(child.contents)
                else:
                    contents.append(child)
            for child in contents:
                if getattr(child, "name", None) in {
                    "p",
                    "ul",
                    "ol",
                    "blockquote",
                    "pre",
                    "table",
                }:
                    if pending:
                        paragraph = XmlElement("paragraph")
                        element.children.append(paragraph)
                        _append_nodes(paragraph, pending)
                        pending = []
                    _append_nodes(element, [child])
                else:
                    pending.append(child)
            if pending or not len(element.children):
                paragraph = XmlElement("paragraph")
                element.children.append(paragraph)
                _append_nodes(paragraph, pending)
        else:
            _append_nodes(element, node.contents, marks)


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_append_preserves_existing_crdt_and_is_idempotent
# @tests tests_unit/test_010b_document_append.py::test_append_converts_supported_markdown_blocks
# @matrix editor sync : document append idempotency offline-replay browser-interop undo
# @matrix editor markdown : document append formatting
def append_fragment(snapshot, html, operation_id, *, html_after=None):
    """Return a new snapshot and a durable retry receipt; never reset old IDs."""
    doc = load_document(snapshot)
    receipts = doc["lagniappeReports"]
    if operation_id in receipts:
        return snapshot, receipts[operation_id]
    root = doc["default"]
    start = len(root.children)
    _append_nodes(root, BeautifulSoup(html, "html.parser").contents)
    receipt = {"state": "applied", "start": start, "count": len(root.children) - start}
    if html_after is not None:
        receipt["signature"] = {
            "html": hashlib.md5(html_after.strip().encode()).hexdigest()
            if html_after.strip()
            else None,
            "structure": hashlib.sha256(
                document_structure(encode_document(doc)).encode()
            ).hexdigest(),
        }
    receipts[operation_id] = receipt
    return encode_document(doc), receipt


# @testable true
# @tests tests_unit/test_010b_document_append.py::test_undo_emits_tombstones_without_resetting_existing_nodes
# @matrix editor sync : document append undo tombstones browser-interop offline-replay
def undo_fragment(snapshot, operation_id):
    """Delete this append's unchanged tail; caller must fence against edits."""
    doc = load_document(snapshot)
    receipt = doc["lagniappeReports"].get(operation_id)
    if not receipt or receipt["state"] == "undone":
        return snapshot
    start, count = int(receipt["start"]), int(receipt["count"])
    if len(doc["default"].children) != start + count:
        raise ValueError("Document changed after the append; undo stopped.")
    del doc["default"].children[start : start + count]
    doc["lagniappeReports"][operation_id] = {**receipt, "state": "undone"}
    return encode_document(doc)
