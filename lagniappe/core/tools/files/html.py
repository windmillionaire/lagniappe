"""Named HTML safety policies, Markdown rendering, and text conversion."""

import html as html_module
import re
import textwrap
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString
import markdown
import nh3

from .constants import CODE_MIMETYPES, TEXT_MIMETYPES


NARROW_HTML_TAGS = {
    "a", "blockquote", "br", "code", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "li", "ol", "p", "pre", "s", "strike",
    "strong", "sub", "sup", "table", "tbody", "td", "th", "thead",
    "tr", "u", "ul", "del",
}
CLEAN_CONTENT_TAGS = {
    "applet", "audio", "base", "button", "canvas", "embed", "form", "frame",
    "frameset", "iframe", "img", "input", "link", "math", "meta",
    "noscript", "object", "option", "picture", "script", "select", "source",
    "style", "svg", "textarea", "track", "video",
}
SAFE_LINK_SCHEMES = {"http", "https", "mailto"}
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
IMAGE_STYLE_PROPERTIES = {
    "display",
    "float",
    "margin",
    "margin-left",
    "margin-right",
    "width",
}
MAX_IMAGE_TEXT_ATTRIBUTE = 500


# @testable true
# @tests tests_unit/test_014_security.py::test_safe_html_policy_is_typed_idempotent_and_ephemeral
# @matrix security : nominal-type serialization trust-loss
class SafeHTML(str):
    """HTML that passed its final named server-side safety policy."""

    __slots__ = ()


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @covered-by lagniappe/core/tools/files/html.py::sanitize_form_content_html
# @covered-by lagniappe/core/tools/files/html.py::sanitize_public_document_html
# @covered-by lagniappe/core/tools/files/html.py::htmlize
# @covered-by lagniappe/core/tools/files/html.py::render_markdown
# @reason private constructor is statically restricted to named final policies
def _stamp_safe_html(value):
    """Stamp output only after a named policy has completed every transform."""
    return SafeHTML(value)


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @reason nh3 attribute callback is exercised through the narrow policy
def _bounded_span_attribute(_tag, attribute, value):
    if attribute not in {"colspan", "rowspan"}:
        return value
    try:
        span = int(value)
    except (TypeError, ValueError):
        return None
    return str(span) if 1 < span <= 100 else None


_TASK_ATTRIBUTE_VALUES = {
    "ul": {"data-type": {TASK_LIST_TYPE}},
    "li": {
        "data-type": {TASK_ITEM_TYPE},
        "data-checked": {"true", "false"},
    },
}
_NARROW_ATTRIBUTES = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
_NARROW_CLEANER = nh3.Cleaner(
    tags=NARROW_HTML_TAGS,
    clean_content_tags=CLEAN_CONTENT_TAGS,
    attributes=_NARROW_ATTRIBUTES,
    attribute_filter=_bounded_span_attribute,
    strip_comments=True,
    link_rel="noopener noreferrer",
    tag_attribute_values=_TASK_ATTRIBUTE_VALUES,
    url_schemes=SAFE_LINK_SCHEMES,
    url_relative="pass_through",
)
_RICH_CLEANER = nh3.Cleaner(
    tags=NARROW_HTML_TAGS | {"img"},
    clean_content_tags=CLEAN_CONTENT_TAGS - {"img"},
    attributes={
        **_NARROW_ATTRIBUTES,
        "img": {"alt", "src", "style", "title"},
    },
    attribute_filter=_bounded_span_attribute,
    strip_comments=True,
    link_rel="noopener noreferrer",
    tag_attribute_values=_TASK_ATTRIBUTE_VALUES,
    url_schemes=SAFE_LINK_SCHEMES,
    url_relative="pass_through",
    filter_style_properties=IMAGE_STYLE_PROPERTIES,
)


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_strip_tags
# @pair utility:html-stripping
def strip_tags(html_content):
    """Strip HTML tags and collapse whitespace in text content."""
    if not isinstance(html_content, str):
        return html_content
    soup = BeautifulSoup(html_content, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()


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

    item.clear()
    item.attrs = {
        "data-type": TASK_ITEM_TYPE,
        "data-checked": "true" if checked else "false",
    }
    for child in content:
        if isinstance(child, NavigableString) and not str(child).strip():
            continue
        item.append(child)


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


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @reason task ancestry reduction is exercised through the named policies
def _prepare_canonical_task_lists(content):
    """Reduce only exact task-list ancestry to semantic list state."""
    soup = BeautifulSoup(content, "html.parser")
    for task_list in soup.find_all("ul", attrs={"data-type": TASK_LIST_TYPE}):
        element_children = task_list.find_all(recursive=False)
        items = [child for child in element_children if child.name == "li"]
        valid = bool(items) and len(items) == len(element_children) and all(
            item.get("data-type") == TASK_ITEM_TYPE for item in items
        )
        if not valid:
            task_list.attrs = {}
            for item in items:
                item.attrs = {}
            continue

        task_list.attrs = {"data-type": TASK_LIST_TYPE}
        for item in items:
            checked = str(item.get("data-checked", "false")).lower() == "true"
            wrapper = item.find("div", recursive=False)
            if wrapper is not None:
                content_nodes = [child.extract() for child in list(wrapper.contents)]
            else:
                label = item.find("label", recursive=False)
                if label is not None:
                    label.extract()
                content_nodes = [child.extract() for child in list(item.contents)]
            item.clear()
            item.attrs = {
                "data-type": TASK_ITEM_TYPE,
                "data-checked": "true" if checked else "false",
            }
            for child in content_nodes:
                if isinstance(child, NavigableString) and not str(child).strip():
                    continue
                item.append(child)
    return str(soup)


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @reason fixed task scaffolding is exercised through the narrow policy
def _rebuild_task_item(soup, item):
    """Rebuild fixed inert editor scaffolding from validated semantic state."""
    checked = item.get("data-checked") == "true"
    content = [child.extract() for child in list(item.contents)]

    label = soup.new_tag("label")
    checkbox = soup.new_tag("input")
    checkbox.attrs = {"type": "checkbox", "disabled": ""}
    if checked:
        checkbox.attrs["checked"] = ""
    label.append(checkbox)
    label.append(soup.new_tag("span"))

    wrapper = soup.new_tag("div")
    paragraph = None

    # @testable false
    # @covered-by lagniappe/core/tools/files/html.py::_rebuild_task_item
    # @reason local paragraph flush is part of fixed task scaffolding
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
# @covered-by lagniappe/core/tools/files/html.py::sanitize_html
# @reason link and task canonicalization is exercised through the narrow policy
def _finalize_clean_html(content):
    """Canonicalize links and rebuild task controls after nh3 cleaning."""
    soup = BeautifulSoup(content, "html.parser")
    for link in soup.find_all("a"):
        if link.get("href"):
            link.attrs["target"] = "_blank"
            link.attrs["rel"] = "noopener noreferrer"
        else:
            link.attrs.pop("target", None)
            link.attrs.pop("rel", None)

    valid_task_items = set()
    valid_task_lists = set()
    task_lists = soup.find_all("ul", attrs={"data-type": TASK_LIST_TYPE})
    for task_list in reversed(task_lists):
        element_children = task_list.find_all(recursive=False)
        items = [child for child in element_children if child.name == "li"]
        if not items or len(items) != len(element_children) or any(
            item.get("data-type") != TASK_ITEM_TYPE
            or item.get("data-checked") not in {"true", "false"}
            for item in items
        ):
            task_list.attrs = {}
            continue
        valid_task_lists.add(id(task_list))
        for item in items:
            _rebuild_task_item(soup, item)
            valid_task_items.add(id(item))

    for task_list in soup.find_all("ul"):
        if id(task_list) not in valid_task_lists:
            task_list.attrs = {}
    for item in soup.find_all("li"):
        if id(item) not in valid_task_items:
            item.attrs = {}
    return str(soup)


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_form_content_html
# @covered-by lagniappe/core/tools/files/html.py::sanitize_public_document_html
# @reason image layout parsing is exercised through the richer named policies
def _canonical_image_style(value):
    if not isinstance(value, str) or not value.strip():
        return None
    declarations = {}
    for declaration in value.split(";"):
        if ":" not in declaration:
            continue
        name, raw_value = declaration.split(":", 1)
        declarations[name.strip().lower()] = raw_value.strip().lower()

    width_match = re.fullmatch(r"(\d{1,3})(?:\.0+)?%", declarations.get("width", ""))
    width = int(width_match.group(1)) if width_match else 100
    width = min(100, max(10, width))
    float_value = declarations.get("float", "none")
    if float_value not in {"left", "right", "none"}:
        float_value = "none"

    styles = [f"width: {width}%", "display: block"]
    if float_value in {"left", "right"}:
        styles.extend(
            [
                f"float: {float_value}",
                (
                    "margin: 0 1em 1em 0"
                    if float_value == "left"
                    else "margin: 0 0 1em 1em"
                ),
            ]
        )
    else:
        styles.append("float: none")
        margin_left = declarations.get("margin-left")
        margin_right = declarations.get("margin-right")
        if margin_left == "auto" and margin_right != "auto":
            styles.extend(["margin-left: auto", "margin-right: 0"])
        elif margin_right == "auto" and margin_left != "auto":
            styles.extend(["margin-right: auto", "margin-left: 0"])
        else:
            styles.extend(["margin-left: auto", "margin-right: auto"])
    return "; ".join(styles)


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_form_content_html
# @covered-by lagniappe/core/tools/files/html.py::sanitize_public_document_html
# @reason owned-image matching is exercised through the richer named policies
def _same_resource_url(source, target):
    source_url = urlsplit(str(source or ""))
    target_url = urlsplit(str(target or ""))
    if not source_url.path or source_url.path != target_url.path:
        return False
    if source_url.netloc or target_url.netloc:
        return bool(source_url.netloc and source_url.netloc == target_url.netloc)
    return True


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_form_content_html
# @covered-by lagniappe/core/tools/files/html.py::sanitize_public_document_html
# @reason image metadata bounding is exercised through the richer named policies
def _bounded_plain_attribute(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    return value[:MAX_IMAGE_TEXT_ATTRIBUTE] or None


# @testable false
# @covered-by lagniappe/core/tools/files/html.py::sanitize_form_content_html
# @covered-by lagniappe/core/tools/files/html.py::sanitize_public_document_html
# @reason owned-image transformation is exercised through the richer policies
def _prepare_owned_images(content, image_sources):
    soup = BeautifulSoup(content, "html.parser")
    sources = list(image_sources or [])
    for image in list(soup.find_all("img")):
        match = next(
            (
                rewritten
                for original, rewritten in sources
                if _same_resource_url(image.get("src"), original)
            ),
            None,
        )
        if not match:
            image.decompose()
            continue
        attrs = {"src": match}
        for name in ("alt", "title"):
            if value := _bounded_plain_attribute(image.get(name)):
                attrs[name] = value
        if style := _canonical_image_style(image.get("style")):
            attrs["style"] = style
        image.attrs = attrs
    return str(soup)


# @testable true
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_markdown_html
# @tests tests_unit/test_014_security.py::test_htmlize_sanitizes_text_html
# @tests tests_unit/test_014_security.py::test_htmlize_preserves_markdown_tables_and_sanitizes_cells
# @tests tests_unit/test_014_security.py::test_sanitize_html_restricts_task_controls
# @tests tests_unit/test_014_security.py::test_sanitize_html_drops_active_content_and_unwraps_unknown_markup
# @tests tests_unit/test_014_security.py::test_sanitize_html_rejects_obfuscated_active_link_schemes
# @tests tests_unit/test_014_security.py::test_sanitize_html_keeps_reviewed_link_schemes_and_fixed_attributes
# @tests tests_unit/test_014_security.py::test_sanitize_html_bounds_table_spans
# @tests tests_unit/test_014_security.py::test_sanitize_html_strips_task_attributes_outside_exact_ancestry
# @tests tests_unit/test_014_security.py::test_render_markdown_normalizes_indented_html_source
# @tests tests_e2e/004_projects/test_004d_document.py::test_pasting_plain_html_inserts_safe_formatted_content
# @matrix files security : active-content comments html-sanitization links malformed-markup relative-url table task-list unknown-wrapper url-scheme
def sanitize_html(content) -> SafeHTML:
    """Apply the narrow semantic HTML policy used by Markdown and files."""
    if not isinstance(content, str) or not content:
        return _stamp_safe_html("")
    reduced = _prepare_canonical_task_lists(content)
    return _stamp_safe_html(_finalize_clean_html(_NARROW_CLEANER.clean(reduced)))


# @testable true
# @tests tests_unit/test_014_security.py::test_form_content_policy_keeps_only_owned_images
# @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
# @matrix form-html security : html-sanitization inner-html owned-image
def sanitize_form_content_html(content, form, field_id) -> SafeHTML:
    """Apply the form-content policy and retain only this field's owned images."""
    if not isinstance(content, str) or not content:
        return _stamp_safe_html("")
    image_sources = []
    prefix = f"image_{field_id}_"
    for name, definition in getattr(form, "assets", {}).items():
        if not name.startswith(prefix) or definition.get("type") != "image":
            continue
        asset = form.get_asset(name)
        if asset and getattr(asset, "url", None):
            image_sources.append((asset.url, asset.url))
    prepared = _prepare_owned_images(content, image_sources)
    reduced = _prepare_canonical_task_lists(prepared)
    return _stamp_safe_html(_finalize_clean_html(_RICH_CLEANER.clean(reduced)))


# @testable true
# @tests tests_unit/test_014_security.py::test_public_document_policy_keeps_only_rewritten_owned_images
# @matrix public-pages security : html-sanitization owned-image
def sanitize_public_document_html(content, image_sources) -> SafeHTML:
    """Apply the anonymous public-document policy to transformed editor HTML."""
    if not isinstance(content, str) or not content:
        return _stamp_safe_html("")
    prepared = _prepare_owned_images(content, image_sources)
    reduced = _prepare_canonical_task_lists(prepared)
    return _stamp_safe_html(_finalize_clean_html(_RICH_CLEANER.clean(reduced)))


# @testable true
# @tests tests_unit/test_014_security.py::test_render_markdown_collapses_soft_wrapped_lines
# @tests tests_unit/test_014_security.py::test_render_markdown_preserves_code_block_newlines
# @tests tests_unit/test_014_security.py::test_render_markdown_creates_editor_task_lists
# @tests tests_unit/test_014_security.py::test_render_markdown_splits_mixed_task_lists
# @tests tests_unit/test_014_security.py::test_render_markdown_preserves_adjacent_list_kinds
# @tests tests_unit/test_014_security.py::test_render_markdown_normalizes_indented_html_source
# @matrix editor files markdown : code-block hard-break html-source list-kind mixed-list soft-wrap task-list
def render_markdown(text) -> SafeHTML:
    """Render Markdown through the shared sanitized editor-compatible pipeline."""
    if not isinstance(text, str):
        return _stamp_safe_html("")
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
# @tests tests_unit/test_014_security.py::test_htmlize_escapes_code_plain_text_and_mimetype_attributes
# @matrix files security : code html html-sanitization markdown mimetype plain-text table
def htmlize(text, mimetype) -> SafeHTML:
    """Convert text content to sanitized HTML for its MIME type."""
    if mimetype == "text/html":
        return sanitize_html(text)
    if mimetype == "text/markdown":
        return render_markdown(text)
    if not isinstance(text, str):
        return _stamp_safe_html("")
    if mimetype in CODE_MIMETYPES:
        safe_mimetype = html_module.escape(str(mimetype), quote=True)
        escaped = html_module.escape(text)
        return _stamp_safe_html(
            f'<pre><code class="{safe_mimetype}">{escaped}</code></pre>'
        )
    if mimetype in TEXT_MIMETYPES.values() or isinstance(text, str):
        return _stamp_safe_html("\n".join(
            f"<p>{html_module.escape(line)}</p>"
            for line in text.split("\n")
            if line.strip()
        ))
    return _stamp_safe_html("")
