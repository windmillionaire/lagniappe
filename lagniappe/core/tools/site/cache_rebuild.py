"""Focused cache recovery without unrelated administration dependencies."""

from dataclasses import dataclass
from itertools import chain, islice

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import migrations as database_migrations


@dataclass(frozen=True)
class CacheRebuildResult:
    """Outcome of a migration-gated cache rebuild."""

    rebuilt: bool
    migration_status: dict


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_cache_rebuild_is_blocked_until_migrations_are_current
# @tests tests_unit/test_026_site_admin.py::test_cache_rebuild_rehydrates_entities_in_bounded_chunks
# @tests tests_unit/test_026_site_admin.py::test_cache_rebuild_materializes_nested_relations_across_batch_boundaries
# @matrix cache : batching current migration-gate nested-relations pending
def rebuild_application_cache(*, chunk_size=100):
    """Rebuild cached entities only when migration state allows it."""
    migration_status = database_migrations.get_migration_status()
    if not migration_status["cache_refresh_allowed"]:
        return CacheRebuildResult(False, migration_status)

    cache.delete_cache()
    all_raw = chain(
        database_get.all_models(),
        database_get.all_instances(),
        database_get.all_files(),
        database_get.all_users(),
    )
    while chunk := list(islice(all_raw, chunk_size)):
        loaded = Entities.fetch(
            *chunk,
            request=Fetch.nested(
                because=FetchReason.CACHE_REBUILD_MATERIALIZATION
            ),
        )
        cache.update(*loaded, update=False)

    return CacheRebuildResult(True, migration_status)
