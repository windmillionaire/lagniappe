# Backend Filters

The filter system lets users create saved filter conditions on categories and projects, then query entities matching those conditions. It spans four layers: frontend widgets, backend entities, a Redis JSON cache, and a JSONPath query engine.

## Architecture

```
Frontend (filters.mjs widget)
  │
  ├── GET  /filters/{key}/condition  → Build condition UI
  ├── GET  /filters/{key}/options    → Get comparator + value inputs
  ├── GET  /filters/{key}/test       → Preview filter results
  ├── POST /filters/{key}/save       → Save filter
  └── GET  /filters/{key}            → Run saved filter
         │
         ▼
Routes (web/routes/filters/main.py)
  │
  ├── Parse the bounded v1 request contract
  ├── Resolve fields and values through the viewer's authorized catalog
  └── Produce an immutable CompiledFilter
         │
         ▼
Filter Entity (core/entities/filter.py)
  │
  ├── Stores the canonical versioned contract as JSON
  ├── Recompiles saved data for each viewer before use
  └── Adapts and validates legacy compact definitions at runtime
         │
         ▼
FilterCache (core/tools/filters/cache.py)
  │
  ├── Builds entity filter indices (entity.to_filter_index)
  ├── Stores as Redis JSON keyed by entity hash + user access
  └── Queries with FilterExpression → JSONPath
         │
         ▼
FilterExpression (core/tools/filters/build.py)
  │
  └── Converts FilterDefinitions to JSONPath queries
```

## Value Alignment

The critical design constraint: the same field identifier must be consistent across the entire stack.

```
Frontend condition DTO: field="{field.filter_key}"
Condition.field:        Property or SubmissionField object
FilterDefinition.field: field.filter_key
Cache index key:        field.filter_key (from entity.to_filter_index())
JSONPath query:         @["{field}"] where field = FilterDefinition.field
```

For values, the same alignment applies -- `field.filter_value` is used consistently in definitions and cache indices.

Dynamic form/model selectors use their related entity hash for frontend
disambiguation and the relation field's `filter_key` for cache storage. The
authorized catalog maps the selector back to its exact attached entity.

## Versioned Request Contract

Browser preview/save requests and saved filters use this envelope:

```json
{
  "version": 1,
  "conditions": [
    {
      "source_id": "entity-hash",
      "field": "name",
      "comparator": "substring",
      "values": ["urgent"]
    }
  ]
}
```

The client never supplies field type or entity-valued flags. The compiler
derives those from the viewer's current catalog, validates referenced entities
and attached-form scope, normalizes values, and returns `CompiledFilter`.
`FilterCache.query()` and `query_roots()` reject every other input type.

The envelope is limited to 32 KiB, 12 effective predicates (including injected
form selectors), 25 values per condition, and 512 UTF-8 bytes per string or
identifier. Malformed JSON/envelopes return `400`; well-formed invalid,
unavailable, or oversized filters return `422`.

Repeated compact `definition` values remain a request compatibility input and
legacy saved top-level lists remain readable. Both are converted to v1 and
fully recompiled without trusting their stored type flags. New saves write v1;
there is no write-on-read migration.

## Condition (`entities/condition.py`)

Represents a single filter condition. A condition has:

- An **entity** to filter on (the category or project)
- A **field** within that entity (a Property or SubmissionField with `FilterMixin`)
- A **comparator** (equals, contains, greater than, etc.)
- A **value** to compare against

### Setting a Condition

`set_value(form_values, default_comparator)` processes form input:

1. Normalizes values to a list
2. For boolean fields, maps to `IS_TRUE`/`IS_FALSE` comparator
3. For list fields with multiple values, auto-selects `CONTAINS_ANY`
4. For string fields with multiple values, auto-selects `IN`
5. Creates a `FilterDefinition` with the field's `filter_key`, `field_type`, comparator, and normalized value

### Initializing from a Saved Filter

`initialize(entity_hashes_map)` restores a condition from a stored `FilterDefinition`:

1. Looks up the entity by hash
2. Finds the field in the entity's `filters.fields` dict
3. Sets the comparator and value from the definition

### Details for Display

`details` returns display information including entity-valued fields resolved to names. Lazy-loads related entities from cache if needed.

## Filter Entity (`entities/filter.py`)

Stores a saved filter configuration. Properties:

| Property | Description |
|---|---|
| `parent` | The Category or Project being filtered |
| `creator` | The User who created the filter |
| `related` | Entities referenced by conditions (for relationship loading) |
| `table` | Column configuration for displaying results |
| `definitions` | Canonical v1 contract, compiled to `FilterDefinition` objects on access |
| `conditions` | Condition objects created from definitions |

### Creation

`Filter.create(entity, compiled_filter, temporary=False)`:

1. Creates a new Filter entity
2. Stores the compiler's canonical contract
3. Stores only the authorized related entities returned by compilation
4. Initializes display conditions from the derived predicates

Saved filters retain parent-scoped sharing semantics. A direct run recompiles
for its current viewer. Stale or inaccessible filters never query Redis;
view-only users do not see them, while parent editors receive a generic
deletable unavailable row.

### Filter Table

`FilterTable` (in `properties/filter.py`) generates the column configuration for displaying filter results. It includes the entity name column plus columns derived from the filter conditions (fields that implement `ColumnMixin`).

## Filters Property (`properties/base_filters.py`)

Each filterable entity (Category, Project) has a `filters` property that provides:

- `fields` -- dict of filterable fields keyed by `filter_key`. Includes both entity properties and form submission fields that implement `FilterMixin`.
- `entity_fields` -- additional entity-valued fields (form references, etc.)
- `conditions` -- serialized field metadata for the frontend filter builder UI (field key, label, kind, icon)

## FilterCache (`tools/filters/cache.py`)

Caches entity filter indices in Redis JSON for fast querying.

### Cache Key

The shared cache key is the parent hash plus the format scope `all-v2`.
Permission checks happen after matched roots are loaded. The scope version
ensures caches built before punctuation-preserving values are not reused.

### Building the Cache

`cache()` either creates or refreshes the cache:

- **Create**: Paginates through all child entities (pages for categories, tasks for projects), calls `entity.to_filter_index(user)` on each, and stores the result as a Redis JSON document.
- **Refresh**: Checks which entities have been modified since the last cache build and updates only those entries.

### Querying

`query(compiled_filter)` builds a `FilterExpression` from validated definitions,
executes it as a JSONPath query against the cached JSON, loads the matching
entity IDs with `Entities.fetch(..., request=Fetch.direct())`, and keeps only
entities the current user may view. `query_roots(compiled_filter)` uses `Fetch.root()`
for refresh membership checks that do not need relationships.

### Background Updates

In production, cache updates are deferred to Cloud Tasks (`process.update_cache` endpoint) to avoid blocking the request. In development, they run synchronously.

## FilterExpression (`tools/filters/build.py`)

Converts a list of `FilterDefinition` objects into a JSONPath query string. Each definition becomes a single JSONPath condition, and all conditions are AND-joined.

### JSONPath Patterns by Comparator

| Comparator | JSONPath Pattern |
|---|---|
| `IS_TRUE` | `@["field"] == true` |
| `IS_FALSE` | `@["field"] == false` |
| `EQUALS` (string) | `@["field"] =~ "(?i)^value$"` |
| `EQUALS` (non-string) | `@["field"] == value` |
| `GREATER_THAN` / `LESS_THAN` | Encoded numeric comparison |
| `GREATER_EQUAL` / `LESS_EQUAL` | Encoded numeric comparison |
| `BETWEEN` | Inclusive pair of encoded numeric comparisons |
| `CONTAINS` | Array membership plus scalar fallback |
| `IN` | Equality against each encoded value |
| `SUBSTRING` | Case-insensitive, regex-escaped literal match |
| `CONTAINS_ANY` | Membership against each encoded value |

The final query wraps all conditions: `$..[?((@.id) && (cond1) && (cond2))].id`

Field names use bracket notation and JSON encoding. String equality/substring
escapes regex metacharacters before JSON encoding. Unsupported comparators
raise rather than silently generating an incomplete expression.

## Routes (`lagniappe/web/routes/filters/main.py`)

All routes are on the `filters` blueprint (`/filters` prefix).

| Route | Method | Purpose |
|---|---|---|
| `/filters/{key}/condition` | GET | Build a condition: returns field options or a completed filter badge |
| `/filters/{key}/options` | GET | Get comparator/value inputs for a selected field |
| `/filters/{key}/test` | GET | Preview: create temporary filter, build cache synchronously, query, return results table |
| `/filters/{key}/save` | POST | Save: create persistent filter, return filter list item HTML |
| `/filters/{key}` | GET | Run: load saved filter, query cache, render results page |
| `/filters/{key}/get` | GET | Get all saved filters for an entity |
| `/filters/{key}/delete` | DELETE | Delete a saved filter |

## Frontend Integration

The `Filters` widget (`src/script/widgets/filters.mjs`) manages the filter builder
UI. Server-rendered badges contain explicit condition DTOs; preview/save wraps
them in one v1 `contract` form value. The test endpoint returns a rendered table
for preview, while save returns a filter list item. Saved filters can be loaded
and run as full-page views.
