"""Append sanitized report fragments without rebuilding existing editor nodes."""

import base64
import hashlib
import json
import secrets
from collections.abc import Buffer
from typing import NotRequired, TypedDict, cast

from bs4 import BeautifulSoup
from bs4.element import NavigableString
from pycrdt import Doc, Map, XmlElement, XmlFragment, XmlText


class DocumentReceipt(TypedDict):
    state: str
    signature: NotRequired[dict[str, str | None]]


type Document = Doc[XmlFragment | Map]


def report_receipts(doc: Document) -> Map[DocumentReceipt]:
    """The report root is a Map in every initialized collaborative document."""
    return cast(Map[DocumentReceipt], doc["lagniappeReports"])


def _replacements(doc: Document) -> Map[dict[str, str]]:
    return cast(Map[dict[str, str]], doc["lagniappeReplacements"])


def _fragment(doc: Document) -> XmlFragment:
    return cast(XmlFragment, doc["default"])


def load_document(snapshot: object = None) -> Document:
    doc = Doc(
        {"default": XmlFragment(), "lagniappeReports": Map(), "lagniappeReplacements": Map()},
        client_id=secrets.randbits(32),
    )
    if snapshot:
        if not isinstance(snapshot, (str, Buffer)):
            raise TypeError("Expected an encoded document snapshot")
        doc.apply_update(base64.b64decode(snapshot, validate=True))
    return doc


def encode_document(doc: Document) -> str:
    return base64.b64encode(doc.get_update()).decode("ascii")


def merge_documents(*snapshots: str | bytes | None) -> str:
    doc = load_document()
    for snapshot in snapshots:
        if snapshot:
            doc.apply_update(base64.b64decode(snapshot, validate=True))
    return encode_document(doc)


def document_structure(snapshot: str | bytes | None) -> str:
    def project(node):
        if isinstance(node, XmlText):
            return ["text", node.diff()]
        return [
            getattr(node, "tag", "fragment"),
            dict(node.attributes.__iter__()) if isinstance(node, XmlElement) else {},
            [project(child) for child in node.children],
        ]

    return json.dumps(
        project(_fragment(load_document(snapshot))),
        sort_keys=True,
        separators=(",", ":"),
    )


def document_state(
    snapshot: str | bytes | None,
) -> tuple[
    list[tuple[int, int]], str, dict[str, DocumentReceipt], dict[str, dict[str, str]]
]:
    """Compare IDs/clocks and content, not nondeterministic binary map ordering."""
    doc = load_document(snapshot)
    values = iter(doc.get_state())

    def integer():
        value = shift = 0
        for byte in values:
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
        raise ValueError("Invalid document state vector")

    vector = sorted((integer(), integer()) for _ in range(integer()))
    return vector, document_structure(snapshot), dict(report_receipts(doc).items()), dict(_replacements(doc).items())


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
        # pycrdt annotates attributes as strings, but its Yjs binding also
        # persists the numeric heading level and list start used by the editor.
        element = XmlElement(kind, attributes=cast(dict[str, str], attributes))
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
                    if any(
                        not isinstance(part, NavigableString) or str(part).strip()
                        for part in pending
                    ):
                        paragraph = XmlElement("paragraph")
                        element.children.append(paragraph)
                        _append_nodes(paragraph, pending)
                    pending = []
                    _append_nodes(element, [child])
                else:
                    pending.append(child)
            if not len(element.children) or any(
                not isinstance(part, NavigableString) or str(part).strip()
                for part in pending
            ):
                paragraph = XmlElement("paragraph")
                element.children.append(paragraph)
                _append_nodes(paragraph, pending)
        else:
            _append_nodes(element, node.contents, marks)


def append_fragment(
    snapshot: str | None, html: str, operation_id: str, *, html_after: str | None = None
) -> tuple[str | None, DocumentReceipt]:
    """Return a new snapshot and a durable retry receipt; never reset old IDs."""
    doc = load_document(snapshot)
    receipts = report_receipts(doc)
    if operation_id in receipts:
        return snapshot, receipts[operation_id]
    root = _fragment(doc)
    _append_nodes(root, BeautifulSoup(html, "html.parser").contents)
    receipt: DocumentReceipt = {"state": "applied"}
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


def replace_fragment(
    snapshot: str | None,
    html: str,
    operation_id: str,
    *,
    previous_version: str,
    name: str,
) -> tuple[str | None, DocumentReceipt]:
    """Replace visible nodes as one edit, retaining tombstones and all receipts."""
    doc = load_document(snapshot)
    if operation_id in report_receipts(doc):
        return snapshot, report_receipts(doc)[operation_id]
    with doc.transaction():
        root = _fragment(doc)
        del root.children[:]
        _append_nodes(root, BeautifulSoup(html, "html.parser").contents)
        _replacements(doc)[operation_id] = {
            "key": previous_version, "name": name,
        }
        receipt: DocumentReceipt = {"state": "applied", "signature": {
            "html": hashlib.md5(html.strip().encode()).hexdigest() if html.strip() else None,
            "structure": hashlib.sha256(document_structure(encode_document(doc)).encode()).hexdigest(),
        }}
        report_receipts(doc)[operation_id] = receipt
    return encode_document(doc), receipt
