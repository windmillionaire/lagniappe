# Backend Entities

The entity system in `lagniappe/core/` is the backend domain layer. Entity
classes compose typed properties, permission checks, relationships, and domain
operations; services and routes operate through those contracts instead of raw
Datastore dictionaries.

Read this guide first, then use the focused guides for the part being changed:

| Guide | Read it for |
| --- | --- |
| [BACKEND_ENTITIES_PROPERTIES.md](BACKEND_ENTITIES_PROPERTIES.md) | Property storage, context projections, form schemas, assets, and mixins. |
| [BACKEND_ENTITIES_MUTATIONS.md](BACKEND_ENTITIES_MUTATIONS.md) | Save/delete planning, relation effects, fingerprints, fetch depth, and mutation contracts. |
| [BACKEND_ENTITIES_TASKS.md](BACKEND_ENTITIES_TASKS.md) | Task schedules, completion, history, and task combination. |
| [BACKEND_JOBS.md](BACKEND_JOBS.md) | Durable background-job records, locks, execution, recovery, and browser status. |
| [BACKEND_COMMUNICATIONS.md](BACKEND_COMMUNICATIONS.md) | Notifications, direct messages, mentions, notes, and notification email. |

## Shape of the domain layer

```text
Entity
  -> EntityProperties (lazy property instances)
       -> Property / DBProperty / AssetProperty / ProcessProperty
       -> context mixins (cache, columns, details, AI, filters, dates)
       -> relation mixins
       -> Submission (typed form fields)
  -> domain methods and permission checks
  -> mutation planner and executor
```

`Entity.__getattr__` and `__setattr__` delegate known names to properties, so
ordinary domain code uses `page.name` while context-specific consumers use the
property directly:

```python
page.name = "Project Alpha"
details = page.properties.name.details_value
ai_value = page.properties.name.ai_value
```

Each entity implements `_get_properties()` and merges its declarations with
the base properties. `EntityProperties` stores property classes and creates an
instance only on first access. Context export methods discover capabilities by
mixin rather than by entity-specific branches:

| Entity API | Property capability | Result |
| --- | --- | --- |
| `to_cache` | `CacheMixin` | Search/detail projection. |
| `to_ai(user)` | `AIMixin` | Permission-aware model context. |
| `to_filter_index(user)` | `FilterMixin` | Saved-filter projection. |
| `details` | `DetailsMixin` | Compact browser/entity references. |
| `column(field_id)` | Direct field lookup | Table display and edit contract. |

## Common entity contract

The base class provides `name`, `created`, `modified`, `kind`, `requires`,
`hash`, and `active`. Other shared properties—such as `Description`,
`RestrictedTo`, `IsPublic`, and `PublicID`—are added only by the entity types
that use them.

Important methods and values:

- `allowed(action, user)` delegates instance authorization to
  `user.has_permission(...)`.
- `related_keys` collects stored relationship keys for batch loading.
- `attach(key_map)` connects already-loaded entities to relation properties.
- `save()` and delete operations go through the `Entities` registry and the
  mutation planner; entity methods do not write raw Datastore rows directly.
- `modified` is a dependency-invalidation timestamp. It advances when the
  entity or a dependent view represented by it changes.

## Entity registry

`lagniappe/core/entities/__init__.py` exposes the `Entities` singleton. Its
public read boundary is explicit about relation depth:

```python
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities

page = Entities.fetch_one(page_key, request=Fetch.direct())
task = Entities.fetch_one(
    task,
    request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
)
```

| Method | Purpose |
| --- | --- |
| `fetch(*identifiers, request=...)` | Load ordered roots to an explicit total relation depth. |
| `fetch_one(identifier, request=...)` | Singular form of `fetch`; returns `None` when absent. |
| `save(*entities)` | Plan and commit complete domain mutations. |
| `save_root(entity, property_mask=...)` | Persist one root without lifecycle, intent, or cache work. |
| `save_document_checkpoint(...)` | Persist collaborative-document assets/history through their masked contract. |
| `advance_document_parent(entity)` | Advance document owner/list fingerprints at the lifecycle boundary. |
| `touch(*entities)` | Update only `modified` through the masked root path. |
| `delete(*entities)` | Plan survivor repairs, cascades, durable deletes, and post-commit cleanup. |

`_load()` is an internal attachment primitive. Request code must use `fetch()`
or `fetch_one()` so relation depth cannot depend on whether a caller happened
to pass a key or an already-typed entity.

## Entity types

`EntityType` in `entities/types.py` maps persisted type names to classes.
Several names share a class or act as reserved variants.

| Domain | Types |
| --- | --- |
| People and access | `USER`, `USER_GROUP`, `PUBLIC_GROUP`, reserved `USERS`. |
| Workspace models | `PROJECT`, `CATEGORY`, `FORM`, `MODEL_TASK`. |
| Workspace instances | `PAGE`, `TASK`, `FILE`, `INGRESS`. |
| Saved views and activity | `FILTER`, `CONDITION`, `NOTE`, `NOTIFICATION`. |
| History | `TASK_HISTORY`, `FORM_HISTORY`, `DOCUMENT_HISTORY`. |
| Communication | `MESSAGE_CONVERSATION`, `MESSAGE`, `MENTION_MARKER`. |
| AI and background work | `REPORT`, `DEFERRED_JOB`, `DEFERRED_JOB_LOCK`. |
| Virtual root | `HOME`. |

`MODEL` maps to `ModelTask`, `GROUP` maps to `UserGroup`, and `JOB` names map
to the deferred-job classes. `USERS` is a reserved `UserCategory`, not an
ordinary `Category` alias.

## Users, roles, and AI access

The Owner is the singleton `User` whose normalized email matches
`CONFIG.ADMIN_EMAIL` and whose durable `owner` flag is true. The Owner cannot
be demoted, deleted, reassigned, or renamed through user-management routes.
Additional Administrators have `admin: true`; only the Owner controls the
Administrator roster and secret-bearing installation configuration.

Application roles, Google Cloud IAM, and AI entitlement are independent:

- `User.is_admin` grants application administration, not cloud authority.
- Google Cloud roles do not create a Lagniappe account or session.
- `User.ai_access` is `NONE`, `ASK`, or `CREATE`; `CREATE` includes `ASK`.
- AI routes and deferred adapters recheck both ordinary permissions and the
  required AI tier before provider work and before applying mutations.

Role and AI-access state contribute to `User.authorization_fingerprint`.
Changing either invalidates cached authorization-sensitive UI.

## Indexes

`entities/index.py` contains site-level paginated list models. `TaskIndex`,
`PageIndex`, `FormIndex`, and `UserIndex` apply the viewer's restrictions,
preserve Datastore query order, load results through `Fetch.direct()`, and
publish cursors used by lazy row routes. Task pages combine two ordered query
streams: due-dated tasks first, then undated tasks by recent modification.

## Package imports

An empty package `__init__.py` is only a package marker. A nonempty file is a
deliberate façade, such as `core.entities` or `core.definitions`. Import a
concrete owner from marker packages; use an established façade when it defines
the subsystem's shared vocabulary.
