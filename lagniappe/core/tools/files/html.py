"""Named HTML safety policies, Markdown rendering, and text conversion."""

from collections.abc import Iterable
import html as html_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.form import Form
    from lagniappe.core.entities.history import FormHistory
import re
import textwrap
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4.element import NavigableString
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


class SafeHTML(str):
    """HTML that passed its final named server-side safety policy."""

    __slots__ = ()


def _stamp_safe_html(value):
    """Stamp output only after a named policy has completed every transform."""
    return SafeHTML(value)


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


def strip_tags[T](html_content: T, *, preserve_whitespace: bool = False) -> str | T:
    """Strip HTML tags, optionally retaining multiline text's whitespace."""
    if not isinstance(html_content, str):
        return html_content
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ")
    return text if preserve_whitespace else re.sub(r"\s+", " ", text).strip()


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


def _canonicalize_task_list(soup, task_list, items):
    task_list.name = "ul"
    task_list.attrs = {"data-type": TASK_LIST_TYPE}
    for item in items:
        _canonicalize_task_item(soup, item)


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
        for item, is_task in zip(items, kinds, strict=True):
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
            block_boundary = any(
                getattr(sibling, "name", None) in TASK_BLOCK_TAGS
                for sibling in (node.previous_sibling, node.next_sibling)
            )
            if parent.name in FLOW_TEXT_TAGS and not block_boundary:
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


def _same_resource_url(source, target):
    source_url = urlsplit(str(source or ""))
    target_url = urlsplit(str(target or ""))
    if not source_url.path or source_url.path != target_url.path:
        return False
    if source_url.netloc or target_url.netloc:
        return bool(source_url.netloc and source_url.netloc == target_url.netloc)
    return True


def _bounded_plain_attribute(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    return value[:MAX_IMAGE_TEXT_ATTRIBUTE] or None


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


def _retain_original_images(content, original_html):
    """Keep existing image layout when Markdown rewrites the surrounding text."""
    originals = BeautifulSoup(original_html, "html.parser").find_all("img")
    soup = BeautifulSoup(content, "html.parser")
    for image in soup.find_all("img"):
        for index, original in enumerate(originals):
            if _same_resource_url(image.get("src"), original.get("src")):
                image.attrs = dict(original.attrs)
                # Repeated uses of one image can have different layouts.
                originals.pop(index)
                break
    return str(soup)


def sanitize_html(content: object) -> SafeHTML:
    """Apply the narrow semantic HTML policy used by Markdown and files."""
    if not isinstance(content, str) or not content:
        return _stamp_safe_html("")
    reduced = _prepare_canonical_task_lists(content)
    return _stamp_safe_html(_finalize_clean_html(_NARROW_CLEANER.clean(reduced)))


def sanitize_form_content_html(content: object, form: Form | FormHistory, field_id: str) -> SafeHTML:
    """Apply the form-content policy and retain only this field's owned images."""
    if not isinstance(content, str) or not content:
        return _stamp_safe_html("")
    image_sources = []
    prefix = f"image_{field_id}_"
    for name, definition in getattr(form, "assets", {}).items():
        if not name.startswith(prefix) or definition.get("type") != "image":
            continue
        asset = form.get_asset(name)
        if asset and (url := getattr(asset, "url", None)):
            image_sources.append((url, url))
    prepared = _prepare_owned_images(content, image_sources)
    reduced = _prepare_canonical_task_lists(prepared)
    return _stamp_safe_html(_finalize_clean_html(_RICH_CLEANER.clean(reduced)))


def sanitize_public_document_html(content: object, image_sources: Iterable[tuple[str, str]]) -> SafeHTML:
    """Apply the anonymous public-document policy to transformed editor HTML."""
    if not isinstance(content, str) or not content:
        return _stamp_safe_html("")
    prepared = _prepare_owned_images(content, image_sources)
    reduced = _prepare_canonical_task_lists(prepared)
    return _stamp_safe_html(_finalize_clean_html(_RICH_CLEANER.clean(reduced)))


def render_markdown(text: object, *, image_sources: Iterable[tuple[str, str]] | None = None, original_html: str | None = None) -> SafeHTML:
    """Render Markdown safely, optionally retaining images from existing content."""
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
        ] + (["attr_list"] if image_sources is not None else []),
        extension_configs={
            "pymdownx.tasklist": {
                "custom_checkbox": True,
                "clickable_checkbox": False,
            },
            "pymdownx.tilde": {"subscript": False},
        },
    )
    normalized = _normalize_task_lists(converter.convert(text))
    if image_sources is not None:
        if original_html:
            normalized = _retain_original_images(normalized, original_html)
        # Browser-local image identities are not general allowed URL schemes.
        # Carry only explicitly supplied identities through the rich sanitizer
        # using inert relative placeholders, then restore their draft tokens.
        sources, local_sources = [], {}
        for original, rewritten in image_sources:
            if re.fullmatch(r"draft-image:[A-Za-z0-9_-]{1,100}", str(rewritten)):
                placeholder = f"/__builder_draft_image__/{rewritten.split(':', 1)[1]}"
                local_sources[placeholder] = rewritten
                sources.append((original, placeholder))
            else:
                sources.append((original, rewritten))
        rendered = str(sanitize_public_document_html(
            _collapse_flow_newlines(normalized), sources,
        ))
        for placeholder, original in local_sources.items():
            rendered = rendered.replace(f'src="{placeholder}"', f'src="{original}"')
        return _stamp_safe_html(rendered)
    return sanitize_html(_collapse_flow_newlines(normalized))


def htmlize(text: object, mimetype: str | None) -> SafeHTML:
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
