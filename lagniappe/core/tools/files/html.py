"""HTML cleaning, sanitization, and text conversion."""

import html as html_module
import re
import textwrap
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, NavigableString
import markdown

from .constants import CODE_MIMETYPES, TEXT_MIMETYPES


SAFE_HTML_TAGS = {
    "a", "blockquote", "br", "code", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "li", "ol", "p", "pre", "s", "strike",
    "strong", "sub", "sup", "table", "tbody", "td", "th", "thead",
    "tr", "u", "ul", "del",
}
DROP_HTML_TAGS = {
    "applet", "base", "button", "canvas", "embed", "form", "frame",
    "frameset", "iframe", "img", "input", "link", "math", "meta",
    "noscript", "object", "option", "picture", "script", "select", "source",
    "style", "svg", "textarea", "video",
}
SAFE_LINK_SCHEMES = {"", "http", "https", "mailto"}
TASK_LIST_TYPE = "taskList"
TASK_ITEM_TYPE = "taskItem"
HTML_FRAGMENT_PATTERN = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
TASK_BLOCK_TAGS = {
    "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "ol",
    "p", "pre", "table", "ul",
}
FLOW_TEXT_TAGS = {
    "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p",
    "td", "th",
}


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


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @reason table span validation is part of the shared sanitizer contract
def _safe_span(value):
    try:
        span = int(value)
    except (TypeError, ValueError):
        return None
    return str(span) if 1 < span <= 100 else None


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @reason canonical task attributes are enforced as part of sanitization
def _task_attrs(tag):
    name = (tag.name or "").lower()
    if name == "ul" and tag.attrs.get("data-type") == TASK_LIST_TYPE:
        return {"data-type": TASK_LIST_TYPE}

    if name == "li":
        parent = tag.parent
        if (
            tag.attrs.get("data-type") == TASK_ITEM_TYPE
            and getattr(parent, "name", None) == "ul"
            and parent.attrs.get("data-type") == TASK_LIST_TYPE
        ):
            checked = str(tag.attrs.get("data-checked", "false")).lower() == "true"
            return {
                "data-type": TASK_ITEM_TYPE,
                "data-checked": "true" if checked else "false",
            }

    if name == "label":
        parent = tag.parent
        if (
            getattr(parent, "name", None) == "li"
            and parent.attrs.get("data-type") == TASK_ITEM_TYPE
        ):
            return {}

    if name == "input":
        label = tag.parent
        item = getattr(label, "parent", None)
        if (
            getattr(label, "name", None) == "label"
            and getattr(item, "name", None) == "li"
            and item.attrs.get("data-type") == TASK_ITEM_TYPE
        ):
            attrs = {"type": "checkbox", "disabled": ""}
            if item.attrs.get("data-checked") == "true":
                attrs["checked"] = ""
            return attrs

    if name == "span":
        label = tag.parent
        item = getattr(label, "parent", None)
        if (
            getattr(label, "name", None) == "label"
            and getattr(item, "name", None) == "li"
            and item.attrs.get("data-type") == TASK_ITEM_TYPE
        ):
            return {}

    if name == "div":
        item = tag.parent
        if (
            getattr(item, "name", None) == "li"
            and item.attrs.get("data-type") == TASK_ITEM_TYPE
        ):
            return {}

    return None


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::render_markdown
# @reason task item construction is exercised through Markdown rendering
def _canonicalize_task_item(soup, item):
    control = item.find(
        lambda tag: tag.name in {"label", "input"}
        and (
            "task-list-control" in tag.attrs.get("class", [])
            or tag.attrs.get("type") == "checkbox"
        ),
        recursive=False,
    )
    checkbox = control.find("input", attrs={"type": "checkbox"}) if control else None
    if checkbox is None and getattr(control, "name", None) == "input":
        checkbox = control
    checked = checkbox is not None and checkbox.has_attr("checked")

    if control is not None:
        control.extract()
    content = [child.extract() for child in list(item.contents)]

    label = soup.new_tag("label")
    input_element = soup.new_tag("input")
    input_element.attrs = {"type": "checkbox", "disabled": ""}
    if checked:
        input_element.attrs["checked"] = ""
    label.append(input_element)
    label.append(soup.new_tag("span"))

    wrapper = soup.new_tag("div")
    paragraph = None

    # @testable false
    # @covered-by lagniappe/core/tools/files/html.py::render_markdown
    # @reason local task-block grouping is exercised through Markdown rendering
    def flush_paragraph():
        nonlocal paragraph
        if paragraph is not None:
            wrapper.append(paragraph)
            paragraph = None

    for child in content:
        if isinstance(child, NavigableString) and not str(child).strip():
            continue
        if getattr(child, "name", None) in TASK_BLOCK_TAGS:
            flush_paragraph()
            wrapper.append(child)
            continue
        if paragraph is None:
            paragraph = soup.new_tag("p")
        if not paragraph.contents and isinstance(child, NavigableString):
            child = NavigableString(str(child).lstrip())
        paragraph.append(child)
    flush_paragraph()

    first_content = next(
        (
            child
            for child in wrapper.contents
            if not isinstance(child, NavigableString) or str(child).strip()
        ),
        None,
    )
    if getattr(first_content, "name", None) != "p":
        wrapper.insert(0, soup.new_tag("p"))

    item.clear()
    item.attrs = {
        "data-type": TASK_ITEM_TYPE,
        "data-checked": "true" if checked else "false",
    }
    item.append(label)
    item.append(wrapper)


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::render_markdown
# @reason mixed-list grouping is exercised through Markdown rendering
def _canonicalize_task_list(soup, task_list, items):
    task_list.name = "ul"
    task_list.attrs = {"data-type": TASK_LIST_TYPE}
    for item in items:
        _canonicalize_task_item(soup, item)


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::render_markdown
# @reason PyMdown task markup normalization is part of rendering
def _normalize_task_lists(content):
    soup = BeautifulSoup(content, "html.parser")
    task_lists = [
        tag
        for tag in soup.find_all(["ul", "ol"])
        if "task-list" in tag.attrs.get("class", [])
    ]

    for task_list in reversed(task_lists):
        if task_list.parent is None:
            continue
        items = task_list.find_all("li", recursive=False)
        kinds = ["task-list-item" in item.attrs.get("class", []) for item in items]
        if not any(kinds):
            task_list.attrs.pop("class", None)
            continue
        if all(kinds):
            _canonicalize_task_list(soup, task_list, items)
            continue

        groups = []
        for item, is_task in zip(items, kinds):
            if not groups or groups[-1][0] != is_task:
                groups.append((is_task, []))
            groups[-1][1].append(item)

        original_name = task_list.name
        for is_task, grouped_items in groups:
            replacement = soup.new_tag("ul" if is_task else original_name)
            task_list.insert_before(replacement)
            for item in grouped_items:
                replacement.append(item.extract())
            if is_task:
                _canonicalize_task_list(soup, replacement, grouped_items)
        task_list.decompose()

    return str(soup)


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::render_markdown
# @reason Markdown flow whitespace normalization is exercised through rendering
def _collapse_flow_newlines(content):
    """Turn source wrapping into spaces without changing semantic hard breaks."""
    soup = BeautifulSoup(content, "html.parser")
    for node in list(soup.find_all(string=True)):
        parent = node.parent
        if parent is None or parent.name == "pre" or parent.find_parent("pre"):
            continue

        value = str(node)
        if "\n" not in value:
            continue
        if not value.strip():
            if parent.name in FLOW_TEXT_TAGS:
                node.replace_with(" ")
            else:
                node.extract()
            continue

        previous = node.previous_sibling
        if getattr(previous, "name", None) == "br":
            value = re.sub(r"^[ \t]*\n[ \t]*", "", value, count=1)
        value = re.sub(r"[ \t]*\n[ \t]*", " ", value)
        node.replace_with(value)
    return str(soup)


# @testable true
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_markdown_html
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_text_html
# @tests tests_unit/test_014_security.py::test_htmlize_preserves_markdown_tables_and_sanitizes_cells
# @tests tests_unit/test_014_security.py::test_sanitize_html_restricts_task_controls
# @tests tests_unit/test_014_security.py::test_render_markdown_normalizes_indented_html_source
# @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_plain_html_inserts_safe_formatted_content
# @matrix files security : html-sanitization table task-list
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
        task_attrs = _task_attrs(tag)
        if task_attrs is not None:
            tag.attrs = task_attrs
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
        elif name in {"td", "th"}:
            colspan = _safe_span(tag.attrs.get("colspan"))
            rowspan = _safe_span(tag.attrs.get("rowspan"))
            if colspan:
                attrs["colspan"] = colspan
            if rowspan:
                attrs["rowspan"] = rowspan
        tag.attrs = attrs
    return str(soup)


# @testable true
# @tests tests_unit/test_014_security.py::test_render_markdown_collapses_soft_wrapped_lines
# @tests tests_unit/test_014_security.py::test_render_markdown_preserves_code_block_newlines
# @tests tests_unit/test_014_security.py::test_render_markdown_creates_editor_task_lists
# @tests tests_unit/test_014_security.py::test_render_markdown_splits_mixed_task_lists
# @tests tests_unit/test_014_security.py::test_render_markdown_preserves_adjacent_list_kinds
# @tests tests_unit/test_014_security.py::test_render_markdown_normalizes_indented_html_source
# @matrix editor files markdown : code-block hard-break html-source list-kind mixed-list soft-wrap task-list
def render_markdown(text):
    """Render Markdown through the shared sanitized editor-compatible pipeline."""
    if not isinstance(text, str):
        return ""
    if text.lstrip().startswith("<") and HTML_FRAGMENT_PATTERN.search(text):
        text = textwrap.dedent(text).strip()
    converter = markdown.Markdown(
        extensions=[
            "fenced_code",
            "sane_lists",
            "tables",
            "pymdownx.tasklist",
            "pymdownx.tilde",
        ],
        extension_configs={
            "pymdownx.tasklist": {
                "custom_checkbox": True,
                "clickable_checkbox": False,
            },
            "pymdownx.tilde": {"subscript": False},
        },
    )
    normalized = _normalize_task_lists(converter.convert(text))
    return sanitize_html(_collapse_flow_newlines(normalized))


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
        return render_markdown(text)
    if mimetype in CODE_MIMETYPES:
        return f'<pre><code class="{mimetype}">{html_module.escape(text)}</code></pre>'
    if mimetype in TEXT_MIMETYPES.values() or isinstance(text, str):
        return "\n".join(
            f"<p>{html_module.escape(line)}</p>"
            for line in text.split("\n")
            if line.strip()
        )
    return ""
