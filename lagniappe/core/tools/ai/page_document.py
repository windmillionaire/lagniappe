"""Bounded Markdown for an editable Page, checked against the replacement renderer."""

from bs4 import BeautifulSoup
from markdownify import markdownify

from lagniappe.core.tools.files.html import render_markdown, sanitize_html


MAX_EDIT_MARKDOWN_BYTES = 64 * 1024


def _structure(source: str) -> BeautifulSoup:
    tree = BeautifulSoup(source, "html.parser")
    # Layout whitespace between blocks is insignificant. Preserve whitespace in
    # prose and code, where stripping it could join words or change samples.
    for text in tree.find_all(string=True):
        parent = text.parent
        if (
            parent
            and parent.name
            in {"[document]", "table", "thead", "tbody", "tr", "ol", "ul", "blockquote"}
            and not text.strip()
        ):
            text.extract()
    for link in tree.find_all("a", href=True):
        # The shared renderer always supplies these link policies.
        if set(link.get_attribute_list("rel")) == {"noopener", "noreferrer"}:
            del link.attrs["rel"]
        if link.get("target") == "_blank":
            del link.attrs["target"]
    return tree


def _as_markdown(source: str) -> tuple[str, bool]:
    clean = str(sanitize_html(source))
    text = markdownify(clean, heading_style="ATX", bullets="-").strip()
    tree = _structure(clean)
    round_trips = _structure(str(render_markdown(text))) == tree
    if not round_trips:
        # Markdown permits HTML blocks, including merged table cells and
        # task-list attributes that pipe tables and ordinary lists cannot express.
        text = clean
        round_trips = _structure(str(render_markdown(text))) == tree
    complete = round_trips and _structure(source) == tree
    return text, complete


def document_edit_projection(
    source: str | None, *, has_snapshot: bool
) -> dict[str, object]:
    """Return Markdown and indicate whether replacing the document would preserve its structure."""
    if not source:
        return {
            "page_document_markdown": "",
            "page_document_markdown_complete": not has_snapshot,
            "page_document_markdown_truncated": False,
        }

    # Bound the input as well as the projection. Never parse a fragment cut
    # through a tag or present a partial document as a replacement.
    if len(source.encode()) > 4 * MAX_EDIT_MARKDOWN_BYTES:
        return {
            "page_document_markdown": "",
            "page_document_markdown_complete": False,
            "page_document_markdown_truncated": True,
        }

    try:
        text, complete = _as_markdown(source)
    except RecursionError:
        # Deeply nested rich documents can exceed the Markdown parser's stack.
        return {
            "page_document_markdown": "",
            "page_document_markdown_complete": False,
            "page_document_markdown_truncated": True,
        }
    encoded = text.encode()
    truncated = len(encoded) > MAX_EDIT_MARKDOWN_BYTES
    return {
        "page_document_markdown": encoded[:MAX_EDIT_MARKDOWN_BYTES].decode(
            errors="ignore"
        ),
        "page_document_markdown_complete": complete and not truncated,
        "page_document_markdown_truncated": truncated,
    }
