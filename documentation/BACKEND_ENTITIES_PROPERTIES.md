# Backend Entity Properties

Read this guide before changing `lagniappe/core/properties/`, form schema
storage, asset properties, or a property's cache/AI/filter/table projection.

## Property lifecycle

`EntityProperties` stores property classes and lazily creates instances with
their owning entity. Ordinary access delegates through the entity, while rich
consumers use the property object itself.

| Base | Storage contract |
| --- | --- |
| `Property` | In-memory value with an explicit unset sentinel. |
| `DBProperty` | Reads and writes a key in `entity.db`; supports JSON encoding. |
| `AssetProperty` | Resolves an entity asset and writes through Cloud Storage. |
| `ProcessProperty` | Reads and writes one section of a shared JSON process record. |
| `Submission` | Manages typed fields from a form schema as one property collection. |

`Property` distinguishes unset, explicit `None`, `False`, and empty containers.
`DBProperty` treats `(None, [], {})` as blank unless a subclass overrides
`_blank_values`. For example, `Attributes` persists `[]`, so missing and
explicitly empty configurations remain different.

Do not use truthiness to decide whether a field was loaded or submitted. Use
`is_set`, `value`, and the property's normalization contract.

## Context mixins

Mixins provide a projection and mark the property as eligible for that context.

| Mixin | Projection |
| --- | --- |
| `CacheMixin` | `cache_key`, `cache_value` for search/detail indexes. |
| `ColumnMixin` | `column_value`, `sort_value`, ordering, selection, and editability. |
| `DetailsMixin` | Compact `details_key` / `details_value`. |
| `AIMixin` | Permission-aware `ai_key` / `ai_value`. |
| `FilterMixin` | Filter key, normalized value, type, and options. |
| `DateMixin` | User-timezone display and comparable filter/sort values. |
| `SearchMixin` | Submission text included in full-text search. |
| `RelatedEntityMixin` | One attached related entity. |
| `RelatedEntityListMixin` | An attached list of related entities. |
| `AssetMixin` | Entity-level asset read/write/copy/delete behavior. |
| `SubmitterMixin` | Form schema and submission behavior. |

Add a mixin only when the property belongs in that projection. A new property
does not automatically become searchable, filterable, or model-visible.

## DB-backed relationships

Relation properties store keys and receive entity instances through
`Entities.fetch()` followed by `Entity.attach()`. They do not perform hidden
per-property reads. Accessing an unattached stored relation captures an
`UnloadedRelationError` with request, caller, entity, property, and key context,
then returns `None` or `[]`.

Missing targets are omitted from the attached value without rewriting the
owner during a read. The mutation path that owns a relationship decides when
to replace its stored keys. This keeps reads side-effect free and makes
relationship cleanup explicit.

`PageCategories` stores a Page's model separately from additional categories.
Removing the model does not promote another selected category. A Page with no
model or categories uses `Uncategorized Pages`; a Page with categories but no
model uses its first category only for parent display projections.

## Submissions

`FormSubmission` and `RowSubmission` build fields from the attached schema.
Stored fields receive their backend value; absent fields remain unset. The
submission's stored projection omits unset and blank values, so an empty
submission removes `db["submission"]`.

Aggregate projections are intentionally separate:

| Projection | Use |
| --- | --- |
| `value` | Raw typed field values. |
| `form_value` | Browser form rendering. |
| `ai_value` | Model context. |
| `filter_value` | Saved-filter index. |
| `search_value` | Labeled full-text index fields. |

Internal form links store compact entity-detail snapshots inside the
submission. A Task separately maintains `linked_pages` for live relationship
and permission behavior. Task history keeps its submission snapshot immutable.

Checkboxes illustrate the unset contract: an absent stored checkbox projects
as `None`; a complete submit without the checkbox input validates it to
explicit `False`.

Task defaults live in `default_submission`. Saving one default uses a masked
root write, and a later task submit removes defaults whose values changed or
disappeared. Todo fields never repeat as defaults; reopening starts a fresh
checklist while history preserves completed items.

## Canonical form schemas

`properties/schema.py::canonicalize_schema()` is the durable schema-shape
authority. It validates fields and table columns, normalizes input types and
conditions, supplies defaults, and enforces unique IDs without mutating its
input. The `todo` type is valid only on task forms.

All durable assignment flows converge on `Schema.value` and should prefer
`Form.set_schema()`: builder saves, AI generation, ingress-created forms,
category/report operations, and direct updates. Browser builder defaults are a
presentation convenience, not a persistence contract.

`schema_format` records the storage format independently from the form's
user-facing version. During a data update, readable rows remain projectable so
the Administrator workflow can report malformed values instead of silently
discarding them. See [DATA_MIGRATIONS.md](DATA_MIGRATIONS.md).

## Assets and processes

`AssetMixin` owns an entity's asset descriptors and delegates bytes to
`tools/database/assets.py`. Asset deletion is post-commit cleanup; a provider
failure cannot make the Datastore outcome ambiguous.

`ProcessProperty` stores named sections such as extraction, summary, and task
scheduling in a shared JSON document. A process property declares its DB key,
section ID, and allowed dynamic attributes. Cross-record orchestration remains
in a service, not in the property.

## File organization

Property modules use domain prefixes (`page_*`, `task_*`, `file_*`, `user_*`,
`form_*`) and `common_*` for genuinely shared behavior. Base classes use
`base_*`. Keep a new property with the entity or concern it serves; split a
module when unrelated durable contracts begin sharing only a filename.
