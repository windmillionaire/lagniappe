"""
Filter and Query builder for Google Cloud Datastore.

Provides a fluent API for constructing Datastore queries with support for:
- All comparison operators (=, !=, <, <=, >, >=, IN, NOT_IN)
- AND/OR composite filters
- Pagination with cursors
- Ordering
- Projection queries (fetch specific properties only)
- Keys-only queries
- Ancestor queries

Example usage:
    from .filter import Filter, Query, Results
    from .core import DATA, KINDS

    # Simple filter
    f = Filter().eq("active", True).eq("type", "page").build()
    q = DATA.datastore.query(kind=KINDS.instances.value)
    q.add_filter(filter=f)

    # Fluent query builder with Results
    r = (
        Query(KINDS.instances)
        .filter(Filter().eq("active", True).eq("type", "page"))
        .order("-modified")
        .limit(25)
        .fetch()
    )
    for page in r:
        print(page)
    if r.next_cursor:
        # fetch next page...

    # OR filter
    f = Filter().any_of(
        Filter().eq("type", "page").eq("categories", category_key),
        Filter().eq("type", "page").eq("model", category_key),
    ).build()

    # Comparison operators
    f = Filter().eq("type", "task").le("due_date", next_week).build()

    # IN filter
    f = Filter().contains("hash", ["abc", "def", "ghi"]).build()
"""

from __future__ import annotations

from typing import Any, Iterator, Optional, Union

from google.cloud.datastore import Key, query as datastore_query

from ...restrictions import Restriction
from .core import DATA, KINDS


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_results_use_normal_list_indexing_and_keep_cursor_metadata
# @matrix database : indexing pagination query-results slicing
class Results:
    """
    Container for query results with optional pagination cursor.

    Supports list-style access plus pagination metadata:
        # Attribute access
        r = query.fetch()
        for item in r.results:
            ...
        if r.next_cursor:
            ...

        # Iteration (iterates over results)
        for item in query.fetch():
            ...

        # Length
        len(query.fetch())  # returns len(results)
    """

    __slots__ = ("results", "next_cursor")

    def __init__(self, results: list, next_cursor: Optional[str] = None):
        self.results = results
        self.next_cursor = next_cursor

    def __iter__(self):
        """Iterate over results."""
        return iter(self.results)

    def __len__(self):
        """Return the number of results."""
        return len(self.results)

    def __bool__(self):
        """Return True if there are any results."""
        return bool(self.results)

    def __getitem__(self, index):
        """Allow indexing into results."""
        return self.results[index]

    def first(self) -> Optional[Any]:
        """Return the first result or None."""
        return self.results[0] if self.results else None


_DENY_ALL_FILTER = object()


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_filter_preserves_explicit_deny_all_through_composition
# @matrix database permissions : deny-all filter-composition
class Filter:
    """
    Fluent builder for Datastore filters.

    Supports all Datastore comparison operators and composite AND/OR filters.
    Chain methods to build complex filters, then call .build() to get the
    final filter object for use with query.add_filter().
    """

    def __init__(self):
        self._conditions: list[datastore_query.PropertyFilter] = []
        self._or_groups: list[Filter] = []
        self._requires: Optional[list] = None

    # --- Comparison Operators ---

    def eq(self, prop: str, value: Any) -> Filter:
        """Equal to (=)"""
        if value is not None:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, "=", value)
            )
        return self

    def is_null(self, prop: str) -> Filter:
        """Equal to null / missing (explicit ``= None`` filter)."""
        self._conditions.append(datastore_query.PropertyFilter(prop, "=", None))
        return self

    def ne(self, prop: str, value: Any) -> Filter:
        """Not equal to (!=)"""
        if value is not None:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, "!=", value)
            )
        return self

    def lt(self, prop: str, value: Any) -> Filter:
        """Less than (<)"""
        if value is not None:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, "<", value)
            )
        return self

    def le(self, prop: str, value: Any) -> Filter:
        """Less than or equal to (<=)"""
        if value is not None:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, "<=", value)
            )
        return self

    def gt(self, prop: str, value: Any) -> Filter:
        """Greater than (>)"""
        if value is not None:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, ">", value)
            )
        return self

    def ge(self, prop: str, value: Any) -> Filter:
        """Greater than or equal to (>=)"""
        if value is not None:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, ">=", value)
            )
        return self

    def contains(self, prop: str, values: list) -> Filter:
        """IN filter - property value is in the given list"""
        if values:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, "IN", values)
            )
        return self

    def excludes(self, prop: str, values: list) -> Filter:
        """NOT_IN filter - property value is not in the given list"""
        if values:
            self._conditions.append(
                datastore_query.PropertyFilter(prop, "NOT_IN", values)
            )
        return self

    # --- Convenience Methods ---

    def all_of(self, **kwargs) -> Filter:
        """
        Add multiple equality filters from keyword arguments.

        Example:
            Filter().all_of(active=True, type="page", status="published")
        """
        for prop, value in kwargs.items():
            self.eq(prop, value)
        return self

    # @testable true
    # @tests tests_unit/test_001_test_general_and_utilities.py::test_database_filter_requires_rejects_invalid_hashes_type
    # @matrix database : filter validation
    def requires(self, hashes: Optional[list]) -> Filter:
        """
        Add a requires filter for permission-based access.

        This adds an IN filter on the "requires" property to filter
        entities based on user/group hashes.
        """
        if Restriction.is_unrestricted(hashes):
            return self
        if not isinstance(hashes, list):
            raise TypeError("hashes must be Restriction.UNRESTRICTED or a list")
        self._requires = hashes
        return self

    # --- Composite Filters ---

    def any_of(self, *filters: Filter) -> Filter:
        """
        Combine multiple filters with OR.

        Example:
            Filter().any_of(
                Filter().eq("status", "active"),
                Filter().eq("status", "pending"),
            )
        """
        self._or_groups.extend(filters)
        return self

    # --- Build ---

    def build(self) -> Optional[datastore_query.PropertyFilter]:
        """
        Build and return the final Datastore filter.

        Returns None if no filters were added.
        """
        if self.is_denied:
            return _DENY_ALL_FILTER

        all_conditions = list(self._conditions)

        # Add requires filter if set
        if self._requires is not None:
            all_conditions.append(
                datastore_query.PropertyFilter("requires", "IN", self._requires)
            )

        # Handle OR groups
        if self._or_groups:
            or_filters = []
            for f in self._or_groups:
                if not f:
                    continue
                built = f.build()
                if built is _DENY_ALL_FILTER:
                    continue
                if built is not None:
                    or_filters.append(built)

            if or_filters and all_conditions:
                # Combine OR with existing AND conditions
                return datastore_query.And([
                    datastore_query.Or(or_filters),
                    *all_conditions
                ])
            elif or_filters:
                return datastore_query.Or(or_filters)

        # Just AND conditions
        if not all_conditions:
            return None
        elif len(all_conditions) == 1:
            return all_conditions[0]
        else:
            return datastore_query.And(all_conditions)

    @property
    def is_denied(self) -> bool:
        """Return whether this filter represents an explicit deny-all."""
        if self._requires is not None and Restriction.is_denied(self._requires):
            return True

        meaningful_or_groups = [group for group in self._or_groups if group]
        return bool(meaningful_or_groups) and all(
            group.is_denied for group in meaningful_or_groups
        )

    def __bool__(self) -> bool:
        """Return True if any filters have been added."""
        return bool(
            self._conditions or self._or_groups or self._requires is not None
        )


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_denied_query_terminals_do_not_create_datastore_query
# @matrix database permissions : deny-all query-short-circuit terminal-results
class Query:
    """
    Fluent query builder for Datastore.

    Wraps Filter with additional query options like ordering, pagination,
    projection, and ancestor queries.

    Example:
        # Using Results object
        r = (
            Query(KINDS.instances)
            .filter(Filter().eq("active", True).eq("type", "page"))
            .order("-modified")
            .limit(25)
            .cursor(start_cursor)
            .fetch()
        )
        for item in r:
            print(item)
        if r.next_cursor:
            # fetch next page

        # Keys-only query for counting
        count = Query(KINDS.instances).filter(f).keys_only().count()

        # Projection query (fetch only specific properties)
        results = Query(KINDS.users).project("email", "name").fetch_all()
    """

    def __init__(self, kind: Union[KINDS, str], ancestor: Optional[Key] = None):
        """
        Initialize a query for the given kind.

        Args:
            kind: Entity kind (KINDS enum or string)
            ancestor: Optional ancestor key for ancestor queries
        """
        self._kind = kind.value if isinstance(kind, KINDS) else kind
        self._ancestor = ancestor
        self._filter: Optional[Filter] = None
        self._order: list[str] = []
        self._limit: Optional[int] = None
        self._cursor: Optional[str] = None
        self._projection: list[str] = []
        self._keys_only: bool = False
        self._distinct_on: list[str] = []

    def filter(self, f: Filter) -> Query:
        """Set the filter for this query."""
        self._filter = f
        return self

    def order(self, *properties: str) -> Query:
        """
        Add ordering to the query.

        Prefix with "-" for descending order.

        Example:
            .order("-modified", "name")  # descending modified, ascending name
        """
        self._order.extend(properties)
        return self

    def limit(self, n: int) -> Query:
        """Set the maximum number of results to return."""
        self._limit = n
        return self

    def cursor(self, token: Optional[str]) -> Query:
        """Set the start cursor for pagination."""
        self._cursor = token
        return self

    def project(self, *properties: str) -> Query:
        """
        Fetch only specific properties (projection query).

        This reduces bandwidth and cost by only fetching the specified
        properties instead of the full entity.

        Note: Projected entities are read-only.
        """
        self._projection.extend(properties)
        return self

    def keys_only(self) -> Query:
        """
        Fetch only entity keys (no properties).

        Useful for counting or checking existence efficiently.
        """
        self._keys_only = True
        return self

    def distinct(self, *properties: str) -> Query:
        """
        Return only distinct values for the specified properties.

        Must be used with projection queries.
        """
        self._distinct_on.extend(properties)
        return self

    def ancestor(self, key: Key) -> Query:
        """Set the ancestor for an ancestor query."""
        self._ancestor = key
        return self

    def _build_query(self) -> Optional[datastore_query.Query]:
        """Build the underlying Datastore query object."""
        built_filter = self._filter.build() if self._filter else None
        if built_filter is _DENY_ALL_FILTER:
            return None

        q = DATA.datastore.query(kind=self._kind, ancestor=self._ancestor)

        if built_filter is not None:
            q.add_filter(filter=built_filter)

        if self._order:
            q.order = self._order

        if self._projection:
            q.projection = self._projection

        if self._keys_only:
            q.keys_only()

        if self._distinct_on:
            q.distinct_on = self._distinct_on

        return q

    def fetch(self) -> Results:
        """
        Execute the query and return Results with optional pagination cursor.

        Returns:
            Results object with .results list and .next_cursor (None if no more results).
        """
        q = self._build_query()
        if q is None:
            return Results([], None)

        if self._limit:
            q_iter = q.fetch(start_cursor=self._cursor, limit=self._limit)
            results = list(next(q_iter.pages))
            token = q_iter.next_page_token
            next_cursor = token.decode() if token else None
            return Results(results, next_cursor)
        elif self._cursor:
            return Results(list(q.fetch(start_cursor=self._cursor)))
        else:
            return Results(list(q.fetch()))

    def fetch_all(self) -> list:
        """Execute the query and return all results (no pagination)."""
        q = self._build_query()
        if q is None:
            return []
        return list(q.fetch())

    def fetch_one(self) -> Optional[Any]:
        """Execute the query and return the first result or None."""
        q = self._build_query()
        if q is None:
            return None
        results = list(q.fetch(limit=1))
        return results[0] if results else None

    def fetch_iter(self) -> Iterator:
        """Execute the query and return an iterator over results."""
        q = self._build_query()
        if q is None:
            return iter(())
        return q.fetch(start_cursor=self._cursor, limit=self._limit)

    def count(self) -> int:
        """
        Count the number of matching entities.

        Note: This fetches all keys, which can be expensive for large
        result sets. For very large counts, consider using aggregation
        queries (Datastore's COUNT aggregation) if available.
        """
        # Ensure keys_only for efficiency
        self._keys_only = True
        q = self._build_query()
        if q is None:
            return 0
        return len(list(q.fetch()))

    def exists(self) -> bool:
        """Check if any matching entities exist."""
        self._keys_only = True
        q = self._build_query()
        if q is None:
            return False
        results = list(q.fetch(limit=1))
        return len(results) > 0
