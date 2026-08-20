"""File content utilities: text extraction, HTML conversion, and MIME detection."""

import html
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment
import filetype
import markdown

from .constants import CODE_MIMETYPES, ENCODINGS, TEXT_MIMETYPES

SAFE_HTML_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
DROP_HTML_TAGS = {
    "applet",
    "base",
    "button",
    "canvas",
    "embed",
    "form",
    "frame",
    "frameset",
    "iframe",
    "img",
    "input",
    "link",
    "math",
    "meta",
    "noscript",
    "object",
    "option",
    "picture",
    "script",
    "select",
    "source",
    "style",
    "svg",
    "textarea",
    "video",
}
SAFE_LINK_SCHEMES = {"", "http", "https", "mailto"}


# @testable false
# @covered-by lagniappe/core/tools/files/utility.py::sanitize_html
# @reason link scheme filtering is part of the sanitizer contract
def _safe_link(href):
    """Return a sanitized href or None if it uses an unsafe scheme."""
    href = href[0] if isinstance(href, list) and href else href
    if not href:
        return None

    href = href.strip()
    parsed = urlparse(href)
    if parsed.scheme.lower() in SAFE_LINK_SCHEMES:
        return href

    return None


# @testable true
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_markdown_html
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_text_html
# @tests tests_unit/test_014_security.py::test_htmlize_preserves_markdown_tables_and_sanitizes_cells
# @features files, security
# @dimensions html-sanitization table
def sanitize_html(content):
    """Allow only a small safe subset of HTML for inline rendering."""
    if not isinstance(content, str) or not content:
        return ""

    soup = BeautifulSoup(content, "html.parser")

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for tag in list(soup.find_all()):
        name = (tag.name or "").lower()
        if not name:
            continue

        if name in DROP_HTML_TAGS:
            tag.decompose()
            continue

        if name not in SAFE_HTML_TAGS:
            tag.unwrap()
            continue

        attrs = {}
        if name == "a":
            href = _safe_link(tag.attrs.get("href"))
            if href:
                attrs["href"] = href
                attrs["rel"] = "noopener noreferrer"
                attrs["target"] = "_blank"
            title = tag.attrs.get("title")
            if title:
                attrs["title"] = str(title)

        tag.attrs = attrs

    return str(soup)


# @testable true
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_markdown_html
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_text_html
# @tests tests_unit/test_014_security.py::test_htmlize_preserves_markdown_tables_and_sanitizes_cells
# @features files, security
# @dimensions html-sanitization, html, markdown, table
def htmlize(text, mimetype):
    """Convert text content to sanitized HTML based on its MIME type.

    Args:
        text: Raw text content to convert.
        mimetype: MIME type determining the conversion strategy.

    Returns:
        HTML string suitable for safe rendering.
    """
    if mimetype == "text/html":
        return sanitize_html(text)

    elif mimetype == "text/markdown":
        md = markdown.Markdown(extensions=["fenced_code", "tables", "nl2br"])
        return sanitize_html(md.convert(text))

    elif mimetype in CODE_MIMETYPES:
        escaped_text = html.escape(text)
        return f'<pre><code class="{mimetype}">{escaped_text}</code></pre>'

    elif mimetype in TEXT_MIMETYPES.values() or isinstance(text, str):
        return "\n".join(
            [f"<p>{html.escape(line)}</p>" for line in text.split("\n") if line.strip()]
        )

    else:
        return ""


MIME_SAMPLE_BYTES = 8192


# @testable false
# @covered-by lagniappe/core/tools/files/utility.py::determine_encoding
# @covered-by lagniappe/core/tools/files/utility.py::determine_mimetype
# @reason sample positioning is exercised through the upload metadata helpers
def _upload_sample(upload, size=MIME_SAMPLE_BYTES):
    if hasattr(upload, "read_sample"):
        return upload.read_sample(size)

    position = None
    try:
        position = upload.tell()
    except Exception:
        pass

    upload.seek(0)
    sample = upload.read(size)

    try:
        upload.seek(position or 0)
    except Exception:
        pass

    return sample or b""


# @testable false
# @covered-by lagniappe/core/properties/file_assets.py::FileAsset
# @covered-by lagniappe/core/tools/files/utility.py::determine_mimetype
# @reason upload metadata decisions are owned by the file asset upload contract
def determine_encoding(upload):
    """Detect the character encoding of an uploaded file by trial decoding."""
    sample = _upload_sample(upload, 1024)
    for encoding in ENCODINGS:
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue

    return None


GENERIC_MIMETYPES = {None, "", "application/octet-stream", "text/plain"}


# @testable false
# @covered-by lagniappe/core/properties/file_assets.py::FileAsset
# @reason upload metadata decisions are owned by the file asset upload contract
def determine_mimetype(upload, filename, mimetype, encoding):
    """Resolve the MIME type for an upload using magic bytes and file extension.

    Args:
        upload: File-like object to inspect.
        filename: Original filename for extension-based fallback.
        mimetype: Client-provided MIME type, may be None or generic.
        encoding: Detected encoding; if set, unknown binaries fall back to text types.

    Returns:
        Resolved MIME type string.
    """
    if mimetype in GENERIC_MIMETYPES:
        kind = filetype.guess(_upload_sample(upload))

        if kind:
            return kind.mime
        elif encoding:
            ext = filename.split(".")[-1]
            return TEXT_MIMETYPES.get(ext, "text/plain")

    return mimetype
