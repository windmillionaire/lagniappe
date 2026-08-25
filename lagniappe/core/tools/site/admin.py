"""Runtime-safe orchestration for application administration."""

from dataclasses import dataclass
from itertools import chain, islice

from config.ai_models import discover_model_options
from config.ai_settings import normalize_ai_settings
from config.constants import DEFAULT_DEPLOYMENT_SETTINGS
from config.deployment import normalize_deployment_settings
from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache, database
from lagniappe.core.tools.ai.settings import runtime_ai_settings
from lagniappe.core.tools.database import migrations as database_migrations
from lagniappe.core.tools.database import site as site_database


@dataclass(frozen=True)
class CacheRebuildResult:
    """Outcome of a migration-gated cache rebuild."""

    rebuilt: bool
    migration_status: dict


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_deployment_settings_merge_live_values_over_runtime_defaults
# @matrix admin : config deployment-settings metadata
def load_deployment_settings(*, config=None):
    """Load normalized deployment settings with live values taking precedence."""
    config = config or CONFIG
    defaults = {
        key: getattr(config, key, value)
        for key, value in DEFAULT_DEPLOYMENT_SETTINGS.items()
    }
    entity = site_database.deployment()
    if entity:
        defaults.update(
            {
                key: value
                for key, value in dict(entity).items()
                if key in DEFAULT_DEPLOYMENT_SETTINGS
            }
        )
    return normalize_deployment_settings(defaults)


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_ai_settings_payload_normalizes_runtime_settings_against_discovery
# @matrix admin : ai-settings config metadata
def load_ai_settings_payload(settings=None, *, config=None):
    """Load normalized runtime AI settings and current model options."""
    config = config or CONFIG
    settings = settings or runtime_ai_settings(config=config)
    model_options = discover_model_options(
        project=config.GOOGLE_CLOUD_PROJECT,
        location=settings["AI_LOCATION"],
        credentials=config.google_credentials,
        current_settings=settings,
    )
    return (
        normalize_ai_settings(
            settings,
            current_settings=settings,
            model_options=model_options,
        ),
        model_options,
    )


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_site_updates_return_the_migration_report
# @matrix admin : audit site-update
def run_site_updates():
    """Run data migrations and return their complete status report."""
    return database_migrations.run_data_migrations()


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
        database.get.all_models(),
        database.get.all_instances(),
        database.get.all_files(),
        database.get.all_users(),
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
