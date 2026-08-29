"""Sanitized, network-free owner-oriented offline archive presentation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import html as html_stdlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re

from .portable import portable_name, unportable_name
from .provider import DataLifecycleError


INDEX_SECTIONS = (
    ("project", "Projects"),
    ("category", "Categories"),
    ("note", "Notes"),
    ("report", "Reports"),
    ("form", "Forms"),
    ("user", "People"),
    ("group", "Groups"),
    ("public_group", "Public groups"),
    ("message_conversation", "Conversations (private)"),
)
LINKED_TYPES = {"page", "model", "task", "file"}
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
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#182230;background:#f5f7fa;line-height:1.55;color-scheme:light}
*{box-sizing:border-box}body{max-width:76rem;margin:auto;padding:1.5rem}a{color:#175cd3;text-underline-offset:.16em}h1,h2,h3{line-height:1.2}h1{font-size:clamp(2rem,5vw,3rem);margin:.25rem 0 1rem}h2{font-size:1.3rem;margin:0 0 1rem}h3{font-size:1.05rem;margin:.2rem 0}.archive-header,.record,.panel{background:#fff;border:1px solid #d0d5dd;border-radius:.8rem;padding:clamp(1rem,3vw,2rem);margin:1rem 0;box-shadow:0 1px 2px #1018280d}.archive-header{border-top:4px solid #3264a8}.eyebrow{color:#475467;font-size:.82rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase}.breadcrumbs{display:flex;gap:.5rem;flex-wrap:wrap;margin:.25rem 0 1.5rem}.breadcrumbs span{color:#667085}.summary{color:#475467;max-width:52rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));gap:1rem}.record-list{list-style:none;padding:0;margin:0}.record-list li{border-top:1px solid #e4e7ec;padding:.8rem 0}.record-list li:first-child{border-top:0}.record-list a{font-weight:650}.record-list small{display:block;color:#667085;margin-top:.2rem}.badges{display:flex;gap:.4rem;flex-wrap:wrap;margin:.75rem 0}.badges span{display:inline-block;border-radius:999px;background:#eaf0f8;color:#344054;padding:.2rem .65rem;font-size:.8rem;font-weight:650}.warning{border:1px solid #f5c27a;border-radius:.65rem;background:#fffaeb;color:#7a2e0e;padding:.8rem 1rem}.muted{color:#667085}.missing{color:#b42318}.search{margin:1.5rem 0}.search label{font-weight:650}.search input{display:block;width:100%;margin-top:.4rem;padding:.75rem;border:1px solid #98a2b3;border-radius:.5rem;font:inherit}.document{border:0;border-left:4px solid #d0d5dd;border-radius:0;padding:.2rem 0 .2rem 1.25rem;margin:1.25rem 0}.media img{display:block;max-width:100%;max-height:46rem;width:auto;height:auto;margin:1rem auto;border-radius:.6rem}.details{display:grid;grid-template-columns:minmax(8rem,14rem) 1fr;gap:.55rem 1rem;margin:1rem 0}.details dt{font-weight:650}.details dd{margin:0}.meta{border-top:1px solid #e4e7ec;color:#667085;font-size:.88rem;margin-top:1.5rem;padding-top:1rem}.sensitive{border-color:#fda29b;background:#fff7f6}.nested{margin:1rem 0;padding:1rem;border-left:3px solid #b2ccff;background:#f8faff}.empty{color:#667085;font-style:italic}
@media(max-width:40rem){body{padding:.75rem}.details{grid-template-columns:1fr;gap:.1rem}.details dd{margin-bottom:.7rem}}
@media print{.search,script{display:none}body{max-width:none;background:#fff}.archive-header,.record,.panel{break-inside:avoid;border-color:#aaa;box-shadow:none}}
""".strip()


# @testable true
# @tests tests_tooling/test_008_data_lifecycle.py::test_html_sanitizer_removes_active_and_remote_content
# @matrix portable-archive : html-sanitization no-network
def sanitize_stored_html(value: str, *, page_path: str, identities: set[tuple[str, str, str]], assets=None) -> str:
    """Keep inert document markup and rewrite known portable links locally."""
    from installer.package_install import install_if_missing

    install_if_missing(
        "bs4",
        "HTML parser for portable archive documents",
        package_name="beautifulsoup4",
    )
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
# @matrix portable-archive : navigation offline-html owner-content
class OfflineHTMLBuilder:
    """Render presentation pages using only already-portable records and assets."""

    def __init__(self, root, *, backup_id, created_at, consistency, warnings=()):
        self.root = Path(root)
        self.backup_id = backup_id
        self.created_at = created_at
        self.consistency = consistency
        self.warnings = list(warnings)

    def build(self, records, assets=()):
        all_records = list(records)
        self._all_records = {
            self._identity(record): record for record in all_records
        }
        self._records = all_records
        navigable_records = [
            record for record in all_records if self._is_navigable_record(record)
        ]
        self._records_by_identity = {
            self._identity(record): record for record in navigable_records
        }
        self._identity_set = set(self._all_records)
        navigable_identities = set(self._records_by_identity)
        self._assets = {asset["logical_id"]: asset for asset in assets}
        sections = defaultdict(list)
        search = []
        pages = []
        for record in self._records:
            identity = record["identity"]
            semantic_type = identity["type"]
            title = self._title(record)
            relative = PurePosixPath(
                "site", portable_name(semantic_type), portable_name(identity["id"]), "index.html"
            )
            self._write(
                relative,
                self._record_page(record, title, relative.as_posix()),
            )
            pages.append(relative.as_posix())
            if self._identity(record) not in navigable_identities:
                continue
            sections[semantic_type].append((title, relative.as_posix(), record))
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
            "<header class='archive-header'><p class='eyebrow'>Private portable archive</p>"
            "<h1>Lagniappe archive</h1>"
            f"<p class='summary'>Created {self._render_datetime(self.created_at)} from backup "
            f"<code>{html_stdlib.escape(self.backup_id)}</code>. The database and exact "
            "referenced file versions are bound to the selected backup snapshot.</p></header>",
            "<div class='search'><label>Search <input id='search' type='search'></label><ul id='search-results'></ul></div>",
        ]
        if self.warnings:
            asset_failure = any(
                warning.get("code") == "asset-unavailable"
                for warning in self.warnings
            )
            explanation = (
                "One or more optional files could not be included."
                if asset_failure
                else "No archived file failed to download."
            )
            content.append(
                f"<p class='warning'>{len(self.warnings)} conversion notice "
                f"categor{'y was' if len(self.warnings) == 1 else 'ies were'} recorded. "
                f"{explanation} <a href='../README.md'>Review the details</a>.</p>"
            )
        cards = []
        for semantic_type, label in INDEX_SECTIONS:
            values = sections.get(semantic_type, [])
            if not values:
                continue
            items = "".join(
                f"<li><a href='{html_stdlib.escape(posixpath.relpath(path, 'site'))}'>{html_stdlib.escape(title)}</a></li>"
                for title, path, _record in values
            )
            cards.append(
                f"<section class='panel'><h2>{html_stdlib.escape(label)} ({len(values)})</h2>"
                f"<ul class='record-list'>{items}</ul></section>"
            )
        content.append(f"<main class='grid'>{''.join(cards)}</main>")
        script = "<script src='search-index.js'></script>"
        return self._document("Lagniappe archive", "".join(content) + script)

    def _record_page(self, record, title, page_path):
        identity = record["identity"]
        sensitive = identity["type"] == "message_conversation"
        badges = []
        properties = record["properties"]
        if properties.get("active") is False:
            badges.append("inactive")
        if properties.get("public") is False or properties.get("visibility") == "private":
            badges.append("private")
        if identity["type"] == "task":
            badges.append("completed" if properties.get("completed") else "open")
        if sensitive:
            badges.append("sensitive private content")
        badge_html = "".join(f"<span>{html_stdlib.escape(badge)}</span>" for badge in badges)
        semantic_type = identity["type"]
        renderers = {
            "category": self._category_content,
            "project": self._project_content,
            "model": self._model_content,
            "page": self._page_content,
            "task": self._task_content,
            "file": self._file_content,
        }
        content = renderers.get(semantic_type, self._generic_content)(record, page_path)
        children = self._render_children(record, page_path)
        modified = properties.get("modified")
        metadata = (
            f"<footer class='meta'>Last updated {self._render_value(modified, page_path)}</footer>"
            if modified
            else ""
        )
        body = (
            f"{self._breadcrumbs(record, page_path)}"
            f"<article class='record {'sensitive' if sensitive else ''}'>"
            f"<p class='eyebrow'>{html_stdlib.escape(self._type_label(semantic_type))}</p>"
            f"<h1>{html_stdlib.escape(title)}</h1>"
            f"<div class='badges'>{badge_html}</div>{content}{children}{metadata}</article>"
        )
        return self._document(title, body)

    def _category_content(self, record, page_path):
        return self._description(record) + self._record_list(
            "Pages",
            self._related("page", "model", record),
            page_path,
            empty="No pages were archived in this category.",
        )

    def _project_content(self, record, page_path):
        content = [self._description(record)]
        models = self._related("model", "project", record)
        model_items = []
        for model in models:
            tracked = self._related("task", "model", model)
            model_items.append(
                "<div class='nested'>"
                f"<h3>{self._record_link(model, page_path)}</h3>"
                f"{self._record_list('Tracked tasks', tracked, page_path, empty='No tracked tasks were archived.') }"
                "</div>"
            )
        content.append(
            "<section class='panel'><h2>Model tasks</h2>"
            f"{''.join(model_items) if model_items else '<p class=\'empty\'>No model tasks were archived.</p>'}"
            "</section>"
        )
        direct_tasks = [
            task
            for task in self._related("task", "project", record)
            if not self._reference_identity(task["properties"].get("model"))
        ]
        if direct_tasks:
            content.append(self._record_list("Other project tasks", direct_tasks, page_path))
        return "".join(content)

    def _model_content(self, record, page_path):
        return self._description(record) + self._record_list(
            "Tracked tasks",
            self._related("task", "model", record),
            page_path,
            empty="No tracked tasks were archived.",
        )

    def _page_content(self, record, page_path):
        properties = record["properties"]
        content = [self._description(record)]
        asset_values = properties.get("assets") or {}
        image = asset_values.get("image") or asset_values.get("photo")
        if image:
            content.append(
                "<section class='panel media'><h2>Image</h2>"
                f"{self._render_value(image, page_path)}</section>"
            )
        document = asset_values.get("document")
        if document:
            content.append(self._render_value(document, page_path))
        content.append(
            self._record_list(
                "Tasks",
                self._related("task", "page", record),
                page_path,
            )
        )
        content.append(
            self._record_list(
                "Files",
                self._related("file", "pages", record),
                page_path,
            )
        )
        return "".join(content)

    def _task_content(self, record, page_path):
        properties = record["properties"]
        rows = [("Status", "Completed" if properties.get("completed") else "Open")]
        for label, name in (
            ("Due", "due_date"),
            ("Completed", "completed_on"),
            ("Completed by", "completed_by"),
            ("Assigned to", "assigned_to"),
        ):
            if properties.get(name):
                rows.append((label, self._render_value(properties[name], page_path)))
        schedule = self._schedule_label(properties.get("schedule"))
        if schedule:
            rows.append(("Repeats", html_stdlib.escape(schedule)))
        return (
            self._description(record)
            + self._details(rows)
            + self._record_list(
                "Files",
                self._related("file", "pages", record),
                page_path,
            )
        )

    def _file_content(self, record, page_path):
        content = [self._description(record)]
        file_asset = (record["properties"].get("assets") or {}).get("file")
        if file_asset:
            content.append(
                "<section class='panel'><h2>Download</h2>"
                f"{self._render_value(file_asset, page_path)}</section>"
            )
        content.append(
            self._record_list(
                "Attached to",
                self._records_for_references(record["properties"].get("pages")),
                page_path,
            )
        )
        return "".join(content)

    def _generic_content(self, record, page_path):
        properties = record["properties"]
        fields = {
            "user": (("Email", "email"), ("Owner", "owner"), ("Timezone", "timezone"), ("Last login", "last_login")),
            "form": (("Description", "description"),),
            "group": (("Description", "description"), ("Members", "members")),
            "public_group": (("Description", "description"), ("Members", "members")),
            "note": (("Body", "body"), ("Page", "page")),
            "report": (("Description", "description"), ("Body", "body"), ("Page", "page")),
            "message_conversation": (("Description", "description"),),
        }.get(record["identity"]["type"], (("Description", "description"),))
        rows = [
            (label, self._render_value(properties[name], page_path))
            for label, name in fields
            if not self._empty(properties.get(name))
        ]
        return self._details(rows) if rows else ""

    def _render_children(self, record, page_path):
        sections = []
        labels = {
            "task_history": "Task history",
            "document_history": "Pinned document versions",
            "message": "Messages",
        }
        for child_type, children in sorted((record.get("children") or {}).items()):
            items = []
            for child in children:
                properties = child["properties"]
                fallback_title = {
                    "message": "Message",
                    "document_history": "Pinned document version",
                }.get(child_type, "Completed task")
                title = properties.get("name") or fallback_title
                body = properties.get("body") or properties.get("description")
                details = []
                for label, name in (
                    ("Completed", "completed_on"),
                    ("Completed by", "completed_by"),
                    ("Created", "created"),
                ):
                    if properties.get(name):
                        details.append(
                            (label, self._render_value(properties[name], page_path))
                        )
                document = ""
                if child_type == "document_history":
                    document_asset = (properties.get("assets") or {}).get("document")
                    if document_asset:
                        document = self._render_value(document_asset, page_path)
                items.append(
                    f"<article class='nested {'sensitive' if child_type == 'message' else ''}'>"
                    f"<h3>{html_stdlib.escape(str(title))}</h3>"
                    f"{f'<p>{html_stdlib.escape(str(body))}</p>' if body else ''}"
                    f"{self._details(details)}{document}</article>"
                )
            sections.append(
                f"<section class='panel'><h2>{html_stdlib.escape(labels.get(child_type, child_type.replace('_', ' ').title()))} ({len(children)})</h2>"
                f"{''.join(items)}</section>"
            )
        return "".join(sections)

    def _render_value(self, value, page_path):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (int, float)):
            return html_stdlib.escape(str(value))
        if isinstance(value, str):
            return html_stdlib.escape(value)
        if isinstance(value, list):
            return "<ul>" + "".join(f"<li>{self._render_value(item, page_path)}</li>" for item in value) + "</ul>"
        if not isinstance(value, dict):
            return html_stdlib.escape(str(value))
        if "$datetime" in value:
            return self._render_datetime(value["$datetime"])
        if "$ref" in value:
            identity = self._reference_identity(value)
            record = self._records_by_identity.get(identity)
            if record is None:
                hidden = self._all_records.get(identity)
                if hidden is not None:
                    return html_stdlib.escape(self._title(hidden))
                return "<span class='missing'>Unavailable reference</span>"
            return self._record_link(record, page_path)
        if "$missing_ref" in value:
            missing = value["$missing_ref"]
            return f"<span class='missing'>Unavailable link ({html_stdlib.escape(missing['warning_id'])})</span>"
        if "$asset" in value:
            tag = value["$asset"]
            asset = self._assets.get(tag["logical_id"])
            if not asset or asset.get("status") != "available":
                warning = (asset or {}).get("warning_id", "asset-unavailable")
                return f"<span class='missing'>Unavailable asset ({html_stdlib.escape(warning)})</span>"
            if asset.get("type") == "html" and asset.get("canonical_document"):
                canonical = self.root / PurePosixPath(asset["canonical_document"])
                local_assets = {}
                entity = asset.get("entity") or {}
                for candidate in self._assets.values():
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
                    identities=self._identity_set,
                    assets=local_assets,
                )
                return f"<section class='document' aria-label='Archived document'>{sanitized}</section>"
            href = posixpath.relpath(asset["path"], posixpath.dirname(page_path))
            label = html_stdlib.escape(tag.get("name") or "asset")
            preview = ""
            if str(asset.get("media_type") or "").startswith("image/"):
                preview = f"<br><img src='{html_stdlib.escape(href)}' alt='{label}' loading='lazy'>"
            else:
                label = f"Download {label}"
            return f"<a href='{html_stdlib.escape(href)}'>{label}</a>{preview}"
        return "<dl>" + "".join(
            f"<dt>{html_stdlib.escape(str(key))}</dt><dd>{self._render_value(nested, page_path)}</dd>"
            for key, nested in sorted(value.items())
        ) + "</dl>"

    def _record_list(self, title, records, page_path, *, empty=None):
        records = sorted(records, key=lambda item: self._title(item).casefold())
        if not records and not empty:
            return ""
        items = []
        for record in records:
            summary = self._record_summary(record)
            items.append(
                f"<li>{self._record_link(record, page_path)}"
                f"{f'<small>{html_stdlib.escape(summary)}</small>' if summary else ''}</li>"
            )
        body = (
            f"<ul class='record-list'>{''.join(items)}</ul>"
            if items
            else f"<p class='empty'>{html_stdlib.escape(empty)}</p>"
        )
        return f"<section class='panel'><h2>{html_stdlib.escape(title)}</h2>{body}</section>"

    def _details(self, rows):
        rows = [(label, value) for label, value in rows if value]
        if not rows:
            return ""
        return "<dl class='details'>" + "".join(
            f"<dt>{html_stdlib.escape(label)}</dt><dd>{value}</dd>"
            for label, value in rows
        ) + "</dl>"

    def _breadcrumbs(self, record, page_path):
        values = [
            f"<a href='{html_stdlib.escape(posixpath.relpath('site/index.html', posixpath.dirname(page_path)))}'>Archive home</a>"
        ]
        parent = self._parent_record(record)
        if parent is not None:
            values.extend(("<span>/</span>", self._record_link(parent, page_path)))
        return f"<nav class='breadcrumbs'>{''.join(values)}</nav>"

    def _parent_record(self, record):
        properties = record["properties"]
        semantic_type = record["identity"]["type"]
        candidate = None
        if semantic_type == "page":
            candidate = properties.get("model")
        elif semantic_type == "task":
            candidate = properties.get("page") or properties.get("model") or properties.get("project")
        elif semantic_type == "model":
            candidate = properties.get("project")
        elif semantic_type == "file":
            values = properties.get("pages") or []
            candidate = values[0] if values else None
        identity = self._reference_identity(candidate)
        return self._records_by_identity.get(identity)

    def _related(self, semantic_type, property_name, target):
        identity = self._identity(target)
        return [
            record
            for record in self._records
            if record["identity"]["type"] == semantic_type
            and self._contains_reference(record["properties"].get(property_name), identity)
        ]

    def _records_for_references(self, value, semantic_type=None):
        values = value if isinstance(value, list) else [value]
        records = []
        for item in values:
            identity = self._reference_identity(item)
            record = self._records_by_identity.get(identity)
            if record is not None and (
                semantic_type is None or record["identity"]["type"] == semantic_type
            ):
                records.append(record)
        return records

    @classmethod
    def _contains_reference(cls, value, identity):
        if cls._reference_identity(value) == identity:
            return True
        if isinstance(value, list):
            return any(cls._contains_reference(item, identity) for item in value)
        return False

    @staticmethod
    def _reference_identity(value):
        if not isinstance(value, dict) or "$ref" not in value:
            return None
        reference = value["$ref"]
        return (
            reference.get("namespace") or "",
            reference.get("type"),
            reference.get("id"),
        )

    @staticmethod
    def _identity(record):
        identity = record["identity"]
        return identity.get("namespace") or "", identity["type"], identity["id"]

    def _is_navigable_record(self, record):
        identity = record["identity"]
        properties = record["properties"]
        if identity.get("reserved_role") or properties.get("reserved") is True:
            return False
        if identity["type"] == "page":
            parent = self._all_records.get(self._reference_identity(properties.get("model")))
            if parent is not None and (
                parent["identity"].get("reserved_role")
                or parent["properties"].get("reserved") is True
            ):
                return False
        return identity["type"] in {
            *(value[0] for value in INDEX_SECTIONS),
            *LINKED_TYPES,
        }

    def _record_link(self, record, page_path):
        identity = record["identity"]
        target = f"site/{portable_name(identity['type'])}/{portable_name(identity['id'])}/index.html"
        href = posixpath.relpath(target, posixpath.dirname(page_path))
        return f"<a href='{html_stdlib.escape(href)}'>{html_stdlib.escape(self._title(record))}</a>"

    def _record_summary(self, record):
        properties = record["properties"]
        semantic_type = record["identity"]["type"]
        if semantic_type == "task":
            status = "Completed" if properties.get("completed") else "Open"
            if properties.get("due_date"):
                return f"{status} · due {self._datetime_text(properties['due_date'].get('$datetime'))}"
            return status
        if semantic_type == "file":
            return str(properties.get("filename") or "")
        return str(properties.get("description") or "").strip()

    @staticmethod
    def _schedule_label(value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return "Configured schedule"
        if not isinstance(value, dict):
            return None
        recurring = value.get("recurring")
        if isinstance(recurring, dict):
            interval = max(1, int(recurring.get("interval") or 1))
            unit = str(recurring.get("unit") or "interval")
            unit = unit if interval == 1 else f"{unit}s"
            suffix = " after completion" if recurring.get("complete") else ""
            return f"Every {unit}{suffix}" if interval == 1 else f"Every {interval} {unit}{suffix}"
        return "Configured schedule"

    def _description(self, record):
        value = str(record["properties"].get("description") or "").strip()
        return f"<p class='summary'>{html_stdlib.escape(value)}</p>" if value else ""

    @classmethod
    def _render_datetime(cls, value):
        text = cls._datetime_text(value)
        return f"<time datetime='{html_stdlib.escape(str(value))}'>{html_stdlib.escape(text)}</time>"

    @staticmethod
    def _datetime_text(value):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return str(value)
        clock = parsed.strftime("%I:%M %p").lstrip("0")
        return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year} at {clock} UTC"

    @staticmethod
    def _empty(value):
        return value is None or value == "" or value == [] or value == {}

    @staticmethod
    def _type_label(semantic_type):
        return {
            "model": "Model task",
            "message_conversation": "Private conversation",
            "public_group": "Public group",
        }.get(semantic_type, semantic_type.replace("_", " ").title())

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
