"""Focused cache recovery without unrelated administration dependencies."""

from dataclasses import dataclass
from itertools import chain, islice

from config.datastore import encode_urlsafe_key
from google.api_core.exceptions import GoogleAPICallError
from redis.exceptions import RedisError

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import PropertyError, UnloadedRelationError, capture
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import migrations as database_migrations


@dataclass(frozen=True)
class CacheRebuildResult:
    """Outcome of a migration-gated cache rebuild."""

    rebuilt: bool
    migration_status: database_migrations.MigrationStatus
    cache_status: dict | None = None


def rebuild_application_cache(*, chunk_size: int = 100) -> CacheRebuildResult:
    """Rebuild cached entities only when migration state allows it."""
    migration_status = database_migrations.get_migration_status()
    if not migration_status["cache_refresh_allowed"]:
        return CacheRebuildResult(False, migration_status)

    if chunk_size < 1:
        raise ValueError("Cache rebuild chunk size must be positive.")
    cache.delete_cache()
    status = {"status": "complete", "processed": 0, "failed": 0, "errors": []}
    all_raw = chain(
        database_get.all_models(),
        database_get.all_instances(),
        database_get.all_files(),
        database_get.all_users(),
    )
    while chunk := list(islice(all_raw, chunk_size)):
        _rebuild_chunk(chunk, status)

    if status["failed"]:
        status["status"] = "partial"
    return CacheRebuildResult(True, migration_status, status)


def _rebuild_chunk(chunk, status):
    try:
        for record in chunk:
            if isinstance(record, dict) and not record.get("type"):
                raise ValueError("Entity type is missing.")
        loaded = Entities.fetch(
            *chunk,
            request=Fetch.nested(
                because=FetchReason.CACHE_REBUILD_MATERIALIZATION
            ),
        )
        cache.update(*loaded, update=False)
    except (UnloadedRelationError, PropertyError, ValueError, TypeError, KeyError, AttributeError) as error:
        cause = error
        while cause is not None:
            if isinstance(cause, (GoogleAPICallError, RedisError, ConnectionError, TimeoutError)):
                raise
            cause = cause.__cause__
        # Retrying projections is safe: rebuild writes replace cache entries.
        # Split only bad data batches; provider failures must still stop the run.
        if len(chunk) > 1:
            middle = len(chunk) // 2
            _rebuild_chunk(chunk[:middle], status)
            _rebuild_chunk(chunk[middle:], status)
            return
        detail = _record_error(chunk[0], error)
        status["failed"] += 1
        if len(status["errors"]) < 100:
            status["errors"].append(detail)
        capture(error, context={"operation": "cache_rebuild_record", **detail})
    else:
        status["processed"] += len(loaded)


def _record_error(entity, error):
    raw = getattr(entity, "db", entity)
    raw = raw if isinstance(raw, dict) else {}
    key = getattr(entity, "key", None)
    try:
        identifier = encode_urlsafe_key(key) if key is not None else "unknown"
    except (AttributeError, TypeError, ValueError):
        identifier = str(key)
    kind = raw.get("type") or raw.get("kind")
    routes = {"page": "pages", "task": "tasks", "form": "forms", "file": "files",
              "category": "categories", "project": "projects", "user": "users"}
    detail = {"key": identifier, "message": str(error) or type(error).__name__}
    if isinstance(kind, str) and kind in routes and key is not None:
        detail["url"] = f"/{routes[kind]}/{identifier}"
        detail["link_label"] = raw.get("name") or f"Open {kind}"
    return detail
