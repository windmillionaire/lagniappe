"""Cache-backed filter index for querying entities via JSONPath expressions."""

from flask import url_for
from lagniappe import CONFIG

from ...definitions import Action, Comparator, Fetch, FetchReason, FieldType, Restriction
from ...entities import Entities
from lagniappe.core.tools.database import get as database_get
from ...tools.database.core import KINDS
from ...tools.database.filter import Filter, Query
from ...tools.auth.context import current_context_user
from typing import TYPE_CHECKING, TypeGuard, cast

if TYPE_CHECKING:
    from redis.commands.json._util import JsonType
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.category import Category
    from lagniappe.core.entities.project import Project
    from lagniappe.core.entities.user import User

from ..cache import Keys, filter_cache
from ..services.task_queue import create_task
from .build import FilterExpression
from .contract import CompiledFilter


FILTER_CACHE_SCOPE = "all-v2"


def _entity_ids(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(key, str) for key in value)


def _needs_literal_match(definition):
    # RedisJSON versions can silently miss regex operands containing escaped
    # characters. Evaluate those literal comparisons over cached candidates.
    return (
        definition.field_type == FieldType.STRING
        and definition.comparator in {Comparator.EQUALS, Comparator.SUBSTRING}
        and any(
            character in '\\.^$*+?{}[]|()"\'' or not 32 <= ord(character) < 127
            for character in definition.value
        )
    )


def _matches_literal(row, definition):
    value = row.get(definition.field)
    if not isinstance(value, str):
        return False
    actual, expected = value.casefold(), definition.value.casefold()
    return actual == expected if definition.comparator == Comparator.EQUALS else expected in actual


def escape_for_filter[T](to_filter: T) -> T:
    """Preserve semantic cache values; query literals provide the escaping."""
    return to_filter


class FilterCache:
    """Manages a cached filter index for an entity."""

    def __init__(self, entity: Category | Project, user: User | None = None) -> None:
        self.entity = entity
        self.user = current_context_user(user)
        self.cache_key = Keys.FILTER.value.format(self.entity.hash, FILTER_CACHE_SCOPE)

        self._to_cache = {}

    def _query_keys(self, filter: CompiledFilter) -> list[str]:
        if not isinstance(filter, CompiledFilter):
            raise TypeError("FilterCache queries require a CompiledFilter")
        literals = [definition for definition in filter.definitions if _needs_literal_match(definition)]
        if not literals:
            expression = FilterExpression(filter.definitions).build()
            identifiers = filter_cache.query(self.cache_key, expression)
            if not _entity_ids(identifiers):
                raise TypeError("Expected an array of entity IDs from the filter index")
            return identifiers
        remaining = [definition for definition in filter.definitions if definition not in literals]
        expression = FilterExpression(remaining).build(ids_only=False) if remaining else "$.*"
        rows = filter_cache.query(self.cache_key, expression)
        if not isinstance(rows, list):
            raise TypeError("Expected an array of records from the filter index")
        return [
            identifier for row in rows
            if isinstance(row, dict) and isinstance(identifier := row.get("id"), str) and identifier
            and all(_matches_literal(row, definition) for definition in literals)
        ]

    def query_roots(self, filter: CompiledFilter) -> list[Entity]:
        """Return matching roots for modified-time comparison without expansion."""
        return Entities.fetch(*self._query_keys(filter), request=Fetch.root())

    def query(self, filter: CompiledFilter) -> list[Entity]:
        """Query the cache with a filter and return matching entities."""
        return [
            entity
            for entity in Entities.fetch(
                *self._query_keys(filter),
                request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
            )
            if entity.allowed(Action.VIEW, user=self.user)
        ]

    def update(self, queue: bool = True) -> None:
        """Refresh the cache immediately or via a background task."""
        now = CONFIG.local or not queue

        if now:
            self.cache()
        else:
            assert self.user is not None
            task_endpoint = url_for("process.update_cache", _external=True)
            payload: dict[str, object] = {
                "cache_key": self.cache_key,
                "entity_key": self.entity.urlsafe_key,
                "user_key": self.user.urlsafe_key,
            }
            create_task(task_endpoint, payload)

    def _entity_map(self, entities):
        return {e.hash: cast("JsonType", escape_for_filter(e.to_filter_index())) for e in entities}

    def _load(self, cursor=None):
        if self.entity.kind == "project":
            self._load_project_tasks()
            return

        if self.entity.kind != "category":
            return

        category_key = self.entity.key
        assert category_key is not None
        while True:
            index = database_get.pages(
                category_key,
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

    def cache(self) -> None:
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

            if not _entity_ids(to_refresh):
                raise TypeError("Expected an array of entity IDs requiring a refresh")
            request = (
                Fetch.nested(because=FetchReason.TASK_FILTER_INDEX_MATERIALIZATION)
                if self.entity.kind == "project"
                else Fetch.direct()
            )
            refreshed = Entities.fetch(*to_refresh, request=request)
            filter_cache.set(self.cache_key, self._entity_map(refreshed))
