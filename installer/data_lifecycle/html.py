"""Sanitized, network-free owner-oriented offline archive presentation."""

from __future__ import annotations

from collections import defaultdict
import html as html_stdlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re

from .portable import portable_name, unportable_name
from .provider import DataLifecycleError


SECTIONS = (
    ("user", "Users"),
    ("group", "Groups"),
    ("public_group", "Public groups"),
    ("project", "Projects"),
    ("category", "Categories"),
    ("users", "User category"),
    ("form", "Forms"),
    ("page", "Pages"),
    ("model", "Model tasks"),
    ("task", "Tasks"),
    ("filter", "Filters"),
    ("file", "Files"),
    ("note", "Notes"),
    ("report", "Reports"),
    ("message_conversation", "Conversations (private)"),
)
REFERENCE_PATTERN = re.compile(
    r"\Aref:(?:(?P<namespace>[^:]+):)?(?P<type>[^:]+):(?P<id>[^:]+)\Z"
)
REMOTE_PATTERN = re.compile(r"(?i)(?:https?:)?//|\b(?:https?|ftp|data):")
ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "dd", "del", "div", "dl", "dt",
    "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
    "img", "li", "mark", "ol", "p", "pre", "s", "section", "small", "span", "strong",
    "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}


STYLE = """
:root{font-family:system-ui,sans-serif;color:#17202a;background:#f7f8fa;line-height:1.5}
body{max-width:72rem;margin:auto;padding:1rem}a{color:#155eef}header,article,section{background:#fff;border:1px solid #d8dee8;border-radius:.6rem;padding:1rem;margin:1rem 0}
nav a{margin-right:1rem}.badges span{display:inline-block;border-radius:1rem;background:#e8edf5;padding:.15rem .55rem;margin-right:.3rem;font-size:.8rem}
.warning{border-color:#b54708;background:#fffaeb}.private{border-color:#b42318}.muted{color:#596579}.properties{width:100%;border-collapse:collapse}.properties th,.properties td{border-top:1px solid #e4e7ec;padding:.45rem;text-align:left;vertical-align:top}.properties th{width:16rem}.missing{color:#b42318}.search input{width:100%;padding:.6rem}.sensitive{background:#fff1f0;border-color:#b42318}
@media(max-width:40rem){body{padding:.5rem}.properties th,.properties td{display:block;width:auto}.properties th{padding-bottom:0}}
@media print{.search,script{display:none}body{max-width:none;background:#fff}header,article,section{break-inside:avoid;border-color:#aaa}}
""".strip()


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_html_sanitizer_removes_active_and_remote_content
# @pairs portable-archive:html-sanitization portable-archive:no-network
def sanitize_stored_html(value: str, *, page_path: str, identities: set[tuple[str, str, str]], assets=None) -> str:
    """Keep inert document markup and rewrite known portable links locally."""
    from bs4 import BeautifulSoup, Comment

    soup = BeautifulSoup(str(value or ""), "html.parser")
    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()
    for tag in list(soup.find_all(True)):
        name = tag.name.casefold()
        if name not in ALLOWED_TAGS:
            tag.unwrap() if name not in {"script", "style", "iframe", "object", "embed", "form"} else tag.decompose()
            continue
        allowed_attributes = {"a": {"href", "title"}, "img": {"src", "alt", "title"}}.get(name, set())
        for attribute in list(tag.attrs):
            if attribute.casefold().startswith("on") or attribute not in allowed_attributes:
                del tag.attrs[attribute]
        for attribute in ("href", "src"):
            raw = str(tag.attrs.get(attribute) or "").strip()
            if not raw:
                continue
            if raw in (assets or {}):
                tag.attrs[attribute] = posixpath.relpath((assets or {})[raw], posixpath.dirname(page_path))
            else:
                rewritten = _rewrite_reference_url(raw, page_path, identities)
                if rewritten:
                    tag.attrs[attribute] = rewritten
                else:
                    del tag.attrs[attribute]
                    if name == "a":
                        tag.unwrap()
    return str(soup)


# @testable false
# @covered-by installer/data_lifecycle/html.py::sanitize_stored_html
# @reason URL classification and rewriting are sanitizer implementation details
def _rewrite_reference_url(value, page_path, identities):
    if REMOTE_PATTERN.search(value) or value.casefold().startswith(("javascript:", "data:")):
        return None
    match = REFERENCE_PATTERN.fullmatch(value.strip("#/"))
    if not match:
        return value if value.startswith("#") and not value.startswith("#/") else None
    try:
        identity = (
            unportable_name(match.group("namespace")) if match.group("namespace") else "",
            unportable_name(match.group("type")),
            unportable_name(match.group("id")),
        )
    except DataLifecycleError:
        return None
    if identity not in identities:
        return None
    target = f"site/{portable_name(identity[1])}/{portable_name(identity[2])}/index.html"
    return posixpath.relpath(target, posixpath.dirname(page_path))


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_html_archive_renders_owner_sections_and_local_navigation
# @pairs portable-archive:offline-html portable-archive:owner-content portable-archive:navigation
class OfflineHTMLBuilder:
    """Render presentation pages using only already-portable records and assets."""

    def __init__(self, root, *, backup_id, created_at, consistency, warnings=()):
        self.root = Path(root)
        self.backup_id = backup_id
        self.created_at = created_at
        self.consistency = consistency
        self.warnings = list(warnings)

    def build(self, records, assets=()):
        records = list(records)
        identity_set = {
            (
                record["identity"]["namespace"],
                record["identity"]["type"],
                record["identity"]["id"],
            )
            for record in records
        }
        asset_by_logical = {asset["logical_id"]: asset for asset in assets}
        sections = defaultdict(list)
        search = []
        pages = []
        for record in records:
            identity = record["identity"]
            semantic_type = identity["type"]
            title = self._title(record)
            relative = PurePosixPath(
                "site", portable_name(semantic_type), portable_name(identity["id"]), "index.html"
            )
            sections[semantic_type].append((title, relative.as_posix(), record))
            self._write(
                relative,
                self._record_page(record, title, relative.as_posix(), identity_set, asset_by_logical),
            )
            pages.append(relative.as_posix())
            search.append(
                {
                    "title": title,
                    "type": semantic_type,
                    "id": identity["id"],
                    "text": self._search_text(record),
                    "url": posixpath.relpath(relative.as_posix(), "site"),
                }
            )
        index = self._index_page(sections)
        self._write(PurePosixPath("site", "index.html"), index)
        search_payload = "window.LAGNIAPPE_SEARCH_INDEX=" + json.dumps(
            search, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ) + ";\n" + """const q=document.getElementById('search'),out=document.getElementById('search-results');
q?.addEventListener('input',()=>{const value=q.value.toLowerCase();out.textContent='';if(!value)return;
for(const item of window.LAGNIAPPE_SEARCH_INDEX.filter(x=>(x.title+' '+x.text).toLowerCase().includes(value)).slice(0,50)){
const li=document.createElement('li'),a=document.createElement('a');a.href=item.url;a.textContent=item.title+' ('+item.type+')';li.append(a);out.append(li);}});
"""
        self._write(PurePosixPath("site", "search-index.js"), search_payload)
        return {"pages": len(pages) + 1, "paths": ["site/index.html", *pages, "site/search-index.js"]}

    def _index_page(self, sections):
        content = [
            f"<h1>Lagniappe private archive</h1><p>Created {html_stdlib.escape(self.created_at)} from backup <code>{html_stdlib.escape(self.backup_id)}</code>.</p>",
            f"<p class='warning'>Consistency: {html_stdlib.escape(self.consistency)}. Assets were collected later and can be newer.</p>",
            "<div class='search'><label>Search <input id='search' type='search'></label><ul id='search-results'></ul></div>",
        ]
        if self.warnings:
            content.append(f"<p class='warning'>{len(self.warnings)} archive warning(s); see README.md for details.</p>")
        for semantic_type, label in SECTIONS:
            values = sections.get(semantic_type, [])
            if not values:
                continue
            items = "".join(
                f"<li><a href='{html_stdlib.escape(posixpath.relpath(path, 'site'))}'>{html_stdlib.escape(title)}</a></li>"
                for title, path, _record in values
            )
            content.append(f"<section><h2>{html_stdlib.escape(label)} ({len(values)})</h2><ul>{items}</ul></section>")
        script = "<script src='search-index.js'></script>"
        return self._document("Lagniappe archive", "".join(content) + script)

    def _record_page(self, record, title, page_path, identities, assets):
        identity = record["identity"]
        sensitive = identity["type"] == "message_conversation"
        badges = []
        properties = record["properties"]
        if properties.get("active") is False:
            badges.append("inactive")
        if properties.get("public") is False or properties.get("visibility") == "private":
            badges.append("private")
        if sensitive:
            badges.append("sensitive private content")
        rows = []
        for name, value in sorted(properties.items()):
            rows.append(
                f"<tr><th>{html_stdlib.escape(name)}</th><td>{self._render_value(value, page_path, identities, assets)}</td></tr>"
            )
        badge_html = "".join(f"<span>{html_stdlib.escape(badge)}</span>" for badge in badges)
        home = posixpath.relpath("site/index.html", posixpath.dirname(page_path))
        body = (
            f"<nav><a href='{home}'>Archive home</a></nav>"
            f"<article class='{'sensitive' if sensitive else ''}'><h1>{html_stdlib.escape(title)}</h1>"
            f"<p class='muted'>{html_stdlib.escape(identity['type'])} · {html_stdlib.escape(identity['id'])}</p>"
            f"<div class='badges'>{badge_html}</div><table class='properties'>{''.join(rows)}</table>"
            f"{self._render_children(record, page_path, identities, assets)}</article>"
        )
        return self._document(title, body)

    def _render_children(self, record, page_path, identities, assets):
        sections = []
        labels = {"task_history": "Task history", "message": "Messages"}
        for child_type, children in sorted((record.get("children") or {}).items()):
            items = []
            for child in children:
                key = child["key"]
                key_value = key.get("name", key.get("id"))
                rows = "".join(
                    f"<tr><th>{html_stdlib.escape(name)}</th><td>{self._render_value(value, page_path, identities, assets)}</td></tr>"
                    for name, value in sorted(child["properties"].items())
                )
                items.append(
                    f"<article class='{'sensitive' if child_type == 'message' else ''}'>"
                    f"<h3>{html_stdlib.escape(child_type.replace('_', ' ').title())}</h3>"
                    f"<p class='muted'>Child key: {html_stdlib.escape(str(key_value))}</p>"
                    f"<table class='properties'>{rows}</table></article>"
                )
            sections.append(
                f"<section><h2>{html_stdlib.escape(labels[child_type])} ({len(children)})</h2>"
                f"{''.join(items)}</section>"
            )
        return "".join(sections)

    def _render_value(self, value, page_path, identities, assets):
        if value is None:
            return "<span class='muted'>None</span>"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (int, float)):
            return html_stdlib.escape(str(value))
        if isinstance(value, str):
            return html_stdlib.escape(value)
        if isinstance(value, list):
            return "<ul>" + "".join(f"<li>{self._render_value(item, page_path, identities, assets)}</li>" for item in value) + "</ul>"
        if not isinstance(value, dict):
            return html_stdlib.escape(str(value))
        if "$ref" in value:
            reference = value["$ref"]
            identity = (reference.get("namespace") or "", reference["type"], reference["id"])
            if identity not in identities:
                return "<span class='missing'>Unavailable reference</span>"
            target = f"site/{portable_name(identity[1])}/{portable_name(identity[2])}/index.html"
            href = posixpath.relpath(target, posixpath.dirname(page_path))
            return f"<a href='{html_stdlib.escape(href)}'>{html_stdlib.escape(identity[1])}: {html_stdlib.escape(identity[2])}</a>"
        if "$missing_ref" in value:
            missing = value["$missing_ref"]
            return f"<span class='missing'>Unavailable link ({html_stdlib.escape(missing['warning_id'])})</span>"
        if "$asset" in value:
            tag = value["$asset"]
            asset = assets.get(tag["logical_id"])
            if not asset or asset.get("status") != "available":
                warning = (asset or {}).get("warning_id", "asset-unavailable")
                return f"<span class='missing'>Unavailable asset ({html_stdlib.escape(warning)})</span>"
            if asset.get("type") == "html" and asset.get("canonical_document"):
                canonical = self.root / PurePosixPath(asset["canonical_document"])
                local_assets = {}
                entity = asset.get("entity") or {}
                for candidate in assets.values():
                    if (
                        candidate.get("status") == "available"
                        and (candidate.get("entity") or {}) == entity
                    ):
                        local_assets[candidate.get("name")] = candidate["path"]
                        local_assets[candidate.get("logical_id")] = candidate["path"]
                        local_assets[
                            posixpath.relpath(
                                candidate["path"],
                                posixpath.dirname(asset["canonical_document"]),
                            )
                        ] = candidate["path"]
                sanitized = sanitize_stored_html(
                    canonical.read_text(encoding="utf-8"),
                    page_path=page_path,
                    identities=identities,
                    assets=local_assets,
                )
                return f"<section aria-label='Archived document'>{sanitized}</section>"
            href = posixpath.relpath(asset["path"], posixpath.dirname(page_path))
            label = html_stdlib.escape(tag.get("name") or "asset")
            preview = ""
            if str(asset.get("media_type") or "").startswith("image/"):
                preview = f"<br><img src='{html_stdlib.escape(href)}' alt='{label}' loading='lazy'>"
            return f"<a href='{html_stdlib.escape(href)}'>{label}</a>{preview}"
        return "<dl>" + "".join(
            f"<dt>{html_stdlib.escape(str(key))}</dt><dd>{self._render_value(nested, page_path, identities, assets)}</dd>"
            for key, nested in sorted(value.items())
        ) + "</dl>"

    @staticmethod
    def _title(record):
        properties = record["properties"]
        for key in ("name", "title", "email", "filename", "body"):
            value = properties.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:160]
        identity = record["identity"]
        return f"{identity['type'].replace('_', ' ').title()} {identity['id']}"

    @staticmethod
    def _search_text(record):
        text = []
        def visit(value):
            if isinstance(value, str):
                text.append(value)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict) and not any(key.startswith("$") for key in value):
                for item in value.values():
                    visit(item)
        visit(record["properties"])
        visit(record.get("children") or {})
        return " ".join(text)[:20_000]

    @staticmethod
    def _document(title, body):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src 'self' data:; media-src 'self'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta http-equiv='Content-Security-Policy' content=\"{csp}\">"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html_stdlib.escape(title)}</title><style>{STYLE}</style></head><body>{body}</body></html>\n"
        )

    def _write(self, relative, content):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_text(content, encoding="utf-8", newline="\n")


__all__ = ["OfflineHTMLBuilder", "sanitize_stored_html"]
