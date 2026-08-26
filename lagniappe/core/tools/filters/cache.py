"""Cache-backed filter index for querying entities via JSONPath expressions."""

from flask import url_for
from lagniappe import CONFIG

from ...definitions import Action, Fetch, FetchReason, Restriction
from ...entities import Entities
from lagniappe.core.tools.database import get as database_get
from ...tools.database.core import KINDS
from ...tools.database.filter import Filter, Query
from ...tools.auth.context import current_context_user
from ..cache import Keys, filter_cache
from ..services.task_queue import create_task
from .build import FilterExpression
from .contract import CompiledFilter


FILTER_CACHE_SCOPE = "all-v2"


# @testable false
# @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
# @reason filter-index value escaping is part of cache materialization
def escape_for_filter(to_filter):
    """Preserve semantic cache values; query literals provide the escaping."""
    return to_filter


# @testable true
# @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_uses_shared_cache_key_without_user_restrictions
# @matrix cache filters permissions : restrictions shared-key
class FilterCache:
    """Manages a cached filter index for an entity."""

    def __init__(self, entity, user=None):
        self.entity = entity
        self.user = current_context_user(user)
        self.cache_key = Keys.FILTER.value.format(self.entity.hash, FILTER_CACHE_SCOPE)

        self._to_cache = {}

    # @testable true
    # @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_query_filters_loaded_entities_by_view_permission
    # @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_rejects_uncompiled_query_definitions
    # @matrix cache filters : allowed query query-boundary related-load validation
    # @matrix permissions : allowed query related-load
    def _query_keys(self, filter):
        if not isinstance(filter, CompiledFilter):
            raise TypeError("FilterCache queries require a CompiledFilter")
        expression = FilterExpression(filter.definitions).build()
        return filter_cache.query(self.cache_key, expression)

    # @testable true
    # @tests tests_unit/test_021_refresh.py::test_filter_cache_query_roots_uses_root_fetch_without_permission_expansion
    # @matrix filters reconnect-refresh : membership root-depth
    def query_roots(self, filter):
        """Return matching roots for modified-time comparison without expansion."""
        return Entities.fetch(*self._query_keys(filter), request=Fetch.root())

    # @testable true
    # @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_query_filters_loaded_entities_by_view_permission
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_project_filter_results_respect_task_permissions
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_multiple_conditions
    # @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filter_results_respect_page_permissions
    # @matrix filters : compound entity-condition run-results string-condition view-access
    # @pair filters:query
    def query(self, filter):
        """Query the cache with a filter and return matching entities."""
        return [
            entity
            for entity in Entities.fetch(
                *self._query_keys(filter), request=Fetch.direct()
            )
            if entity.allowed(Action.VIEW, user=self.user)
        ]

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
    # @covered-by lagniappe/web/routes/process/main.py::update_cache
    # @reason refresh scheduling is owned by route/process workflows
    def update(self, queue=True):
        """Refresh the cache immediately or via a background task."""
        now = CONFIG.local or not queue

        if now:
            self.cache()
        else:
            task_endpoint = url_for("process.update_cache", _external=True)
            payload = {
                "cache_key": self.cache_key,
                "entity_key": self.entity.urlsafe_key,
                "user_key": self.user.urlsafe_key,
            }
            create_task(task_endpoint, payload)

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
    # @reason index-map shaping is part of cache materialization
    def _entity_map(self, entities):
        return {e.hash: escape_for_filter(e.to_filter_index()) for e in entities}

    # @testable true
    # @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_loads_category_pages_without_restrictions
    # @matrix filters : cache category-pagination restrictions source-query
    def _load(self, cursor=None):
        if self.entity.kind == "project":
            self._load_project_tasks()
            return

        if self.entity.kind != "category":
            return

        while True:
            index = database_get.pages(
                self.entity.key,
                start_cursor=cursor,
                limit=100,
                hashes=Restriction.UNRESTRICTED,
            )
            self._to_cache.update(
                self._entity_map(Entities.fetch(*index.results, request=Fetch.direct()))
            )
            if not index.next_cursor:
                return
            cursor = index.next_cursor

    # @testable false
    # @covered-by lagniappe/core/tools/filters/cache.py::FilterCache.cache
    # @reason project task cache loading needs real database/filter-cache behavior
    def _load_project_tasks(self):
        """Load every task for a project filter cache.

        The project UI task index shows incomplete tasks. A filter cache needs
        the full task set so completion status can be queried alongside
        ordinary fields.
        """
        tasks = Entities.fetch(
            *Query(KINDS.instances)
            .filter(
                Filter()
                .eq("type", "task")
                .eq("project", database_get.datastore_key(self.entity))
            )
            .order("-modified")
            .fetch_all(),
            request=Fetch.nested(because=FetchReason.TASK_FILTER_INDEX_MATERIALIZATION),
        )

        self._to_cache.update(self._entity_map(tasks))

    # @testable true
    # @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_uses_shared_cache_key_without_user_restrictions
    # @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_loads_category_pages_without_restrictions
    # @tests tests_unit/test_011b_filter_cache.py::test_filter_cache_loads_all_project_tasks_without_active_or_restriction_filters
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_category
    # @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_model_task
    # @matrix filters : entity-condition model-task run-results string-condition
    # @matrix filters : all-tasks restrictions shared-key
    def cache(self):
        """Build or incrementally refresh the filter cache."""
        # filter_cache.delete(self.cache_key)
        if self.entity.kind == "project" and CONFIG.local:
            self._load()
            filter_cache.create(self.cache_key, self._to_cache)
            return

        if not filter_cache.exists(self.cache_key):
            self._load()
            filter_cache.create(self.cache_key, self._to_cache)
        else:
            to_refresh = filter_cache.refresh_needed(self.cache_key)
            if not to_refresh:
                return

            request = (
                Fetch.nested(because=FetchReason.TASK_FILTER_INDEX_MATERIALIZATION)
                if self.entity.kind == "project"
                else Fetch.direct()
            )
            refreshed = Entities.fetch(*to_refresh, request=request)
            filter_cache.set(self.cache_key, self._entity_map(refreshed))
