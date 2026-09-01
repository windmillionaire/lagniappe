"""Unit tests for security hardening changes."""

import json
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from markupsafe import Markup

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


# @matrix files security : active-content comments html-sanitization malformed-markup unknown-wrapper
@pytest.mark.unit
def test_sanitize_html_drops_active_content_and_unwraps_unknown_markup():
    content = """<!-- hidden -->
    <custom><strong>Keep</strong></custom>
    <script>script text</script><style>style text</style>
    <iframe src='https://example.test'>frame text</iframe>
    <svg><script>svg script</script><text>svg text</text></svg>
    <math><mi>math text</mi></math><form><button>submit</button></form>
    <video src='/track'>video text</video><object>object text</object>
    <p onclick='alert(1)' style='position:fixed'>Safe paragraph</p>
    """

    html = file_html.sanitize_html(content)

    assert "<strong>Keep</strong>" in html
    assert "Safe paragraph" in html
    assert not any(
        value in html
        for value in (
            "hidden",
            "script text",
            "style text",
            "frame text",
            "svg text",
            "math text",
            "submit",
            "video text",
            "object text",
            "onclick",
            "position:fixed",
        )
    )


# @matrix files security : html-sanitization links url-scheme
@pytest.mark.unit
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(1)",
        "java&#x73;cript:alert(1)",
        "jav&#x09;ascript:alert(1)",
        "data:text/html,alert(1)",
        "vbscript:msgbox(1)",
    ],
)
def test_sanitize_html_rejects_obfuscated_active_link_schemes(unsafe_url):
    html = file_html.sanitize_html(f'<a href="{unsafe_url}">bad</a>')
    assert BeautifulSoup(html, "html.parser").find("a").get("href") is None


# @matrix files security : html-sanitization links relative-url url-scheme
@pytest.mark.unit
def test_sanitize_html_keeps_reviewed_link_schemes_and_fixed_attributes():
    html = file_html.sanitize_html(
        '<a href="/relative" title="R" rel="opener" target="frame">R</a>'
        '<a href="http://example.test">H</a>'
        '<a href="https://example.test">S</a>'
        '<a href="mailto:test@example.test">M</a>'
        '<a href="ftp://example.test">F</a>'
    )
    links = BeautifulSoup(html, "html.parser").find_all("a")

    assert [link.get("href") for link in links] == [
        "/relative",
        "http://example.test",
        "https://example.test",
        "mailto:test@example.test",
        None,
    ]
    assert all(link.get("target") == "_blank" for link in links[:4])
    assert all(link.get("rel") == ["noopener", "noreferrer"] for link in links[:4])
    assert links[4].get("target") is None
    assert links[4].get("rel") is None


# @matrix files security : html-sanitization table
@pytest.mark.unit
def test_sanitize_html_bounds_table_spans():
    html = file_html.sanitize_html(
        '<table><tr><td colspan="1" rowspan="2">a</td>'
        '<th colspan="100" rowspan="101">b</th>'
        '<td colspan="2x" rowspan="-2">c</td></tr></table>'
    )
    cells = BeautifulSoup(html, "html.parser").find_all(["td", "th"])

    assert cells[0].attrs == {"rowspan": "2"}
    assert cells[1].attrs == {"colspan": "100"}
    assert cells[2].attrs == {}


# @matrix files security : html-sanitization task-list
@pytest.mark.unit
def test_sanitize_html_strips_task_attributes_outside_exact_ancestry():
    html = file_html.sanitize_html(
        '<li data-type="taskItem" data-checked="true"><input>Loose</li>'
        '<ul data-type="taskList"><li>Ordinary</li></ul>'
        '<ul data-type="taskList"><li data-type="taskItem" data-checked="true">'
        '<p>Task</p><input type="checkbox" onclick="bad()"></li></ul>'
    )
    soup = BeautifulSoup(html, "html.parser")

    assert soup.find_all("input") == [
        soup.find("ul", attrs={"data-type": "taskList"}).find("input")
    ]
    assert soup.find("li", string="Loose").attrs == {}
    assert soup.find("ul", string="Ordinary").attrs == {}
    checkbox = soup.find("ul", attrs={"data-type": "taskList"}).find("input")
    assert checkbox.attrs == {"type": "checkbox", "disabled": "", "checked": ""}


# @matrix security : nominal-type serialization trust-loss
@pytest.mark.unit
def test_safe_html_policy_is_typed_idempotent_and_ephemeral():
    assert isinstance(file_html.sanitize_html(None), file_html.SafeHTML)
    assert file_html.sanitize_html(None) == ""
    assert isinstance(file_html.render_markdown(42), file_html.SafeHTML)

    once = file_html.sanitize_html('<p title="drop">Safe</p>')
    twice = file_html.sanitize_html(once)
    assert once == twice
    assert type(once + "") is str
    assert type(f"{once}") is str
    assert type(Markup(once)) is Markup
    assert json.loads(json.dumps({"html": once}))["html"] == str(once)


# @matrix files security : code html-sanitization mimetype plain-text
@pytest.mark.unit
def test_htmlize_escapes_code_plain_text_and_mimetype_attributes(monkeypatch):
    mimetype = 'text/x" onmouseover="bad'
    monkeypatch.setattr(file_html, "CODE_MIMETYPES", {mimetype})
    code = file_html.htmlize('<script>bad</script>', mimetype)
    plain = file_html.htmlize('<img src=x onerror=bad> & text', 'unknown/type')

    assert isinstance(code, file_html.SafeHTML)
    assert "<script>" not in code
    assert "&lt;script&gt;bad&lt;/script&gt;" in code
    assert 'onmouseover="bad"' not in code
    assert "<img" not in plain
    assert "&lt;img src=x onerror=bad&gt; &amp; text" in plain


def _image_owner(url):
    asset = SimpleNamespace(url=url)
    owner = SimpleNamespace(
        assets={"image_intro_owned": {"type": "image"}},
        get_asset=lambda name: asset if name == "image_intro_owned" else None,
    )
    return owner


# @matrix form-html security : html-sanitization owned-image
@pytest.mark.unit
def test_form_content_policy_keeps_only_owned_images():
    owned = "https://assets.test/form/image_intro_owned.png?signature=current"
    content = (
        '<p onclick="bad()">Text</p>'
        '<img src="https://assets.test/form/image_intro_owned.png?signature=old" '
        'alt="Diagram" onerror="bad()" '
        'style="width: 55%; float: left; position: fixed; background: url(javascript:bad)">'
        '<img src="https://external.test/tracker.png">'
        '<script>alert(1)</script>'
    )

    html = file_html.sanitize_form_content_html(
        content,
        _image_owner(owned),
        "intro",
    )
    soup = BeautifulSoup(html, "html.parser")
    images = soup.find_all("img")

    assert len(images) == 1
    assert images[0]["src"] == owned
    assert images[0]["alt"] == "Diagram"
    assert images[0]["style"] == (
        "width:55%;display:block;float:left;margin:0 1em 1em 0"
    )
    assert "onclick" not in html
    assert "onerror" not in html
    assert "javascript" not in html
    assert "script" not in html
    assert file_html.sanitize_form_content_html(None, None, "intro") == ""
    assert isinstance(
        file_html.sanitize_form_content_html(None, None, "intro"),
        file_html.SafeHTML,
    )


# @matrix public-pages security : html-sanitization owned-image
@pytest.mark.unit
def test_public_document_policy_keeps_only_rewritten_owned_images():
    source = "https://private.test/page/image_first.png?signature=old"
    rewritten = "https://site.test/pages/public/id/images/image_first.png"
    html = file_html.sanitize_public_document_html(
        '<h2>Public</h2><img src="https://private.test/page/image_first.png">'
        '<img src="data:image/png;base64,AAAA"><iframe>embed</iframe>',
        [(source, rewritten)],
    )
    soup = BeautifulSoup(html, "html.parser")

    assert soup.find("img")["src"] == rewritten
    assert len(soup.find_all("img")) == 1
    assert "iframe" not in html
    assert "embed" not in html
    assert file_html.sanitize_public_document_html(None, []) == ""


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
