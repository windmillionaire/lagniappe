"""Unit tests for security hardening changes."""

import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.tools import files


# @matrix files security : html-sanitization markdown
@pytest.mark.unit
def test_htmlize_sanitizes_markdown_html():
    """Markdown rendering should strip active HTML and unsafe links."""
    content = """# Heading
<script>alert("xss")</script>
<a href="javascript:alert('bad')">Bad</a>
<a href="https://example.com">Good</a>"""

    html = files.htmlize(content, "text/markdown")

    assert "<script" not in html
    assert 'href="https://example.com"' in html
    assert 'rel="noopener noreferrer"' in html
    assert ">Bad<" in html


# @matrix files security : html-sanitization markdown table
@pytest.mark.unit
def test_htmlize_preserves_markdown_tables_and_sanitizes_cells():
    """Markdown tables should render while unsafe cell content is stripped."""
    content = """| Work | Link |
|---|---|
| Keep `response_mime_type` | <a href="https://example.com">Good</a> |
| Drop unsafe content | <a href="javascript:alert('bad')">Bad</a><img src=x onerror=alert('bad')> |
<script>alert("xss")</script>
"""

    html = files.htmlize(content, "text/markdown")

    assert "<table>" in html
    assert "<thead>" in html
    assert "<tbody>" in html
    assert "<th>Work</th>" in html
    assert "Keep <code>response_mime_type</code>" in html
    assert 'href="https://example.com"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "<script" not in html
    assert "<img" not in html
    assert "javascript:" not in html
    assert "onerror" not in html


# @matrix files security : html html-sanitization
@pytest.mark.unit
def test_htmlize_sanitizes_text_html():
    """HTML previews should keep safe formatting and drop active content."""
    content = """
    <p>Hello <strong>world</strong></p>
    <iframe src="https://example.com/embed"></iframe>
    <img src="https://example.com/image.png" onerror="alert('xss')">
    <a href="mailto:test@example.com" onclick="alert('xss')">Mail</a>
    """

    html = files.htmlize(content, "text/html")

    assert "<iframe" not in html
    assert "<img" not in html
    assert "onclick" not in html
    assert 'href="mailto:test@example.com"' in html


# @matrix files security : mimetype preview svg
@pytest.mark.unit
def test_svg_removed_from_preview_mimetypes():
    """SVG should no longer be previewable inline."""
    assert "image/svg+xml" not in files.PREVIEW_MIMETYPES


# @matrix file security : html-stripping summary
@pytest.mark.unit
def test_file_summary_strips_tags():
    """File summaries should be stored as plain text."""
    file = Entities.FILE(testing=True)
    file.summary = '<strong>Tax summary</strong><script>alert("xss")</script>'

    assert file.summary == "Tax summary"
