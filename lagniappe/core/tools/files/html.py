"""HTML cleaning, sanitization, and text conversion."""

import html as html_module
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment
import markdown

from .constants import CODE_MIMETYPES, TEXT_MIMETYPES


SAFE_HTML_TAGS = {
    "a", "blockquote", "br", "code", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "li", "ol", "p", "pre", "strong", "table",
    "tbody", "td", "th", "thead", "tr", "ul",
}
DROP_HTML_TAGS = {
    "applet", "base", "button", "canvas", "embed", "form", "frame",
    "frameset", "iframe", "img", "input", "link", "math", "meta",
    "noscript", "object", "option", "picture", "script", "select", "source",
    "style", "svg", "textarea", "video",
}
SAFE_LINK_SCHEMES = {"", "http", "https", "mailto"}


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_strip_tags
# @pair utility:html-stripping
def strip_tags(html_content):
    """Strip HTML tags and collapse whitespace in text content."""
    if not isinstance(html_content, str):
        return html_content
    soup = BeautifulSoup(html_content, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_clean_html
# @pair utility:html-cleaning
def clean_html(content):
    """Strip Markdown fences, empty tags, and inter-tag whitespace."""
    if not content or not isinstance(content, str):
        return content or ""
    content = re.sub(r"```html\s*(.*?)\s*```", r"\1", content, flags=re.DOTALL)
    content = re.sub(r"```\s*(.*?)\s*```", r"\1", content, flags=re.DOTALL)
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(["p", "li", "div", "span"]):
        if not tag.get_text(strip=True) and not tag.find_all(["img", "br", "hr"]):
            tag.decompose()
    return re.sub(r">\s+<", "><", str(soup)).strip()


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @reason link-scheme filtering is part of the public HTML sanitizer contract
def _safe_link(href):
    href = href[0] if isinstance(href, list) and href else href
    if not href:
        return None
    href = href.strip()
    return href if urlparse(href).scheme.lower() in SAFE_LINK_SCHEMES else None


# @testable true
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_markdown_html
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_text_html
# @tests tests_unit/test_014_security.py::test_htmlize_preserves_markdown_tables_and_sanitizes_cells
# @matrix files security : html-sanitization table
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
                attrs.update(
                    {"href": href, "rel": "noopener noreferrer", "target": "_blank"}
                )
            title = tag.attrs.get("title")
            if title:
                attrs["title"] = str(title)
        tag.attrs = attrs
    return str(soup)


# @testable true
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_markdown_html
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_text_html
# @tests tests_unit/test_014_security.py::test_htmlize_preserves_markdown_tables_and_sanitizes_cells
# @matrix files security : html html-sanitization markdown table
def htmlize(text, mimetype):
    """Convert text content to sanitized HTML for its MIME type."""
    if mimetype == "text/html":
        return sanitize_html(text)
    if mimetype == "text/markdown":
        converter = markdown.Markdown(extensions=["fenced_code", "tables", "nl2br"])
        return sanitize_html(converter.convert(text))
    if mimetype in CODE_MIMETYPES:
        return f'<pre><code class="{mimetype}">{html_module.escape(text)}</code></pre>'
    if mimetype in TEXT_MIMETYPES.values() or isinstance(text, str):
        return "\n".join(
            f"<p>{html_module.escape(line)}</p>"
            for line in text.split("\n")
            if line.strip()
        )
    return ""
