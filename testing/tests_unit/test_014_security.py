"""Unit tests for security hardening changes."""

import pytest
from bs4 import BeautifulSoup

from lagniappe.core.entities import Entities
from lagniappe.core.tools.files import constants as file_constants
from lagniappe.core.tools.files import html as file_html


# @matrix files security : html-sanitization markdown
@pytest.mark.unit
def test_htmlize_sanitizes_markdown_html():
    """Markdown rendering should strip active HTML and unsafe links."""
    content = """# Heading
<script>alert("xss")</script>
<a href="javascript:alert('bad')">Bad</a>
<a href="https://example.com">Good</a>"""

    html = file_html.htmlize(content, "text/markdown")

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

    html = file_html.htmlize(content, "text/markdown")

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
    <table><tr><td colspan="2" rowspan="999">Cell</td></tr></table>
    """

    html = file_html.htmlize(content, "text/html")

    assert "<iframe" not in html
    assert "<img" not in html
    assert "onclick" not in html
    assert 'href="mailto:test@example.com"' in html
    assert 'colspan="2"' in html
    assert "rowspan" not in html


# @matrix editor files markdown : hard-break soft-wrap
@pytest.mark.unit
def test_render_markdown_collapses_soft_wrapped_lines():
    """Soft source wraps should flow while explicit breaks stay meaningful."""
    content = (
        """A sentence that wraps
onto another source line.

- A bullet that wraps
onto another source line.

An explicit break."""
        + "  \nAfter the break."
    )

    html = file_html.render_markdown(content)
    soup = BeautifulSoup(html, "html.parser")

    assert len(soup.find_all("br")) == 1
    assert " ".join(soup.find("p").get_text().split()) == (
        "A sentence that wraps onto another source line."
    )
    assert "\n" not in soup.find("p").get_text()
    assert " ".join(soup.find("li").get_text().split()) == (
        "A bullet that wraps onto another source line."
    )
    assert "\n" not in soup.find("li").get_text()
    assert len(soup.find_all("p", recursive=False)) == 2
    explicit = soup.find_all("p", recursive=False)[1]
    assert explicit.find("br").next_sibling == "After the break."


# @matrix editor files markdown : code-block soft-wrap
@pytest.mark.unit
def test_render_markdown_preserves_code_block_newlines():
    """Whitespace normalization must not alter fenced code content."""
    html = file_html.render_markdown("```text\nfirst line\nsecond line\n```")
    soup = BeautifulSoup(html, "html.parser")

    assert soup.find("code").get_text() == "first line\nsecond line\n"


# @matrix editor files markdown : task-list
@pytest.mark.unit
def test_render_markdown_creates_editor_task_lists():
    """GFM task Markdown should become safe TipTap-compatible task nodes."""
    content = """- [ ] First task wraps
onto another source line.
    - [x] Nested complete
- [X] Complete ~~now~~"""

    html = file_html.render_markdown(content)
    soup = BeautifulSoup(html, "html.parser")
    task_list = soup.find("ul", attrs={"data-type": "taskList"})
    items = task_list.find_all("li", attrs={"data-type": "taskItem"})

    assert [item["data-checked"] for item in items] == ["false", "true", "true"]
    assert " ".join(items[0].find("p").get_text().split()) == (
        "First task wraps onto another source line."
    )
    assert not items[0].find("p").get_text().startswith(" ")
    assert items[0].find("ul", attrs={"data-type": "taskList"}) is not None
    assert all(item.find("div", recursive=False) is not None for item in items)
    assert all(item.find("input").has_attr("disabled") for item in items)
    assert not items[0].find("input").has_attr("checked")
    assert items[1].find("input").has_attr("checked")
    assert soup.find("del").get_text() == "now"
    assert "class=" not in html


# @matrix editor markdown : mixed-list task-list
@pytest.mark.unit
def test_render_markdown_splits_mixed_task_lists():
    """Ordinary items in a task list should remain ordinary list items."""
    html = file_html.render_markdown("- [ ] Task\n- Ordinary\n- [x] Done")
    soup = BeautifulSoup(html, "html.parser")
    lists = soup.find_all(["ul", "ol"], recursive=False)

    assert [item.attrs.get("data-type") for item in lists] == [
        "taskList",
        None,
        "taskList",
    ]
    assert lists[1].get_text(" ", strip=True) == "Ordinary"
    assert lists[1].find("input") is None


# @matrix editor files markdown : list-kind
@pytest.mark.unit
def test_render_markdown_preserves_adjacent_list_kinds():
    """A following ordered list should not be folded into a bullet list."""
    html = file_html.render_markdown(
        "- First bullet\n- Second bullet\n\n1. First step\n2. Second step"
    )
    soup = BeautifulSoup(html, "html.parser")

    assert soup.find("ul").get_text(" ", strip=True) == "First bullet Second bullet"
    assert soup.find("ol").get_text(" ", strip=True) == "First step Second step"


# @matrix editor files markdown : html-source
# @matrix files security : html-sanitization
@pytest.mark.unit
def test_render_markdown_normalizes_indented_html_source():
    """Explicitly converted HTML source should format safely despite outer indent."""
    html = file_html.render_markdown(
        """
        <p><strong>Note</strong></p>
        <script>alert("bad")</script>
        <a href="javascript:alert('bad')">Bad link</a>
        """
    )

    assert "<strong>Note</strong>" in html
    assert "script" not in html
    assert "javascript:" not in html


# @matrix files security : html-sanitization task-list
@pytest.mark.unit
def test_sanitize_html_restricts_task_controls():
    """Only inert canonical task checkboxes should survive sanitization."""
    content = """<ul data-type="taskList">
    <li data-type="taskItem" data-checked="true">
      <label><input type="text" onclick="alert(1)"><span style="color:red"></span></label>
      <div><p>Task</p><input type="checkbox"></div>
    </li>
    </ul>"""

    html = file_html.sanitize_html(content)
    soup = BeautifulSoup(html, "html.parser")
    controls = soup.find_all("input")

    assert len(controls) == 1
    assert controls[0].attrs == {"type": "checkbox", "disabled": "", "checked": ""}
    assert soup.find("span").attrs == {}
    assert "onclick" not in html


# @matrix files security : mimetype preview svg
@pytest.mark.unit
def test_svg_removed_from_preview_mimetypes():
    """SVG should no longer be previewable inline."""
    assert "image/svg+xml" not in file_constants.PREVIEW_MIMETYPES


# @matrix file security : html-stripping summary
@pytest.mark.unit
def test_file_summary_strips_tags():
    """File summaries should be stored as plain text."""
    file = Entities.FILE(testing=True)
    file.summary = '<strong>Tax summary</strong><script>alert("xss")</script>'

    assert file.summary == "Tax summary"
