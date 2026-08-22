"""Build static HTML site export archives in Cloud Storage."""

import datetime
import json
import posixpath
import re
from collections import defaultdict
from html import escape as html_escape
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.definitions.identifiers import short_hash, short_uuid
from lagniappe.core.entities import Entities
from lagniappe.core.properties.form_special import HTML
from lagniappe.core.properties.form_table import Table
from lagniappe.core.properties.form_todo import TodoList
from lagniappe.core.tools import database
from lagniappe.core.tools.database import site_exports as export_database


CHUNK_SIZE = 50
USERS_CATEGORY_ID = "users"
ARCHIVE_PROFILE = "html"
EXPORT_CONTENT_TYPE = "text/html; charset=utf-8"


# @testable true
# @tests tests_unit/test_019_site_export.py::test_site_export_prefix_uses_dated_directory
# @features admin export
# @dimensions path-generation dated-prefix
def site_export_prefix(export_id, now=None):
    """Return the dated storage prefix for an exploded HTML export."""
    now = _utc(now)
    return f"html/{now:%Y-%m-%d}/{now:%Y%m%dT%H%M%SZ}-{export_id}/"


# @testable true
# @tests tests_unit/test_019_site_export.py::test_export_storage_uri_and_command_include_prefixed_bucket
# @features admin export
# @dimensions storage-uri download-command
def export_storage_uri(prefix, path=""):
    """Return the Cloud Storage URI for an export prefix or object."""
    bucket = f"{CONFIG.PREFIX}{CONFIG.EXPORT_BUCKET}"
    return f"gs://{bucket}/{prefix}{path}"


# @testable true
# @tests tests_unit/test_019_site_export.py::test_export_storage_uri_and_command_include_prefixed_bucket
# @features admin export
# @dimensions storage-uri download-command
def export_download_command(prefix):
    """Return a local recursive copy command for the export prefix."""
    name = prefix.rstrip("/").split("/")[-1]
    return f"gcloud storage cp --recursive {export_storage_uri(prefix)} ./{name}"


# @testable true
# @tests tests_unit/test_019_site_export.py::test_slugify_stabilizes_archive_paths
# @features admin export
# @dimensions slug path-generation
def slugify(value, fallback="item", used=None):
    """Create a URL/path-safe slug, optionally de-duplicating within ``used``."""
    value = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    slug = slug or fallback

    if used is None:
        return slug

    base = slug
    count = 2
    while slug in used:
        slug = f"{base}-{count}"
        count += 1
    used.add(slug)
    return slug


# @testable true
# @tests tests_unit/test_019_site_export.py::test_relative_href_between_archive_pages
# @features admin export
# @dimensions html-links relative-paths
def relative_href(from_path, to_path):
    """Return a relative href from one archive object path to another."""
    start = posixpath.dirname(from_path) or "."
    href = posixpath.relpath(to_path, start)
    return "." if href == "." else href


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder.build
# @reason route-facing convenience delegates to builder workflow
def create_export_record(now=None):
    """Create queued metadata for a new HTML site export."""
    export_id = short_uuid()
    prefix = site_export_prefix(export_id, now=now)
    return export_database.create(
        {
            "id": export_id,
            "profile": ARCHIVE_PROFILE,
            "status": "queued",
            "prefix": prefix,
            "storage_uri": export_storage_uri(prefix),
            "entrypoint": f"{prefix}index.html",
            "manifest_path": f"{prefix}manifest.json",
            "readme_path": f"{prefix}README.txt",
            "command": export_download_command(prefix),
        }
    )


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder.build
# @reason public API delegates to builder internals
def build_site_export(export_id):
    """Build a queued site export and return completion metadata."""
    record = export_database.fetch(export_id)
    if not record:
        raise ValueError(f"Site export not found: {export_id}")

    builder = SiteExportBuilder(export_id, record["prefix"])
    return builder.build()


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder.build
# @reason the class is a workflow container; distinct behaviors are owned by focused methods
class SiteExportBuilder:
    """Collect site content and write an exploded static HTML archive."""

    def __init__(self, export_id, prefix):
        self.export_id = export_id
        self.prefix = prefix if prefix.endswith("/") else f"{prefix}/"

        self.generated = _utc()
        self.object_count = 0
        self.byte_count = 0
        self.objects = []
        self.warnings = []

        self.categories = []
        self.projects = []
        self.pages = []
        self.model_tasks = []
        self.forms = {}
        self.files = {}

        self.category_pages = defaultdict(list)
        self.user_pages = []
        self.model_tasks_by_project = defaultdict(list)
        self.tasks_by_page = defaultdict(list)
        self.history_by_task = defaultdict(list)
        self.orphan_history_by_page = defaultdict(list)

        self.category_paths = {}
        self.project_paths = {}
        self.page_paths = {}
        self.form_paths = {}
        self.file_paths = {}
        self.task_page_paths = {}
        self.task_anchors = {}

        self._path_keys = {
            "category": {},
            "page": {},
            "project": {},
            "form": {},
            "file": {},
            "task": {},
        }
        self._copied_sources = {}
        self._asset_destinations = set()
        self._used_slugs = defaultdict(set)
        self._users_category = None

    # @testable true
    # @tests tests_e2e/001_site/test_001f_site_export.py::test_owner_can_start_html_export
    # @features export
    # @dimensions archive-build storage-objects users-category
    def build(self):
        """Collect content and write the archive, with manifest last."""
        self._collect()

        self._write_text("assets/archive.css", archive_css(), "text/css; charset=utf-8")
        self._write_forms()
        self._write_categories()
        self._write_pages()
        self._write_projects()
        self._write_readme()
        self._write_index()
        self._write_manifest()

        return {
            "status": "complete",
            "completed": _utc(),
            "object_count": self.object_count,
            "byte_count": self.byte_count,
            "warnings": self.warnings,
            "storage_uri": export_storage_uri(self.prefix),
            "entrypoint": f"{self.prefix}index.html",
            "manifest_path": f"{self.prefix}manifest.json",
            "readme_path": f"{self.prefix}README.txt",
            "command": export_download_command(self.prefix),
        }

    def _collect(self):
        self._collect_categories()
        self._collect_projects()
        self._collect_model_tasks()
        self._collect_pages()
        self._collect_tasks()
        self._collect_history()
        self._collect_files()
        self._assign_paths()

    def _collect_categories(self):
        self.categories = list(_load_iter(export_database.categories(), related=True))
        try:
            self._users_category = Entities.USERS.get()
        except Exception as error:
            self._users_category = None
            self.warnings.append(f"Users category was not available: {error}")

    def _collect_projects(self):
        self.projects = list(_load_iter(export_database.projects(), related=True))

    def _collect_model_tasks(self):
        tasks = [
            model
            for model in _load_iter(
                export_database.model_tasks(),
                related=True,
            )
            if isinstance(model, Entities.MODEL_TASK)
        ]
        self.model_tasks = tasks
        for model_task in tasks:
            if model_task.project:
                self.model_tasks_by_project[model_task.project.key].append(model_task)
            self._register_form(model_task.form)

    def _collect_pages(self):
        pages = [
            page
            for page in _load_iter(export_database.pages(), related=True)
            if isinstance(page, Entities.PAGE)
        ]
        self.pages = pages

        for page in pages:
            self._register_form(page.form)

            if self._is_user_page(page):
                self.user_pages.append(page)
                continue

            keys = []
            for category in page.categories:
                if isinstance(category, Entities.USERS):
                    continue
                if isinstance(category, Entities.CATEGORY):
                    keys.append(category.key)

            for key in dict.fromkeys(keys):
                self.category_pages[key].append(page)

    def _collect_tasks(self):
        tasks = [
            task
            for task in _load_iter(
                export_database.tasks(),
                related=True,
            )
            if isinstance(task, Entities.TASK)
        ]
        for task in tasks:
            self._register_form(task.form)
            for page_key in self._page_keys_for_task(task):
                self.tasks_by_page[page_key].append(task)

    def _collect_history(self):
        histories = [
            history
            for history in _load_iter(
                export_database.task_history(),
                related=True,
            )
            if isinstance(history, Entities.TASK_HISTORY)
        ]

        current_task_keys = {
            task.key for tasks in self.tasks_by_page.values() for task in tasks
        }
        for history in histories:
            self._register_form(history.form)
            task_key = history.db.get("task") or getattr(history.key, "parent", None)
            if task_key:
                self.history_by_task[task_key].append(history)

            page_key = history.db.get("page")
            if page_key and task_key not in current_task_keys:
                self.orphan_history_by_page[page_key].append(history)

        for entries in self.history_by_task.values():
            entries.sort(key=lambda item: item.completed or item.created, reverse=True)
        for entries in self.orphan_history_by_page.values():
            entries.sort(key=lambda item: item.completed or item.created, reverse=True)

    def _collect_files(self):
        files = [
            file
            for file in _load_iter(export_database.files(), related=False)
            if isinstance(file, Entities.FILE) and file.db.get("type") != "ingress"
        ]
        self.files = {file.key: file for file in files}

    def _assign_paths(self):
        for category in self.categories:
            slug = self._entity_slug(category, "category")
            path = f"categories/{slug}/index.html"
            self.category_paths[category.key] = path
            self._path_keys["category"][category.urlsafe_key] = path

        users_path = f"categories/{USERS_CATEGORY_ID}/index.html"
        self.category_paths[USERS_CATEGORY_ID] = users_path

        for project in self.projects:
            slug = self._entity_slug(project, "project")
            path = f"projects/{slug}/index.html"
            self.project_paths[project.key] = path
            self._path_keys["project"][project.urlsafe_key] = path

        for page in self.pages:
            slug = self._entity_slug(page, "page")
            path = f"pages/{slug}/index.html"
            self.page_paths[page.key] = path
            self._path_keys["page"][page.urlsafe_key] = path

        for form in self.forms.values():
            form_hash = form.hash or short_hash(form.urlsafe_key)
            path = f"forms/{form_hash}.json"
            self.form_paths[form.key] = path
            self._path_keys["form"][form.urlsafe_key] = path

        for page_key, tasks in self.tasks_by_page.items():
            page_path = self.page_paths.get(page_key)
            if not page_path:
                continue
            for task in tasks:
                anchor = self._task_anchor(task)
                self.task_page_paths[task.key] = page_path
                self.task_anchors[task.key] = anchor
                self._path_keys["task"][task.urlsafe_key] = f"{page_path}#{anchor}"

    def _write_forms(self):
        for form in sorted(self.forms.values(), key=lambda item: item.name or ""):
            path = self.form_paths.get(form.key)
            if not path:
                continue
            data = {
                "id": form.urlsafe_key,
                "hash": form.hash,
                "name": form.name,
                "version": form.version,
                "schema": form.schema,
            }
            self._write_text(path, json.dumps(data, indent=2, default=_json_default), "application/json; charset=utf-8")

    def _write_categories(self):
        for category in self.categories:
            path = self.category_paths[category.key]
            pages = self.category_pages.get(category.key, [])
            body = [
                self._header(category.name, "Category", "index.html"),
                self._entity_description(category),
                self._link_list(
                    pages,
                    path,
                    self.page_paths,
                    empty="No pages in this category.",
                ),
            ]
            self._write_html(path, category.name, "".join(body))

        body = [
            self._header("Users", "Category", "index.html"),
            self._link_list(
                self.user_pages,
                self.category_paths[USERS_CATEGORY_ID],
                self.page_paths,
                empty="No user pages.",
            ),
        ]
        self._write_html(self.category_paths[USERS_CATEGORY_ID], "Users", "".join(body))

    def _write_pages(self):
        for page in self.pages:
            path = self.page_paths[page.key]
            files = self._files_for_page(page)
            body = [
                self._header(page.name, "Page", "index.html"),
                self._page_metadata(page, path),
                self._document_section(page, path),
                self._submission_section("Page Form Values", page, path),
                self._files_section(files, path),
                self._tasks_section(page, path),
            ]
            self._write_html(path, page.name, "".join(body))

    def _write_projects(self):
        for project in self.projects:
            path = self.project_paths[project.key]
            body = [
                self._header(project.name, "Project", "index.html"),
                self._entity_description(project),
                self._document_section(project, path),
                self._model_tasks_section(project, path),
            ]
            self._write_html(path, project.name, "".join(body))

    def _write_index(self):
        category_items = [(category.name, self.category_paths[category.key]) for category in self.categories]
        category_items.append(("Users", self.category_paths[USERS_CATEGORY_ID]))
        project_items = [(project.name, self.project_paths[project.key]) for project in self.projects]

        body = [
            "<header class=\"hero\"><p>Lagniappe HTML Archive</p>",
            f"<h1>{html_escape(getattr(CONFIG, 'APP_NAME', 'Site'))}</h1>",
            f"<div class=\"meta\">Generated {_format_datetime(self.generated)}</div>",
            "</header>",
            self._manual_link_list("Projects", project_items, "No projects exported.", "index.html"),
            self._manual_link_list("Categories", category_items, "No categories exported.", "index.html"),
        ]
        self._write_html("index.html", "Lagniappe HTML Archive", "".join(body), home=False)

    def _write_readme(self):
        text = "\n".join(
            [
                "Lagniappe HTML Export",
                "",
                f"Export ID: {self.export_id}",
                f"Generated: {_format_datetime(self.generated)}",
                "Entry point: index.html",
                f"Storage URI: {export_storage_uri(self.prefix)}",
                "",
                "Download the exploded archive from Cloud Storage:",
                export_download_command(self.prefix),
                "",
                "After downloading, open index.html in a browser.",
                "To zip it locally, run zip -r lagniappe-export.zip . from inside the downloaded directory.",
                "",
            ]
        )
        self._write_text("README.txt", text, "text/plain; charset=utf-8")

    def _write_manifest(self):
        manifest = {
            "id": self.export_id,
            "profile": ARCHIVE_PROFILE,
            "generated": self.generated.isoformat(),
            "prefix": self.prefix,
            "storage_uri": export_storage_uri(self.prefix),
            "entrypoint": "index.html",
            "readme": "README.txt",
            "object_count": self.object_count + 1,
            "byte_count_before_manifest": self.byte_count,
            "counts": {
                "categories": len(self.categories) + 1,
                "projects": len(self.projects),
                "pages": len(self.pages),
                "forms": len(self.forms),
                "files": len(self.file_paths),
            },
            "warnings": self.warnings,
            "objects": self.objects,
        }
        self._write_text(
            "manifest.json",
            json.dumps(manifest, indent=2, default=_json_default),
            "application/json; charset=utf-8",
        )

    def _write_html(self, path, title, body, home=True):
        stylesheet = relative_href(path, "assets/archive.css")
        home_link = (
            f"<a class=\"home-link\" href=\"{html_escape(relative_href(path, 'index.html'))}\">Home</a>"
            if home
            else ""
        )
        html = "\n".join(
            [
                "<!doctype html>",
                "<html lang=\"en\">",
                "<head>",
                "<meta charset=\"utf-8\">",
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
                f"<title>{html_escape(title)}</title>",
                f"<link rel=\"stylesheet\" href=\"{html_escape(stylesheet)}\">",
                "</head>",
                "<body>",
                home_link,
                "<main>",
                body,
                "</main>",
                "</body>",
                "</html>",
            ]
        )
        self._write_text(path, html, EXPORT_CONTENT_TYPE)

    def _write_text(self, path, text, content_type):
        text = text or ""
        database.assets.save_text(text, f"{self.prefix}{path}", content_type, "export")
        size = len(text.encode("utf-8"))
        self.object_count += 1
        self.byte_count += size
        self.objects.append(
            {"path": path, "content_type": content_type, "bytes": size}
        )

    def _copy_asset(self, source_path, source_visibility, destination_path):
        if not source_path or not destination_path:
            return None

        key = (source_visibility, source_path, destination_path)
        if key in self._copied_sources:
            return self._copied_sources[key]

        copied = database.copy_file(
            source_path,
            source_visibility,
            f"{self.prefix}{destination_path}",
            "export",
        )
        if not copied:
            self.warnings.append(f"Missing storage object: {source_visibility}/{source_path}")
            return None

        size = int(getattr(copied, "size", 0) or 0)
        self.object_count += 1
        self.byte_count += size
        self.objects.append(
            {
                "path": destination_path,
                "content_type": getattr(copied, "content_type", None),
                "bytes": size,
            }
        )
        self._copied_sources[key] = destination_path
        return destination_path

    def _register_form(self, form):
        if form and getattr(form, "key", None):
            self.forms[form.key] = form

    def _register_file(self, file):
        if not file or not getattr(file, "key", None):
            return None
        if file.key in self.file_paths:
            return self.file_paths[file.key]

        asset = file.get_asset("file")
        if not asset:
            self.warnings.append(f"File has no stored asset: {file.name or file.filename or file.urlsafe_key}")
            return None

        filename = _safe_filename(file.filename or file.name or f"{file.hash}.{asset.extension or 'bin'}")
        destination = f"files/{file.hash or short_hash(file.urlsafe_key)}/{filename}"
        copied = self._copy_asset(asset.path, asset.visibility.value, destination)
        if not copied:
            return None

        self.file_paths[file.key] = destination
        self._path_keys["file"][file.urlsafe_key] = destination
        return destination

    def _copy_named_asset(self, entity, name, destination_prefix):
        if not entity or not name:
            return None

        asset = entity.get_asset(name)
        if not asset:
            return None

        extension = asset.extension or asset.path.rsplit(".", 1)[-1]
        safe_name = _safe_filename(f"{name.split('.')[0]}.{extension}")
        destination = _unique_asset_path(
            f"{destination_prefix}/{safe_name}",
            self._asset_destinations,
        )
        return self._copy_asset(asset.path, asset.visibility.value, destination)

    def _entity_slug(self, entity, kind):
        fallback_hash = getattr(entity, "hash", None) or short_hash(entity.urlsafe_key)
        fallback = f"{kind}-{fallback_hash}"
        return slugify(entity.name, fallback=fallback, used=self._used_slugs[kind])

    def _is_user_page(self, page):
        if isinstance(page.model, Entities.USERS):
            return True
        users_key = getattr(self._users_category, "key", None)
        return bool(users_key and page.db.get("model") == users_key)

    def _page_keys_for_task(self, task):
        keys = set()
        if task.db.get("page"):
            keys.add(task.db["page"])
        if task.db.get("assigned_to"):
            keys.add(task.db["assigned_to"])
        keys.update(task.db.get("linked_pages", []) or [])
        return keys

    def _files_for_page(self, page):
        files = []
        for file in self.files.values():
            if page.key in (file.db.get("pages") or []):
                files.append(file)
        return sorted(files, key=lambda item: item.name or item.filename or "")

    def _files_for_task_entry(self, entry):
        files = list(getattr(entry, "files", []) or [])
        known = {file.key for file in files}
        for file in self.files.values():
            if entry.key in (file.db.get("tasks") or []) and file.key not in known:
                files.append(file)
        return sorted(files, key=lambda item: item.name or item.filename or "")

    def _header(self, title, kind, current_path):
        return (
            "<header class=\"page-header\">"
            f"<p>{html_escape(kind)}</p>"
            f"<h1>{html_escape(title or kind)}</h1>"
            f"<a href=\"{html_escape(relative_href(current_path, 'index.html'))}\">Archive Home</a>"
            "</header>"
        )

    def _entity_description(self, entity):
        description = getattr(entity, "description", None)
        if not description:
            return ""
        return f"<section><p class=\"description\">{html_escape(description)}</p></section>"

    def _page_metadata(self, page, current_path):
        categories = [
            self._archive_link(category.name, current_path, self.category_paths.get(category.key))
            for category in page.categories
            if not isinstance(category, Entities.USERS)
            and self.category_paths.get(category.key)
        ]
        if self._is_user_page(page):
            categories.append(
                self._archive_link("Users", current_path, self.category_paths[USERS_CATEGORY_ID])
            )
        if not categories:
            return self._entity_description(page)
        return (
            "<section class=\"metadata\">"
            f"{self._entity_description(page)}"
            f"<p><strong>Categories</strong> {' '.join(categories)}</p>"
            "</section>"
        )

    def _document_section(self, entity, current_path):
        document = getattr(entity.properties, "document", None)
        try:
            html = document.html if document else None
        except Exception as error:
            self.warnings.append(
                f"Unable to read document for {entity.entity_kind} {entity.name}: {error}"
            )
            html = None
        if not html:
            return "<section><h2>Document</h2><p class=\"empty\">No document.</p></section>"

        from ..mentions.content import sanitize_mentions

        cleaned = self._sanitize_document_html(
            sanitize_mentions(html), entity, current_path
        )
        return f"<section><h2>Document</h2><article class=\"document\">{cleaned}</article></section>"

    def _submission_section(self, title, entity, current_path):
        if not getattr(entity, "form", None):
            return ""

        form_link = self._form_schema_link(entity.form, current_path, "schema JSON")
        table = self._submission_table(entity, current_path)
        if not table:
            return (
                f"<section><h2>{html_escape(title)}</h2>"
                f"<p class=\"meta\">{form_link}</p><p class=\"empty\">No submitted values.</p></section>"
            )
        return f"<section><h2>{html_escape(title)}</h2><p class=\"meta\">{form_link}</p>{table}</section>"

    def _files_section(self, files, current_path):
        links = []
        for file in files:
            destination = self._register_file(file)
            if not destination:
                continue
            label = file.name or file.filename or "File"
            details = file.filename or file.mimetype
            links.append(
                "<li>"
                f"{self._archive_link(label, current_path, destination)}"
                f"{f'<span>{html_escape(details)}</span>' if details else ''}"
                "</li>"
            )
        if not links:
            return "<section><h2>Files</h2><p class=\"empty\">No files.</p></section>"
        return f"<section><h2>Files</h2><ul class=\"file-list\">{''.join(links)}</ul></section>"

    def _tasks_section(self, page, current_path):
        tasks = list(dict.fromkeys(self.tasks_by_page.get(page.key, [])))
        chunks = []
        for task in sorted(tasks, key=lambda item: item.name or ""):
            chunks.append(self._task_history_table(task, current_path))

        for history in self.orphan_history_by_page.get(page.key, []):
            chunks.append(self._orphan_history_table(history, current_path))

        if not chunks:
            return "<section><h2>Tasks</h2><p class=\"empty\">No tasks.</p></section>"
        return f"<section><h2>Tasks</h2>{''.join(chunks)}</section>"

    def _model_tasks_section(self, project, current_path):
        tasks = sorted(
            self.model_tasks_by_project.get(project.key, []),
            key=lambda item: (item.order or 0, item.name or ""),
        )
        if not tasks:
            return "<section><h2>Model Tasks</h2><p class=\"empty\">No model tasks.</p></section>"

        rows = []
        for task in tasks:
            form = task.form
            form_link = ""
            if form:
                form_link = self._archive_link(form.name, current_path, self.form_paths.get(form.key))
            rows.append(
                "<tr>"
                f"<td>{html_escape(task.name or 'Model Task')}</td>"
                f"<td>{html_escape(str(task.order or ''))}</td>"
                f"<td>{form_link}</td>"
                "</tr>"
            )
        return (
            "<section><h2>Model Tasks</h2>"
            "<table><thead><tr><th>Name</th><th>Order</th><th>Form Schema</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></section>"
        )

    # @testable true
    # @tests tests_unit/test_019_site_export.py::test_task_current_as_history_renders_current_first_with_blank_completed_date
    # @tests tests_unit/test_019_site_export.py::test_task_history_table_renders_current_form_values_from_backend_submission
    # @features export
    # @dimensions task-history
    def _task_history_table(self, task, current_path):
        anchor = self.task_anchors.get(task.key, self._task_anchor(task))
        rows = [
            self._task_row(task, current_path, current=True),
            self._task_detail_row(task, current_path, current=True),
        ]
        for history in self.history_by_task.get(task.key, []):
            rows.append(self._task_row(history, current_path, current=False))
            rows.append(self._task_detail_row(history, current_path, current=False))

        return (
            f"<details id=\"{html_escape(anchor)}\" class=\"task\" open>"
            f"<summary>{html_escape(task.name or 'Task')}</summary>"
            "<table><thead><tr>"
            "<th>Entry</th><th>Completed</th><th>Completed By</th><th>Due</th><th>Description</th><th>Form</th><th>Files</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
            "</details>"
        )

    def _orphan_history_table(self, history, current_path):
        title = history.task.name if history.task else "Task History"
        rows = [
            self._task_row(history, current_path, current=False),
            self._task_detail_row(history, current_path, current=False),
        ]
        return (
            "<details class=\"task\">"
            f"<summary>{html_escape(title)}</summary>"
            "<table><thead><tr>"
            "<th>Entry</th><th>Completed</th><th>Completed By</th><th>Due</th><th>Description</th><th>Form</th><th>Files</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
            "</details>"
        )

    def _task_row(self, entry, current_path, current=False):
        completed = "" if current else _format_datetime(getattr(entry, "completed", None))
        due = _format_date(getattr(entry, "due_date", None)) if current else ""
        completed_by = getattr(entry, "completed_by", None)
        completed_by_name = completed_by.name if completed_by else ""
        form = getattr(entry, "form", None)
        form_link = self._form_schema_link(form, current_path, form.name if form else None)
        files = self._inline_file_links(self._files_for_task_entry(entry), current_path)
        description = getattr(entry, "description", None) or ""
        return (
            "<tr>"
            f"<td>{'Current' if current else 'History'}</td>"
            f"<td>{html_escape(completed)}</td>"
            f"<td>{html_escape(completed_by_name)}</td>"
            f"<td>{html_escape(due)}</td>"
            f"<td>{html_escape(description)}</td>"
            f"<td>{form_link}</td>"
            f"<td>{files}</td>"
            "</tr>"
        )

    def _task_detail_row(self, entry, current_path, current=False):
        form = getattr(entry, "form", None)
        values = self._submission_table(entry, current_path)
        if not form and not values:
            return ""

        schema_link = self._form_schema_link(form, current_path, "schema JSON")
        title = "Current Form Values" if current else "Completed Form Values"
        body = values or "<p class=\"empty\">No submitted values.</p>"
        return (
            "<tr class=\"task-values-row\">"
            "<td colspan=\"7\">"
            "<div class=\"task-values\">"
            "<div class=\"task-values-header\">"
            f"<strong>{html_escape(title)}</strong>"
            f"{f'<span>{schema_link}</span>' if schema_link else ''}"
            "</div>"
            f"{body}"
            "</div>"
            "</td>"
            "</tr>"
        )

    # @testable true
    # @tests tests_unit/test_019_site_export.py::test_submission_table_renders_backend_field_values_and_table_rows
    # @features export
    # @dimensions form-values
    def _submission_table(self, entity, current_path, compact=False):
        fields = self._submission_fields(entity)
        if not fields:
            return ""

        rows = []
        for field in fields:
            value = self._format_field_value(field, current_path)
            if not value:
                continue
            rows.append(
                "<tr>"
                f"<th>{html_escape(field.label or field.id)}</th>"
                f"<td>{value}</td>"
                "</tr>"
            )

        if not rows:
            return ""

        table = f"<table class=\"submission\"><tbody>{''.join(rows)}</tbody></table>"
        if compact:
            return f"<details><summary>Values</summary>{table}</details>"
        return table

    def _submission_fields(self, entity):
        submission = getattr(getattr(entity, "properties", None), "submission", None)
        if not submission or not getattr(entity, "form", None):
            return []

        fields = []
        for field in submission.fields.values():
            if isinstance(field, HTML):
                continue
            if not self._submission_field_visible(submission, field):
                continue
            if self._field_empty(field):
                continue
            fields.append(field)
        return fields

    def _submission_field_visible(self, submission, field):
        try:
            return submission.is_visible(field.id)
        except Exception:
            return True

    def _field_empty(self, field):
        if isinstance(field, Table):
            return not field.rows
        if isinstance(field, TodoList):
            return not field.items

        value = getattr(field, "form_value", None)
        if value not in (None, "", [], {}):
            return False

        try:
            value = field.column_value
        except Exception:
            value = None
        return value in (None, "", [], {})

    def _format_field_value(self, field, current_path):
        if isinstance(field, Table):
            return self._format_table_field(field, current_path)
        if isinstance(field, TodoList):
            return self._format_todo_field(field)

        value = self._display_value(field)
        return self._format_backend_value(value, field, current_path)

    def _display_value(self, field):
        if getattr(field, "icon", None) == "tel":
            return field.form_value
        try:
            column_value = field.column_value
        except Exception:
            column_value = None

        if isinstance(column_value, dict):
            if column_value.get("url") or column_value.get("title"):
                return column_value
            if getattr(field, "_is_categorical", False):
                return list(column_value.keys())
        elif column_value not in (None, "", [], {}):
            return column_value

        return getattr(field, "form_value", None)

    def _format_backend_value(self, value, field, current_path):
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, list):
            return "<br>".join(
                self._format_backend_value(item, field, current_path) for item in value
            )
        if isinstance(value, dict):
            link = self._submission_link(value, current_path)
            if link:
                return link
            return f"<pre>{html_escape(json.dumps(value, indent=2, default=_json_default))}</pre>"
        if isinstance(value, (datetime.datetime, datetime.date)):
            return html_escape(_format_datetime(value) if isinstance(value, datetime.datetime) else _format_date(value))
        return html_escape(str(value))

    def _format_table_field(self, field, current_path):
        columns = list(field.fields.values())
        if not field.rows or not columns:
            return ""

        header = "".join(
            f"<th>{html_escape(column.label or column.id)}</th>"
            for column in columns
        )
        body_rows = []
        for row in field.rows:
            cells = []
            for column in columns:
                row_field = row.fields.get(column.id)
                value = self._format_field_value(row_field, current_path) if row_field else ""
                cells.append(f"<td>{value}</td>")
            body_rows.append(f"<tr>{''.join(cells)}</tr>")
        return f"<table class=\"nested\"><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"

    # @testable true
    # @tests tests_unit/test_019_site_export.py::test_submission_table_renders_todo_items_semantically
    # @pairs export:semantic-list export:checked-state export:escaping
    # @pair form-todo:semantic-list
    def _format_todo_field(self, field):
        items = []
        for item in field.items:
            marker = "☑" if item["checked"] else "☐"
            items.append(
                f'<li><span aria-hidden="true">{marker}</span> '
                f'{html_escape(item["text"])}</li>'
            )
        return f'<ul class="todo-list">{"".join(items)}</ul>'

    def _submission_link(self, value, current_path):
        url = value.get("url")
        label = value.get("title") or value.get("name") or url
        if not label:
            return ""
        if value.get("id") and value.get("kind"):
            route = self._path_for_details(value)
            if route:
                return self._archive_link(label, current_path, route)
        if url:
            rewritten = self._rewrite_link(url, current_path)
            return f"<a href=\"{html_escape(rewritten)}\">{html_escape(label)}</a>"
        return html_escape(label)

    def _inline_file_links(self, files, current_path):
        links = []
        for file in files:
            destination = self._register_file(file)
            if destination:
                label = file.name or file.filename or "File"
                links.append(self._archive_link(label, current_path, destination))
        return "<br>".join(links)

    def _form_schema_link(self, form, current_path, label=None):
        if not form:
            return ""
        path = self.form_paths.get(form.key)
        if not path:
            return ""
        return self._archive_link(label or form.name or "schema JSON", current_path, path)

    def _link_list(self, entities, current_path, path_map, empty):
        items = []
        for entity in sorted(entities, key=lambda item: item.name or ""):
            target = path_map.get(entity.key)
            if target:
                items.append(f"<li>{self._archive_link(entity.name, current_path, target)}</li>")
        if not items:
            return f"<section><p class=\"empty\">{html_escape(empty)}</p></section>"
        return f"<section><ul class=\"entity-list\">{''.join(items)}</ul></section>"

    def _manual_link_list(self, title, items, empty, current_path):
        links = [
            f"<li>{self._archive_link(label, current_path, path)}</li>"
            for label, path in sorted(items, key=lambda item: item[0] or "")
        ]
        body = "".join(links) if links else f"<li class=\"empty\">{html_escape(empty)}</li>"
        return f"<section><h2>{html_escape(title)}</h2><ul class=\"entity-list\">{body}</ul></section>"

    def _archive_link(self, label, current_path, target_path):
        if not target_path:
            return ""
        href = relative_href(current_path, target_path.split("#", 1)[0])
        if "#" in target_path:
            href = f"{href}#{target_path.split('#', 1)[1]}"
        return f"<a href=\"{html_escape(href)}\">{html_escape(label or target_path)}</a>"

    # @testable true
    # @tests tests_unit/test_019_site_export.py::test_link_and_asset_rewriting_sanitizes_document_and_copies_assets
    # @features export
    # @dimensions html-links storage-objects
    def _sanitize_document_html(self, html, entity, current_path):
        soup = BeautifulSoup(html or "", "html.parser")

        for tag in soup.find_all(["script", "template"]):
            tag.decompose()

        for tag in soup.find_all(True):
            for attr in list(tag.attrs):
                if attr.lower().startswith("on"):
                    del tag.attrs[attr]
            if tag.get("href", "").strip().lower().startswith("javascript:"):
                del tag.attrs["href"]
            if tag.get("src", "").strip().lower().startswith("javascript:"):
                del tag.attrs["src"]

        for link in soup.find_all("a", href=True):
            link["href"] = self._rewrite_link(link["href"], current_path)

        for image in soup.find_all(["img", "source"], src=True):
            rewritten = self._rewrite_asset_url(image["src"], entity, current_path)
            if rewritten:
                image["src"] = rewritten

        return str(soup)

    def _rewrite_link(self, href, current_path):
        if not href:
            return href
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            return href

        parsed = urlparse(href)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            return href

        if parsed.netloc and "storage.googleapis.com" not in parsed.netloc:
            return href

        path = parsed.path or href
        if parsed.netloc and "storage.googleapis.com" in parsed.netloc:
            return href

        target = self._archive_path_for_app_path(path, parsed.query)
        if not target:
            return href

        archive_path, fragment = target
        rewritten = relative_href(current_path, archive_path)
        if fragment:
            rewritten = f"{rewritten}#{fragment}"
        return rewritten

    def _rewrite_asset_url(self, src, entity, current_path):
        if not src or src.startswith("data:"):
            return src

        parsed = urlparse(src)
        if parsed.netloc == "storage.googleapis.com":
            destination = self._copy_public_storage_asset(parsed.path)
            return relative_href(current_path, destination) if destination else src

        if parsed.netloc:
            return src

        path = parsed.path
        if not path.startswith("/assets/"):
            return src

        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) < 3:
            return src

        key, name = parts[1], parts[2]
        source = entity if key == getattr(entity, "urlsafe_key", None) else None
        if not source:
            source = self._entity_for_urlsafe_key(key)

        destination = self._copy_named_asset(
            source,
            name,
            f"assets/{getattr(source, 'hash', None) or short_hash(key)}",
        )
        return relative_href(current_path, destination) if destination else src

    def _copy_public_storage_asset(self, parsed_path):
        bucket = f"/{CONFIG.PREFIX}{CONFIG.PUBLIC_BUCKET}/"
        if not parsed_path.startswith(bucket):
            return None

        source_path = unquote(parsed_path.removeprefix(bucket))
        filename = _safe_filename(source_path.rsplit("/", 1)[-1] or "asset")
        destination = _unique_asset_path(
            f"assets/public/{short_hash(source_path)}-{filename}",
            self._asset_destinations,
        )
        return self._copy_asset(source_path, "public", destination)

    def _archive_path_for_app_path(self, path, query=""):
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) < 2:
            return None

        section, key = parts[0], parts[1]
        fragment = None
        archive_path = None
        if section == "pages":
            archive_path = self._path_keys["page"].get(key)
        elif section == "categories":
            archive_path = self._path_keys["category"].get(key) or self._path_keys["page"].get(key)
        elif section == "projects":
            archive_path = self._path_keys["project"].get(key)
        elif section == "forms":
            archive_path = self._path_keys["form"].get(key)
        elif section == "files":
            archive_path = self._path_keys["file"].get(key)
        elif section == "tasks":
            task_target = self._path_keys["task"].get(key)
            if task_target and "#" in task_target:
                archive_path, fragment = task_target.split("#", 1)
            else:
                archive_path = task_target

        if section == "pages" and query:
            for part in query.split("&"):
                if part.startswith("task="):
                    task_key = part.split("=", 1)[1]
                    task_target = self._path_keys["task"].get(task_key)
                    if task_target and "#" in task_target:
                        fragment = task_target.split("#", 1)[1]

        return (archive_path, fragment) if archive_path else None

    def _path_for_details(self, details):
        kind = details.get("kind")
        key = details.get("id")
        if kind == "user":
            kind = "page"
        elif kind == "model":
            kind = "task"
        return self._path_keys.get(kind, {}).get(key)

    def _entity_for_urlsafe_key(self, key):
        for collection in (self.pages, self.projects, self.categories, self.model_tasks, self.forms.values(), self.files.values()):
            for entity in collection if isinstance(collection, list) else list(collection):
                if getattr(entity, "urlsafe_key", None) == key:
                    return entity
        return None

    def _task_anchor(self, task):
        return f"task-{task.hash or short_hash(task.urlsafe_key)}"


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::site_export_prefix
# @reason datetime normalization is exercised through export prefix generation
def _utc(value=None):
    if value is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder.build
# @reason chunked loading is part of the full archive build workflow
def _load_iter(iterator, related=True, chunk_size=CHUNK_SIZE):
    request = Fetch.direct() if related else Fetch.root()
    chunk = []
    for item in iterator:
        chunk.append(item)
        if len(chunk) >= chunk_size:
            yield from Entities.fetch(*chunk, request=request)
            chunk = []
    if chunk:
        yield from Entities.fetch(*chunk, request=request)


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder
# @reason archive asset/file naming is covered through file and asset export paths
def _safe_filename(value):
    value = str(value or "file").strip()
    value = value.replace("/", "-").replace("\\", "-")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "file"


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder
# @reason duplicate asset naming is part of archive asset export behavior
def _unique_asset_path(path, used):
    if path not in used:
        used.add(path)
        return path

    base, dot, extension = path.rpartition(".")
    stem = base if dot else path
    suffix = f".{extension}" if dot else ""
    count = 2
    candidate = f"{stem}-{count}{suffix}"
    while candidate in used:
        count += 1
        candidate = f"{stem}-{count}{suffix}"
    used.add(candidate)
    return candidate


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder
# @reason date formatting is covered through generated archive pages and manifest data
def _format_datetime(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return _utc(value).strftime("%Y-%m-%d %H:%M UTC")


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder
# @reason date formatting is covered through generated archive pages
def _format_date(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder
# @reason JSON fallback formatting is covered by form and manifest export behavior
def _json_default(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if hasattr(value, "to_legacy_urlsafe"):
        return value.to_legacy_urlsafe().decode()
    return str(value)


# @testable false
# @covered-by lagniappe/core/tools/site/exports.py::SiteExportBuilder.build
# @reason archive stylesheet is emitted as part of the build workflow
def archive_css():
    """Return the static CSS bundled with each archive."""
    return """
:root {
  color-scheme: light;
  --text: #1f2933;
  --muted: #667085;
  --line: #d8dee7;
  --surface: #ffffff;
  --shade: #f4f6f8;
  --accent: #176b87;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--shade);
  color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
main { max-width: 980px; margin: 0 auto; padding: 2rem 1rem 4rem; }
a { color: var(--accent); font-weight: 650; text-decoration-thickness: 0.08em; }
.home-link {
  position: sticky;
  top: 0;
  display: block;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid var(--line);
}
.hero, .page-header {
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 2px solid var(--line);
}
.hero p, .page-header p, .meta, .empty { color: var(--muted); }
h1 { margin: 0.1rem 0 0.35rem; font-size: clamp(2rem, 6vw, 3.75rem); line-height: 1; }
h2 { margin-top: 2rem; border-bottom: 1px solid var(--line); padding-bottom: 0.35rem; }
section {
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.document {
  overflow-wrap: anywhere;
}
.document img {
  max-width: 100%;
  height: auto;
}
.description {
  margin: 0;
  color: var(--muted);
}
.entity-list, .file-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.entity-list li, .file-list li {
  display: flex;
  gap: 0.75rem;
  align-items: baseline;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
  padding: 0.65rem 0;
}
.entity-list li:last-child, .file-list li:last-child { border-bottom: 0; }
.file-list span { color: var(--muted); font-size: 0.9rem; }
details.task {
  margin: 1rem 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  overflow-x: auto;
}
details.task > summary {
  cursor: pointer;
  padding: 0.75rem 1rem;
  font-weight: 750;
}
.task-values-row > td {
  background: #fbfcfd;
}
.task-values {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.task-values-header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  justify-content: space-between;
  color: var(--muted);
}
table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
}
th, td {
  border-top: 1px solid var(--line);
  padding: 0.55rem 0.65rem;
  text-align: left;
  vertical-align: top;
}
thead th { background: var(--shade); font-size: 0.88rem; }
table.submission th { width: 13rem; }
table.nested { font-size: 0.92rem; }
.todo-list { margin: 0; padding-left: 1.25rem; }
.todo-list li { margin: 0.2rem 0; }
pre {
  max-width: 100%;
  overflow-x: auto;
  white-space: pre-wrap;
  margin: 0;
  font-size: 0.9rem;
}
@media (max-width: 640px) {
  main { padding: 1rem 0.75rem 3rem; }
  section { padding: 0.75rem; }
  .entity-list li, .file-list li { flex-direction: column; gap: 0.2rem; }
}
""".strip()
