"""Datastore metadata and query recipes for static site exports."""

import datetime
from datetime import timezone
import uuid

from .core import DATA, KINDS
from .filter import Filter, Query
from . import get


SITE_EXPORT_INDEX_ID = "exports"
SITE_EXPORT_PREFIX = "export:"
SITE_EXPORT_INDEX_LIMIT = 25
SITE_EXPORT_EXCLUDE_FROM_INDEXES = (
    "command",
    "entrypoint",
    "error",
    "manifest_path",
    "prefix",
    "readme_path",
    "storage_uri",
    "warnings",
)


# @testable false
# @covered-by lagniappe/core/tools/database/site_exports.py::create
# @reason timestamp defaulting is covered through export metadata creation/update
def _now():
    return datetime.datetime.now(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/database/site_exports.py::fetch
# @reason key construction is covered through export metadata fetch/list helpers
def _key(export_id):
    return DATA.datastore.key(KINDS.site.value, f"{SITE_EXPORT_PREFIX}{export_id}")


# @testable false
# @covered-by lagniappe/core/tools/database/site_exports.py::recent
# @reason index key construction is covered through recent export listing
def _index_key():
    return DATA.datastore.key(KINDS.site.value, SITE_EXPORT_INDEX_ID)


# @testable false
# @covered-by lagniappe/core/tools/database/site_exports.py::create
# @reason recent-index creation is covered through export metadata creation
def _index():
    index_key = _index_key()
    entity = DATA.datastore.get(index_key)
    if entity:
        return entity
    entity = DATA.datastore.entity(key=index_key)
    entity.update({"ids": []})
    return entity


# @testable false
# @covered-by lagniappe/core/tools/database/site_exports.py::create
# @reason entity shape is covered through export metadata creation
def _entity(export_id):
    return DATA.datastore.entity(
        key=_key(export_id),
        exclude_from_indexes=SITE_EXPORT_EXCLUDE_FROM_INDEXES,
    )


# @testable true
# @tests tests_unit/test_019_site_export.py::test_create_site_export_records_metadata_and_recent_index
# @features admin export
# @dimensions metadata create recent-index
def create(data):
    """Create export metadata and add it to the recent index."""
    export_id = data.get("id") or uuid.uuid4().hex[:12]
    now = _now()
    entity = _entity(export_id)
    entity.update(
        {
            "id": export_id,
            "type": "site_export",
            "profile": data.get("profile", "html"),
            "status": data.get("status", "queued"),
            "created": data.get("created", now),
            "modified": data.get("modified", now),
            "started": data.get("started"),
            "completed": data.get("completed"),
            "prefix": data.get("prefix"),
            "storage_uri": data.get("storage_uri"),
            "entrypoint": data.get("entrypoint"),
            "manifest_path": data.get("manifest_path"),
            "readme_path": data.get("readme_path"),
            "object_count": int(data.get("object_count", 0) or 0),
            "byte_count": int(data.get("byte_count", 0) or 0),
            "warnings": data.get("warnings", []),
            "error": data.get("error"),
            "command": data.get("command"),
        }
    )

    index = _index()
    ids = [export_id, *[item for item in index.get("ids", []) if item != export_id]]
    index["ids"] = ids[:SITE_EXPORT_INDEX_LIMIT]
    DATA.datastore.put_multi([entity, index])
    return entity


# @testable true
# @tests tests_unit/test_019_site_export.py::test_update_site_export_sets_modified_timestamp_and_keeps_counts
# @features admin export
# @dimensions metadata update
def update(export_id, updates):
    """Update an existing export metadata record."""
    entity = DATA.datastore.get(_key(export_id))
    if not entity:
        return None
    entity.exclude_from_indexes = SITE_EXPORT_EXCLUDE_FROM_INDEXES
    entity.update({**updates, "modified": _now()})
    DATA.datastore.put(entity)
    return entity


# @testable true
# @tests tests_unit/test_019_site_export.py::test_site_exports_returns_recent_records_in_index_order
# @features admin export
# @dimensions metadata list
def fetch(export_id):
    """Fetch one export metadata record."""
    return DATA.datastore.get(_key(export_id))


# @testable true
# @tests tests_unit/test_019_site_export.py::test_site_exports_returns_recent_records_in_index_order
# @features admin export
# @dimensions metadata list
def recent(limit=10):
    """Fetch recent exports in newest-first index order."""
    index = DATA.datastore.get(_index_key())
    ids = list(index.get("ids", [])) if index else []
    ids = ids[:limit]
    if not ids:
        return []
    records = [record for record in DATA.datastore.get_multi([_key(i) for i in ids]) if record]
    by_id = {record.get("id"): record for record in records}
    return [by_id[export_id] for export_id in ids if export_id in by_id]


# @testable false
# @reason export source queries are persistence-owned and covered by export workflows
def categories():
    return get.all_categories()


# @testable false
# @reason export source queries are persistence-owned and covered by export workflows
def projects():
    return get.all_projects()


# @testable false
# @reason export source queries are persistence-owned and covered by export workflows
def model_tasks():
    return (
        Query(KINDS.models)
        .filter(Filter().eq("active", True).eq("type", "model"))
        .fetch_iter()
    )


# @testable false
# @reason export source queries are persistence-owned and covered by export workflows
def pages():
    return get.all_pages()


# @testable false
# @reason export source queries are persistence-owned and covered by export workflows
def tasks():
    return Query(KINDS.instances).filter(Filter().eq("type", "task")).fetch_iter()


# @testable false
# @reason export source queries are persistence-owned and covered by export workflows
def task_history():
    return (
        Query(KINDS.history)
        .filter(Filter().eq("type", "task_history"))
        .fetch_iter()
    )


# @testable false
# @reason export source queries are persistence-owned and covered by export workflows
def files():
    return get.all_files()
