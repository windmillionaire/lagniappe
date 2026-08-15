import datetime
import json
from types import SimpleNamespace

import pytest

from lagniappe import CONFIG
from lagniappe.core.tools import site_export
from lagniappe.core.tools.database import assets
from lagniappe.core.tools.database.core import KINDS
from testing.utility.test_entities import TestEntities


# @features admin export
# @dimensions path-generation dated-prefix
@pytest.mark.unit
def test_site_export_prefix_uses_dated_directory():
    now = datetime.datetime(2026, 6, 25, 14, 3, 2, tzinfo=datetime.timezone.utc)

    assert (
        site_export.site_export_prefix("abc123", now=now)
        == "html/2026-06-25/20260625T140302Z-abc123/"
    )


# @features admin export
# @dimensions storage-uri download-command
@pytest.mark.unit
def test_export_storage_uri_and_command_include_prefixed_bucket(monkeypatch):
    monkeypatch.setattr(CONFIG, "PREFIX", "test-", raising=False)
    monkeypatch.setattr(CONFIG, "EXPORT_BUCKET", "export-bucket", raising=False)

    uri = site_export.export_storage_uri("html/day/export/")
    command = site_export.export_download_command("html/day/export/")

    assert uri == "gs://test-export-bucket/html/day/export/"
    assert command == (
        "gcloud storage cp --recursive "
        "gs://test-export-bucket/html/day/export/ ./export"
    )


# @features admin export
# @dimensions slug path-generation
@pytest.mark.unit
def test_slugify_stabilizes_archive_paths():
    used = set()

    assert site_export.slugify("A Fine Page!", used=used) == "a-fine-page"
    assert site_export.slugify("A Fine Page!", used=used) == "a-fine-page-2"
    assert site_export.slugify("", fallback="page-123", used=used) == "page-123"


# @features admin export
# @dimensions html-links relative-paths
@pytest.mark.unit
def test_relative_href_between_archive_pages():
    assert (
        site_export.relative_href(
            "categories/case-files/index.html", "pages/missing-person/index.html"
        )
        == "../../pages/missing-person/index.html"
    )


class _Entity(dict):
    def __init__(self, key=None, exclude_from_indexes=None):
        super().__init__()
        self.key = key
        self.exclude_from_indexes = exclude_from_indexes


class _Datastore:
    def __init__(self):
        self.store = {}

    def key(self, *parts):
        return parts

    def get(self, key):
        return self.store.get(key)

    def get_multi(self, keys):
        return [self.store.get(key) for key in keys if key in self.store]

    def entity(self, key, exclude_from_indexes=None):
        return _Entity(key=key, exclude_from_indexes=exclude_from_indexes)

    def put(self, entity):
        self.store[entity.key] = entity

    def put_multi(self, entities):
        for entity in entities:
            self.put(entity)


# @features admin export
# @dimensions metadata create recent-index
@pytest.mark.unit
def test_create_site_export_records_metadata_and_recent_index(monkeypatch):
    datastore = _Datastore()
    monkeypatch.setattr(assets, "DATA", SimpleNamespace(datastore=datastore))

    record = assets.create_site_export({"id": "export-1", "prefix": "html/x/"})

    assert record["type"] == "site_export"
    assert record["profile"] == "html"
    assert record["status"] == "queued"
    assert record["prefix"] == "html/x/"
    index = datastore.store[(KINDS.site.value, assets.SITE_EXPORT_INDEX_ID)]
    assert index["ids"] == ["export-1"]


# @features admin export
# @dimensions metadata update
@pytest.mark.unit
def test_update_site_export_sets_modified_timestamp_and_keeps_counts(monkeypatch):
    datastore = _Datastore()
    monkeypatch.setattr(assets, "DATA", SimpleNamespace(datastore=datastore))
    assets.create_site_export({"id": "export-1", "object_count": 2})

    updated = assets.update_site_export("export-1", {"status": "complete"})

    assert updated["status"] == "complete"
    assert updated["object_count"] == 2
    assert updated["modified"] >= updated["created"]


# @features admin export
# @dimensions metadata list
@pytest.mark.unit
def test_site_exports_returns_recent_records_in_index_order(monkeypatch):
    datastore = _Datastore()
    monkeypatch.setattr(assets, "DATA", SimpleNamespace(datastore=datastore))
    assets.create_site_export({"id": "older"})
    assets.create_site_export({"id": "newer"})

    assert [record["id"] for record in assets.site_exports()] == ["newer", "older"]


# @features export
# @dimensions form-values
@pytest.mark.unit
def test_submission_table_renders_backend_field_values_and_table_rows():
    entity = TestEntities.get(
        "PAGE",
        {
            "name": "Archive Page",
            "form": {"name": "Archive Form"},
        },
    )
    entity.form.schema = [
        {"id": "summary", "title": "Summary", "type": "input", "input": "text"},
        {
            "id": "decision",
            "title": "Decision",
            "type": "select",
            "options": [{"label": "Proceed", "value": "go"}],
        },
        {
            "id": "contacts",
            "title": "Contacts",
            "type": "table",
            "columns": [
                {"id": "name", "title": "Name", "type": "input", "input": "text"},
                {"id": "email", "title": "Email", "type": "input", "input": "email"},
            ],
        },
    ]
    entity.db["submission"] = json.dumps(
        {
            "summary": "Ready",
            "decision": "go",
            "contacts": {"rows": [{"name": "Ada", "email": "ada@example.com"}]},
        }
    )
    builder = site_export.SiteExportBuilder("export", "html/day/export/")

    html = builder._submission_table(entity, "pages/page/index.html")

    assert "<th>Summary</th>" in html
    assert "Ready" in html
    assert "<th>Decision</th>" in html
    assert "Proceed" in html
    assert "<th>[Contacts] Name</th>" in html
    assert "Ada" in html
    assert "<th>[Contacts] Email</th>" in html
    assert "ada@example.com" in html


# @pairs export:semantic-list export:checked-state export:escaping
# @pair form-todo:semantic-list
@pytest.mark.unit
def test_submission_table_renders_todo_items_semantically():
    task = TestEntities.get(
        "TASK",
        {
            "name": "Archive Checklist",
            "hash": "archive_todo_task",
            "page": {"name": "Archive Parent", "hash": "archive_todo_parent"},
            "form": {"name": "Archive Form", "hash": "archive_todo_form"},
        },
    )
    task.form.schema = [
        {"id": "todo-work", "title": "Work", "type": "todo"},
    ]
    task.db["submission"] = json.dumps(
        {
            "todo-work": {
                "items": [
                    {"text": "Done <safely>", "checked": True},
                    {"text": "Still open", "checked": False},
                ]
            }
        }
    )
    builder = site_export.SiteExportBuilder("export", "html/day/export/")

    html = builder._submission_table(task, "tasks/task/index.html")

    assert '<ul class="todo-list">' in html
    assert "☑" in html
    assert "☐" in html
    assert "Done &lt;safely&gt;" in html
    assert "Still open" in html


# @features export
# @dimensions task-history
@pytest.mark.unit
def test_task_current_as_history_renders_current_first_with_blank_completed_date():
    task = SimpleNamespace(
        key=("task", "1"),
        urlsafe_key="task-key",
        hash="taskhash",
        name="Review",
        form=None,
        completed_by=None,
        due_date=None,
        description="Current work",
        files=[],
        db={},
    )
    history = SimpleNamespace(
        key=("history", "1"),
        task=task,
        form=None,
        completed=datetime.datetime(
            2026, 6, 24, 12, 0, tzinfo=datetime.timezone.utc
        ),
        completed_by=SimpleNamespace(name="Owner"),
        description="Finished work",
        files=[],
        db={},
    )
    builder = site_export.SiteExportBuilder("export", "html/day/export/")
    builder.history_by_task[task.key] = [history]
    builder.task_anchors[task.key] = "task-taskhash"

    html = builder._task_history_table(task, "pages/page/index.html")

    current_index = html.index("<td>Current</td><td></td>")
    history_index = html.index("<td>History</td><td>2026-06-24 12:00 UTC</td>")
    assert current_index < history_index


# @features export
# @dimensions task-history form-values
@pytest.mark.unit
def test_task_history_table_renders_current_form_values_from_backend_submission():
    page = TestEntities.get("PAGE", {"name": "Task Page"})
    task = TestEntities.get(
        "TASK",
        {
            "name": "Review",
            "description": "Current work",
            "form": {"name": "Task Form"},
        },
        page=page,
    )
    task.form.schema = [
        {"id": "summary", "title": "Summary", "type": "input", "input": "text"},
    ]
    task.db["submission"] = json.dumps({"summary": "Ready"})
    builder = site_export.SiteExportBuilder("export", "html/day/export/")
    builder.task_anchors[task.key] = "task-taskhash"

    html = builder._task_history_table(task, "pages/page/index.html")

    assert "<strong>Current Form Values</strong>" in html
    assert "<th>Summary</th>" in html
    assert "Ready" in html
    assert "<th>Values</th>" not in html


# @features export
# @dimensions html-links storage-objects
@pytest.mark.unit
def test_link_and_asset_rewriting_sanitizes_document_and_copies_assets(monkeypatch):
    copied = []

    def copy_file(source_path, source_visibility, destination_path, destination_visibility):
        copied.append(
            (source_path, source_visibility, destination_path, destination_visibility)
        )
        return SimpleNamespace(size=10, content_type="image/jpeg")

    monkeypatch.setattr(site_export.database, "copy_file", copy_file)

    asset = SimpleNamespace(
        path="pagehash_image_abc.jpeg",
        visibility=SimpleNamespace(value="private"),
        extension="jpeg",
    )
    entity = SimpleNamespace(
        urlsafe_key="page-key",
        hash="pagehash",
        get_asset=lambda name: asset if name.startswith("image_abc") else None,
    )
    builder = site_export.SiteExportBuilder("export", "html/day/export/")
    builder._path_keys["page"]["target-key"] = "pages/target/index.html"

    html = builder._sanitize_document_html(
        '<script>alert(1)</script><p onclick="bad()">Hi</p>'
        '<a href="/pages/target-key">Target</a>'
        '<img src="/assets/page-key/image_abc.jpeg">',
        entity,
        "pages/source/index.html",
    )

    assert "<script" not in html
    assert "onclick" not in html
    assert 'href="../target/index.html"' in html
    assert 'src="../../assets/pagehash/image_abc.jpeg"' in html
    assert copied == [
        (
            "pagehash_image_abc.jpeg",
            "private",
            "html/day/export/assets/pagehash/image_abc.jpeg",
            "export",
        )
    ]
