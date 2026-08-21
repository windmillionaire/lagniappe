# Backend Entities

The entity system (`lagniappe/core/`) is the heart of the backend. It uses a **context-aware property system** where each property can represent itself differently depending on the context -- table display, AI export, search indexing, filtering, caching -- all without scattered if/else logic. Properties declare their capabilities through mixins, and the Entity base class uses `isinstance()` to discover what belongs where.

## Architecture

```
Entity (base class)
  ├── EntityProperties (lazy dict of property instances)
  │     ├── Property (base -- in-memory value)
  │     ├── DBProperty (synced with entity.db)
  │     ├── AssetProperty (Cloud Storage files)
  │     ├── ProcessProperty (background process state)
  │     └── Submission (form field collection)
  │
  ├── Mixins (capability markers + methods)
  │     ├── CacheMixin      → .cache_value
  │     ├── ColumnMixin      → .column_value, .sort_value
  │     ├── DetailsMixin     → .details_value
  │     ├── AIMixin          → .ai_value
  │     ├── FilterMixin      → .filter_value
  │     ├── DateMixin        → date formatting
  │     ├── SearchMixin      → .search_value
  │     ├── RelatedEntityMixin / RelatedEntityListMixin → relationships
  │     ├── ProcessMixin     → .section, .error, .complete
  │     ├── AssetMixin       → file storage on the entity
  │     └── SubmitterMixin   → form submission handling
  │
  └── Entity Types (compose properties + business logic)
        Category, Page, Project, Task, Form, File, User, ...
```

### Package import convention

Package `__init__.py` files have two intentional roles. An empty file is only a
package marker, so callers import the concrete submodule they need. A nonempty
file is a deliberate subsystem façade, such as `core.entities` or
`core.definitions`, that exposes stable vocabulary used broadly across the
backend. Do not add re-exports merely to make marker packages look uniform, and
do not bypass an established façade without a concrete circular-import or
ownership reason.

## Entity Base Class (`entities/entity.py`)

### Construction

Entities are created with either a Datastore entity dict (from a database read) or nothing (for new entities). The constructor sets up the key and an empty `_db` dict:

```python
page = Page()                  # New entity, auto-generated key
page = Page(datastore_entity)  # From database
page = Page(urlsafe_key)       # From URL parameter
```

### Property Delegation

The `__getattr__` and `__setattr__` overrides make properties feel like regular attributes:

```python
page.name = "Project Alpha"    # Calls page.properties["name"].value = "Project Alpha"
title = page.name              # Returns page.properties["name"].value
```

For richer access, use the properties dict directly:

```python
page.properties.name.column_value   # Formatted for table display
page.properties.name.ai_value       # Formatted for AI context
page.properties.name.filter_value   # Formatted for search/filtering
page.properties.name.cache_value    # Formatted for caching
page.properties.name.details_value  # Formatted for API/frontend details
```

### `_get_properties()`

Each entity subclass overrides this to declare its properties:

```python
class Page(AssetMixin, SubmitterMixin, Entity):
    entity_kind = "page"

    def _get_properties(self):
        properties = {
            "name": common_entity.Name,
            "categories": page_related.PageCategories,
            "image": page_assets.Image,
            "submission": form_submission.FormSubmission,
            # ...
        }
        return EntityProperties(self, {**super()._get_properties(), **properties})
```

The base `Entity._get_properties()` provides shared properties: `name`,
`created`, `modified`, `kind`, `requires`, `hash`, and `active`.

### `EntityProperties`

A dict subclass that lazily instantiates property classes on first access. Properties are stored as classes in the dict and instantiated (with `entity=self`) only when accessed via `_get()`. Once instantiated, they're cached in `_instances`.

The `implementing(*mixins)` method yields all property instances that are
subclasses of the given mixin(s), used by context export methods.

### Context Export Methods

These methods use `isinstance()` to discover which properties belong in each context:

| Method | Discovers | Returns |
|---|---|---|
| `to_cache` | `CacheMixin` | Search-index fields plus `details_key`/optional `parent_key` pointers |
| `to_ai(user)` | `AIMixin` | Dict of `{ai_key: ai_value}` for AI context |
| `to_filter_index(user)` | `FilterMixin` | Dict of `{filter_key: filter_value}` for filtering |
| `details` | `DetailsMixin` | Dict of `{details_key: details_value}` for frontend |
| `column(field_id)` | Direct lookup | Property or submission field for table column display |

### Relationships

Properties that are `RelatedEntityMixin` or `RelatedEntityListMixin` represent relationships to other entities. The Entity base class provides:

- `related_keys` -- collects all related entity keys from relationship properties
- `attach(key_map)` -- after bulk loading, attaches resolved entity instances to relationship properties
- `relations` -- lists all relationship properties

DB-backed relationship properties do not lazy-load their stored keys on access.
If code asks for a relation that has keys but was not attached by
`Entities.fetch()`/`Entity.attach()`, the mixin captures an
`UnloadedRelationError` with request, caller, entity, property, and key context,
then returns `[]` for list relations or `None` for single relations. This keeps
unexpected N+1 reads visible instead of hiding them inside convenience accessors.

When a relationship load does query a stored key and the target no longer
exists, attachment likewise exposes no value: a single relation is `None` and a
list omits the missing target. Loading is read-only, so the original key remains
in `entity.db` until a write path that owns that property replaces it. This is
intentional for non-owning Page references. Page deletion cascades Tasks and
TaskHistory owned through their `page` property, but does not query and rewrite
otherwise surviving rows merely to remove `linked_pages`, `assigned_to`,
`assigned_by`, or `completed_by` keys. Relevant active-Task edits
opportunistically normalize those properties: saving a submission recalculates
`linked_pages`, Task settings rewrite assignment fields, and completion changes
rewrite `completed_by`. A bare `Task.save()` does not normalize unrelated
properties, and historical rows may retain unresolved references.

`PageCategories` exposes a page's model together with its additional categories,
but persists those relationships separately. Updating the category list removes
an omitted non-reserved model without promoting another selected category into
that role. If the update leaves both the model and category list empty, the page
uses `Uncategorized Pages` as its model. When a page has categories but no
model, its details/search-cache parent projection uses the first category so it
matches the page-title breadcrumb; the persisted model remains unset.

Deleting a user normally cascades through their page. Callers that explicitly
set `preserve_user_pages=True` delete only the user, clear the page's `user`
relationship, and remove the reserved `USERS` model. A preserved page keeps any
other categories; if it has none, `Uncategorized Pages` becomes its model.
Cache cleanup removes both the Page's physical `page` search projection and its
former virtual `user` projection. Search hydration also drops and deletes a
legacy projection whose authoritative entity-details row is already gone.

The Administrator create-user route may adopt an existing public user instead of
creating a duplicate. Adoption keeps the Identity Platform/user key, clears the
public flag, and applies the submitted name, page, AI access, and groups through
the normal user-creation assignments. If the submitted page replaces the
public user's page, the previous page is unlinked and removed from the reserved
Users model while the adopted user's active-session cache is marked stale.

### Permissions

`allowed(action, user)` checks if the current user has permission to perform an action on the entity. Delegates to `user.has_permission(self, action)`.

`has(attribute_name)` checks if a feature (tasks, document, photo, etc.) is enabled on the entity via its attributes property.

### Saving

`Entity.save()` delegates to `Entities.save()`. The registry routes every
explicit root by `entity_kind` through `core/mutations/`, where the kind planner
declares full root writes, masked dependent writes, cache work, and other side
effects in one authoritative `MutationPlan`. Every argument passed directly to
`Entities.save(*entities)` is a normal full `StandardMutation` root. Lifecycle
properties, requirements, process serialization, and the complete
`exclude_from_indexes` set are prepared by the executor before the durable
write.

Entities register typed `MutationIntent` values for work discovered while a
domain object is being changed. `standard` intents represent another complete
domain write; `patch` and `touch` intents represent narrow dependent writes;
cache-state and search-delete intents are post-commit work. Captured intents
are consumed only after every durable write/delete succeeds. A durable failure
therefore leaves the pending work available for retry.

Property-masked effects use Datastore `update` mutations rather than `upsert`.
Only properties named by the mask are changed, and a missing row is not
recreated from a partial document. List owners that only need a new `modified`
timestamp are therefore written with a `modified` mask; mirrored relations name
their exact durable fields and lifecycle updates in the same mask. Full roots
remain complete-document upserts.

`modified` is the entity's dependency-invalidation timestamp: it changes when
the entity itself changes or when a dependent view represented by that entity
changes. For example, changing a Page touches its Category owners because their
page lists changed. Both the Page and Categories consequently receive new
fingerprints and ETags. A future direct-content-only timestamp would be a
separate property; it would not narrow the meaning of `modified`.

Redis projection refreshes, cache deletion/state invalidation, search cleanup,
and blob deletion execute only after durable work succeeds. The returned
`MutationOutcome` separates `durable_committed` from post-commit completion so
a cache or storage failure cannot make the durable result ambiguous.

`Entities.delete()` uses the same plan/executor boundary. It merges repeated
survivor instances by key, commits survivor unlinks and durable deletes before
cache or blob cleanup, and reports post-commit provider failures in the
outcome. There is no optimistic revision or conflict-detection layer in this
contract.

### Mutation contracts

`core/definitions/mutation_contracts.py` is the machine-readable inventory for
every persisted entity kind and DB-backed relation. Each relation declares its
targets, cardinality, durable authority, mutation gateway, persistence shape,
and source/target delete policy. Query-derived edges are included but marked
`persisted=False`; virtual Site/Home entities and non-persisted Conditions are
outside the registry.

Inspect the contract as text or JSON and fail on registry drift with:

```bash
venv/bin/python run.py mutation-contracts --kind task --json
venv/bin/python run.py mutation-contracts --check
```

The kind registry is explicit for both save and delete; an unregistered
persisted kind is an error rather than silently receiving generic behavior.
Effects use durable (`upsert`, `unlink`, `delete`) and post-commit
(`cache-refresh`, `cache-delete`, cache-state/search cleanup, `blob-delete`)
phases. `Entities.save/delete` remain the normal planning and execution
facades. `Entities.save_root(entity, property_mask=...)` uses a minimal
root-only plan: it persists the root and its complete index-exclusion set
without lifecycle updates, typed-intent consumption, or cache work.
`Entities.touch(...)` uses that same boundary with a `modified` property mask.
Collaborative-document persistence uses its own masked contract:
`Entities.save_document_checkpoint(...)` writes only `assets` and
`document_history`, consumes document-history intents, and refreshes cache
without changing the parent fingerprint. A later
`Entities.advance_document_parent(...)` writes only the parent/list-owner
`modified` fields when the changed document leaves its active lifecycle.
Document-only Page/Project masks are also neutral to global site fingerprints;
the lifecycle `modified` touch is the collection-invalidation boundary.

## Property Base Classes (`properties/`)

### Property (`base_property.py`)

The root base class. Holds an in-memory value (not persisted). Provides `id`,
`label`, `icon`, `kind`, `user`, `value`, `editable`, `is_set`,
`is_entity_valued`, and `unset()`.
Unset state is tracked with a private `UNSET` sentinel rather than `False`.
`value` returns `None` while unset, `is_set` reports whether a value has been
assigned or loaded, and `unset()` returns the property to the sentinel state.
This keeps `False` and explicit `None` available as real domain values.
`is_entity_valued` defaults to `False`; related-entity mixins set the backing
flag so both table rendering and filtering can treat entity detail dicts as
entity links.

### DBProperty (`base_db.py`)

Extends `Property` to sync with `entity.db` (the Datastore entity dict). On get,
it reads from `entity.db[db_key]` only when the property is unset. Missing DB
keys leave the property unset and return public `None`.

On set, `DBProperty` writes to `entity.db[db_key]` unless the value is blank.
The default `_blank_values` are `(None, [], {})`; assigning any of those pops
the DB key and calls `unset()`. A property can override `_blank_values` when an
empty container is meaningful. For example, `Attributes` uses
`_blank_values = (None,)` so `attributes=[]` remains persisted and distinct
from missing attributes.

Supports `json = True` for automatic JSON serialization/deserialization of complex values.

The semantic split is:

- unset means not loaded, not submitted, or missing from storage;
- `None` means the public empty value, or an explicitly cleared scalar before persistence;
- `False` means explicit false and is persisted like any other nonblank value;
- `[]` and `{}` are blank by default unless `_blank_values` says otherwise.

### AssetProperty (`base_asset.py`)

Extends `Property` for file-based assets (images, documents, Yjs snapshots). Reading returns the asset path from the entity's asset storage. Writing uploads the file to Cloud Storage via `entity.save_asset()`.

### ProcessProperty (`base_process.py`)

For properties that track background process state (extract, summarize, schedule). Stores data as JSON sections within a shared process dict on the entity.

Configuration: `process_id` (DB key for the JSON blob), `section_id` (section within that JSON), `attributes` (dynamic attributes read from the section).

Provides `error`, `complete`, `update(form_data)`, and `clear()`. Dynamic `__getattr__`/`__setattr__` reads/writes section keys listed in `attributes`.

### Submission (`base_submission.py`)

Not a single property but a collection manager for form submission fields. Each field is a typed property (input, checkbox, select, etc.) loaded from the entity's form schema. Provides aggregate accessors:

| Accessor | Returns |
|---|---|
| `value` | Dict of `{field_id: submission_value}` |
| `form_value` | Dict of values formatted for form display |
| `ai_value` | Dict of values formatted for AI |
| `filter_value` | Dict of values formatted for filtering |
| `search_value` | Dict of `{label: value}` for search indexing |

`FormSubmission.fields` and `RowSubmission.fields` construct all schema fields.
When a stored submission contains a field id, the field receives that `db_value`;
when the field id is missing, the field is `unset()`. `SubmissionProperty.db_value`
omits unset fields and blank projections (`None`, `[]`, `{}`), and
`SubmitterMixin.save_submission()` persists through the submission property.
That means an empty submission removes `db["submission"]` instead of storing an
empty JSON object.

Internal form links are stored inside the submission as entity-details
snapshots, rather than as ordinary DB-backed relationship properties. The
current internal-link setter resolves a new target ID to current entity details,
but preserves the stored details object when the submitted ID is unchanged.
`Task.save_submission()` separately collects internal Page IDs, fetches the
targets, and replaces the Task's `linked_pages` relation with the targets that
still exist (excluding the Task's owning Page). It does not currently reconcile
unchanged details snapshots against that resolved target set. Consequently a
deleted target disappears from `linked_pages` after the next submission save
while its stored submission link can remain visible and lead to a 404. Loads do
not rewrite submissions, and TaskHistory intentionally preserves its snapshot,
including links whose targets were later deleted.

Tasks can persist selected history values in `default_submission` through
`SubmitterMixin.save_default_field()`. The method copies one field's backend
`db_value` through a root-only `default_submission` property-mask update, without
normal intent, cache, or lifecycle work. A later submission keeps defaults
whose values are unchanged and removes
defaults that changed or disappeared. Reopening a task starts its submission from
a copy of the remaining defaults; task assignment remains in place across
completion and reopening. Task-only todo fields are excluded from repeating
defaults: their completed value is retained in task history, while the reopened
task starts with no items.

Checkbox fields use the unset split to distinguish storage state from submitted
state. A never-submitted or missing stored checkbox is unset and projects as
`None`; a full form submit with no checkbox input validates every schema field,
so that checkbox becomes explicit `False`; stored explicit `false` remains
explicit `False`.

### Canonical form schemas (`schema.py`)

`canonicalize_schema()` is the durable schema-shape authority. It validates
field and table-column definitions, normalizes direct input types, supplies
field defaults, enforces unique ids and canonical condition lists, and returns
a copy without mutating its input. Canonicalization preserves membership: it
neither inserts nor strips the page-special `name` and `description` ids.
Explicit fields remain customizable and `SubmitterMixin.save_submission()`
mirrors their submitted values into page metadata. When an attached page form
omits them, `PageForm` renders the standalone special fields instead.
Form-history snapshots use `snapshot=True` to apply the same shape
normalization to historical members. The `todo` schema type is accepted only
for task forms and stores ordered `{text, checked}` item objects.

All typed schema assignment passes through the `Schema.value` setter, and
durable callers should prefer `Form.set_schema()`. Builder saves, AI category
and report operations, form generation, direct updates, and ingress-created
forms therefore converge on the same projection. Browser builder defaults are
presentation-only and are not a second persistence contract.

`schema_format` records `SCHEMA_FORMAT_VERSION` separately from the form's
user-facing schema version. Readers project unversioned valid schemas while a
migration is running; malformed rows remain visible in their raw shape so
**Apply Updates** can report them instead of silently discarding data. See
[DATA_MIGRATIONS.md](DATA_MIGRATIONS.md).

## Mixins (`mixins/`)

Mixins serve dual purposes: they provide methods (the contextual value accessor) and act as type markers that tell the system which context a property belongs to.

| Mixin | Provides | Used By |
|---|---|---|
| `CacheMixin` | `cache_key`, `cache_value` | `entity.to_cache` -- search index entries |
| `ColumnMixin` | `column_value`, `sort_value`, `ordering`, `selected`, `editable` | Table displays -- determines how the property renders in columns |
| `DetailsMixin` | `details_key`, `details_value` | `entity.details` -- lightweight entity info for frontend |
| `AIMixin` | `ai_key`, `ai_value` | `entity.to_ai()` -- context for AI prompts |
| `FilterMixin` | `filter_key`, `filter_value`, `field_type`, `field_options` | `entity.to_filter_index()` -- filterable fields |
| `DateMixin` | `column_value`, `sort_value`, `filter_value` (all date-formatted) | Date/time properties -- timezone-aware formatting |
| `SearchMixin` | `search_value` | Submission fields included in search |
| `RelatedEntityMixin` | `keys`, `attach()`, `remove()` | Single attached entity (e.g. page.model); reports unloaded key access |
| `RelatedEntityListMixin` | `keys`, `attach()`, `remove()` | List of attached entities (e.g. page.categories); reports unloaded key access |
| `AssetMixin` | `get_asset()`, `save_asset()`, `copy_asset()`, `delete_asset()`, `assets` | Entity-level mixin for file storage support |
| `SubmitterMixin` | `form_submission()`, `ai_submission()`, `schema`, `submission` | Entity-level mixin for form data handling |
| `ProcessMixin` | (marker only) | Identifies process-related properties |

To include a property in a context, add the mixin. To exclude it, omit it:

```python
# Included in cache, columns, details, AI, and filters
class Name(CacheMixin, ColumnMixin, DetailsMixin, AIMixin, FilterMixin, DBProperty):
    _id = "name"

# Included only in columns and filters (not cached, not in AI, not in details)
class Created(DateMixin, ColumnMixin, FilterMixin, DBProperty):
    _id = "created"
```

## Common Entity Properties (`properties/common_entity.py`)

These are inherited by all entities via the base `Entity._get_properties()`:

| Property | Mixins | Description |
|---|---|---|
| `Name` | Cache, Column, Details, AI, Filter, DB | Entity name. Sort strips "The ". Column value returns full entity details. |
| `Created` | Date, Column, Filter, DB | UTC datetime, auto-set on first save. |
| `Modified` | Date, Column, Filter, DB | UTC datetime, auto-set on every save. |
| `Kind` | Details, Cache, DB | Entity type string (stored as "type" in DB). |
| `Hash` | Details, Cache, Filter, AI, DB | Short hash from urlsafe key, used for permissions and search. |
| `Requires` | Cache, DB | List of entity hashes required for access. |
| `Active` | DB | Boolean. Inactive entities are excluded from normal active-entity queries. Task completion is tracked separately. |

Other common property classes, such as `Description`, `Attributes`,
`RestrictedTo`, `IsPublic`, and `PublicID`, are registered by the entity types
that need them rather than by every entity.

## Entity Types (`entities/types.py`)

The `EntityType` enum maps type names to entity classes:

| Type | Class | Description |
|---|---|---|
| `USER` | `User` | Site users with permissions |
| `PROJECT` | `Project` | Projects with documents and model tasks |
| `CATEGORY` | `Category` | Categories that contain pages |
| `USERS` | `UserCategory` | Reserved Users model/category with user-resource permissions |
| `PAGE` | `Page` | Pages with form submissions, tasks, files |
| `TASK` | `Task` | Tasks with scheduling, due dates |
| `FORM` | `Form` | Form schemas used by categories |
| `FILE` | `File` | Uploaded files with ingress pipeline |
| `MODEL_TASK`, `MODEL` | `ModelTask` | Template tasks attached to projects; `MODEL` is an alias |
| `FILTER` | `Filter` | Saved filter configurations |
| `USER_GROUP`, `GROUP` | `UserGroup` | User permission groups; `GROUP` is an alias |
| `PUBLIC_GROUP` | `PublicGroup` | Public access groups |
| `NOTE` | `Note` | Entity notes |
| `INGRESS` | `Ingress` | CSV import staging |
| `CONDITION` | `Condition` | Filter conditions |
| `TASK_HISTORY` | `TaskHistory` | Task history records |
| `FORM_HISTORY` | `FormHistory` | Form submission history records |
| `DOCUMENT_HISTORY` | `DocumentHistory` | Document history records |
| `NOTIFICATION` | `Notification` | Notification/activity records |
| `MESSAGE_CONVERSATION` | `MessageConversation` | Internal participant state and unread cursors for a direct-message peer |
| `MESSAGE` | `Message` | Canonical plain-text message child of one conversation |
| `MENTION_MARKER` | `MentionMarker` | Durable document/occurrence delivery idempotency marker |
| `REPORT` | `AIReport` | Reviewed AI report proposals and execution state |
| `DEFERRED_JOB`, `JOB` | `DeferredJob` | Internal durable background-job envelope |
| `DEFERRED_JOB_LOCK`, `JOB_LOCK` | `DeferredJobLock` | Deterministic target/scope ownership for active deferred work |
| `HOME` | `Home` | Home page virtual entity |

Aliases exist for convenience where shown in the table. `USERS` is its own
reserved category class, not a `CATEGORY` alias.

### Application Owner and Administrators

`User.is_owner` is true only for the singleton canonical User whose normalized
email matches `CONFIG.ADMIN_EMAIL` and whose stored `owner` flag is true. Owner
creation and owner-projection repair may establish that flag; ordinary role
management cannot. The Owner cannot be demoted, deleted, reassigned, or have
the canonical email changed through user-management routes.

`User.is_admin` is true for the Owner or for a managed User with stored
`admin: true`. Missing legacy fields are false. Additional Administrators have
the Owner's ordinary application permissions for content, restrictions, Site
Settings, exports, ingress, groups, and user management. Only the Owner may
change the Administrator roster, edit/delete another privileged account, or
inspect/download secret-bearing installation configuration. Demotion only
clears `admin`; account deletion is a separate operation.

Role identity is part of `User.authorization_fingerprint`, and a role change
sets `invalidate_cache` on the target User so browser authorization changes
take effect immediately. Application roles do not imply Google Cloud IAM, and
Google Cloud IAM does not imply an application role.

### Per-user AI access

`User.ai_access` is a separate entitlement from resource permissions and group
membership. Its stored values are `NONE`, `ASK`, and `CREATE`. `CREATE`
includes `ASK`; `ASK` permits workspace questions and Ask reports but not
generation, autofill, summarization, Organize/Create reports, or proposal
execution. `User.access(AI.ASK)` and `User.access(AI.CREATE)` are the
authoritative checks. They deliberately do not grant an owner bypass.

Administrators can set this value for ordinary managed users; only the Owner
may edit an additional Administrator's account. New Owners persist `CREATE`,
while every other newly created user
persists `NONE`. For datastore compatibility, a regular user record with no
stored value resolves to `CREATE`, while a legacy public user resolves to
`NONE`; an explicit value always wins. No group-level AI entitlement or
datastore migration is required.

AI route handlers check the entitlement in addition to their ordinary resource
permission checks. Deferred AI adapters declare `required_ai_access`, reload
the actor, and reauthorize both before provider work and immediately before
applying mutations. This makes a downgrade effective for already queued work.
`User.authorization_fingerprint` combines permission and AI-access state so
ETags and home polling do not reuse UI authorized under an earlier tier.

Notifications are activity entities with a `parent` user, plain-text `body`,
optional related `target`, and a `pending` flag for deferred work. A persisted
`notification_type` separates ordinary rows from the deterministic per-user
aggregate. The aggregate remains durable at zero and stores exact ordinary and
unread-message counts plus its own revision/generation; it never appears in the
ordinary cursor query. Offline
mutation replay can set `offline=True` on a route request; routes that want a
durable user-visible completion message create a `Notification` with
`parent=current_user` and the affected target. Most deferred routes create the
notification as pending and update the same entity when the process finishes.
Completion-only file jobs create it at the end, reviewed report execution uses
none, and email ingestion uses a failure-only policy so its successful handoff
does not create an inbox or notification-email event.
Committed notification creates/content updates/deletes emit a post-commit Redis
projection effect. Ordinary create/delete/clear operations use
`notification_service` to update the row and durable aggregate. Direct-message
and mention transactions update their recipient aggregate in the same
transaction as the unread state or visible Notification. They do not write the User or a notification/site
fingerprint, and cache failure never rolls back the durable entity mutation.
The notification menu promotes stored target keys to explicit fetch roots, so
each target's direct relations are available for permission checks and display
without a nested fetch. This includes a task's backing page.

Managed users also have a user-owned `notification_email_mode` preference with
stored values `NONE`, `IMMEDIATE`, and `DAILY`. Missing values resolve to
`DAILY`; public users always resolve to `NONE`, and users without a
`last_login` are ineligible. Selecting `NONE` advances an opt-out generation so
already queued deliveries are suppressed at send time. Owners cannot change
another user's preference.

Final ordinary notifications, document mentions, and direct messages capture
compact durable `email_deliveries` rows after their primary transaction. Email
is supplementary: record or Cloud Tasks enqueue failures are reported but do
not roll back the notification/message. Immediate notification email is due
after five minutes and is suppressed when the recipient has made any
authenticated application request in the preceding ten minutes. Immediate
messages use one candidate per conversation, wait until five minutes after the
latest inbound message, and suppress delivery after a read, clear, hide,
reply, or recent-site-activity signal. The activity hint is a throttled Redis
write from existing requests, not a browser heartbeat, and cache failure makes
the hint unavailable rather than blocking delivery. Immediate message email
uses the conversation-safe `New messages on {App Name}` subject while the body
identifies the sender for each rendered message.

Daily events are grouped for the recipient's next local 8:00 AM and include
events even when they were seen on site. A digest renders the first 100 events,
combines messages from the same sender under one conversation link, and links
to Notifications and Messages when more remain. It starts directly with the
first event rather than repeating a digest heading. Successful Ask/Organize,
autofill, and file-summary completions use their saved target names and direct
links without redundant ready copy; report links resolve to the report detail
route rather than the home fallback. Delivery uses simple multipart text/HTML
through the configured SMTP sender and a stable `Message-ID`; the HTML contains
plain event content and direct application links with no external assets.
Document-mention email uses a concise mention-specific subject and body,
emphasizes the document name, and
opens the entity's `document` tab directly. Task-assignment email likewise uses
a concise `Task assigned on {App Name}` subject, names the assigner and task,
and omits the generic notification headings. One-off OIDC Cloud Tasks call
`/process/notification-email`; notification email does not add a recurring
scheduler or keep the basic-scaled service awake. Sent/suppressed rows are
compacted to small idempotency tombstones.

`MessageConversation` uses a deterministic key derived from two sorted User
keys. It stores participant/name snapshots, per-user unread/read/clear cursors,
visibility, sequence, and revision. A single `Message` child stores sender,
recipient, sequence, a trimmed unindexed body of at most 1,000 characters, and
per-user hide state. Its deterministic sender/operation key makes matching
replays idempotent and conflicting reuse an error. All message body reads are
participant-authorized; owner status grants no override. Permission loss keeps
history but blocks new sends.

Managed-user collaboration uses the cached `user_message_restrictions` union
of group membership and group `VIEW`, with global Users `VIEW` unrestricted.
The owner has fail-closed `allow_messages_and_mentions` and
`allow_task_assignments` inbound toggles. Redis holds a disposable owner search
projection, while mutation checks always use the already-loaded canonical
owner row. Task assignee transitions increment `assignment_revision` and plan
one deterministic ordinary Notification for a different non-self recipient.

Deferred-job status transactions write only the durable job and
scheduler-control records they actually change; job activity does not
invalidate the User, global users list, or authorization-derived response
caches. Reconstructable operation and notification revisions live in separate
expiring Redis projections documented in
[BACKEND_TOOLS.md](BACKEND_TOOLS.md).

Notes are activity entities with an author `user`, owning `parent`, optional
plain-text `body` and photo asset, a server-assigned `scope` (`home` or `page`),
and `visibility` (`private` or `everyone`). Home-scoped shared notes appear in
authenticated Home feeds; Page-scoped shared notes remain on their Page and
also require Page view access. Private notes and note deletion are limited to
the creator and application Administrators. Any signed-in user may create a private Home-scoped
note, but only an Administrator may give it `everyone` visibility. Page-scoped
note creation and visibility continue to follow Page edit access. Note
mutations touch their parent and author, and Page/user deletion cascades through
attached notes and photo assets.

`DeferredJob` is the internal durable envelope for user-facing background
work. Jobs are retained as operational records and are not a general
user-visible entity list. Version 2 stores an immutable request fingerprint,
transactional job/notification creation, resumable adapter-start metadata,
dispatch state/task identity, a monotonic status revision, a 24-minute attempt
deadline, bounded progress phases, and opaque telemetry correlation. Unknown
versions fail rather than guessing at compatibility. The combined inline
contract is limited to 750 KiB.

Every committed client-visible status revision is published post-commit to a
small per-job Redis projection containing only revision, terminal state, and a
durable-verification timestamp. Lease-only heartbeats do not publish because
they do not change status. Owner polls skip a job-row load while their supplied
revision matches a projection verified during the last minute; misses,
mismatches, and older projections reload the durable job in batches and repair
Redis. Non-owner descriptors always use the durable permission-checked path,
so the cache cannot grant access. Redis failures never roll back a job
transition, and the bounded verification interval prevents an indefinitely
stale cache value from hiding a missed or delayed invalidation.

`DeferredJobLock` is a separate, small Datastore record keyed by a hash of the
target and mutation scope. Page/task autofill creates its job, notification,
and `form-autofill` lock in one transaction, so only one active job can own a
target form. Keeping the lock outside the page/task prevents lock bookkeeping
from changing the target's domain fingerprint or being lost by a stale full
entity save. Terminal cleanup compare-and-deletes the lock by operation ID;
read paths may lazily remove a lock whose referenced job is already terminal.
The lock itself stores no sync ID and no generated or submitted form content.
CreatePage autofill persists the active job reference on the newly created Page
and acquires the same target lock before returning its table row. The source
CreatePage form remains available because it is not the job target. Opening the
new Page renders the stored operation key and subscribes directly to its
Redis-backed status without a target-to-job lookup. Terminal cleanup
compare-clears the reference so a stale worker cannot remove a newer job's
ownership. The reference uses an index-excluded, property-masked write that
does not advance site fingerprints, so this internal lifecycle state cannot
produce a user-facing form or collection change by itself. The form revision
captured when the job is queued still guards proposal application against
target drift.

Workers use a five-minute lease renewed every 60 seconds while blocking
provider work is active. They check deadline, cancellation, and claim ownership
between provider rounds and tool calls. Immediately before inspect/apply they
reload the actor and mutation inputs, re-run current authorization, and compare
the mutation-specific revision captured at start. Autofill uses a form-only
revision (form/schema version, durable/default submission, and schema-mirrored
name/description) plus active lock ownership, so unrelated task/page settings
do not create false drift. Other mutation adapters retain their target
fingerprints. Report jobs additionally require the
report's active operation key to match; starting a replacement writes a
`superseded` tombstone for the prior job. Cancellation writes the same kind of
transactional terminal tombstone and revokes the lease before cleanup.

File processing is dispatched only after the file and its queued option state
have been persisted. When summarization and text extraction are both selected,
summarization reads the original asset first and terminal delivery starts one
idempotent extraction successor, even when summarization fails. File jobs bind
drift protection to the original asset fingerprint rather than summary or
processing metadata. OCR checkpoints retain the extracted text asset definition
alongside process state so recovery cannot mark extraction complete without
reattaching its stored text.

Deferred-job compare-and-set transactions rerun their complete read/check/write
body after Datastore contention, using three bounded delays before surfacing an
exhausted `ABORTED` response. This preserves lease and revision checks while
preventing expected worker/heartbeat races from stranding active work.

A job remains `delivery_pending` until cleanup, notification persistence, and
terminal visibility markers have completed. A later Cloud Task or the
scheduled reconciler resumes at the incomplete marker without repeating
provider preparation or domain apply.

The stable `site/deferred-jobs-control` record tracks the URL-safe keys of jobs
that still require recovery. Membership includes `queued`, `running`, and
`retry_wait` jobs plus terminal jobs whose delivery remains pending. Creation
adds membership in the job transaction; cancellation, failed pre-claim setup,
and the final `delivery_pending` to `complete` transition remove it in their
job transactions. The set makes duplicate lifecycle calls harmless and its
derived count is diagnostic rather than a separate authority.

That site record also stores initialization state, desired/applied Scheduler
state, a monotonic generation, and a short synchronization lease. The first
job requires the exact Cloud Scheduler reconciler to be enabled before its
start request succeeds; the last completion requests a pause, whose failure is
safe because it only permits extra recovery calls. One lease holder serializes
provider mutations and rereads the latest generation after each API response,
so a concurrent first-job resume wins over a stale last-job pause. Each
reconciliation repairs membership from the durable recovery query with an
optimistic generation check. Status-class changes advance that generation so
the scan cannot publish a mixed view of its separate status queries. A clean
empty scan requests a pause immediately.

Cloud Tasks sends only `{ "job_key": "..." }` to `/process/jobs`. Deterministic
task IDs make duplicate scheduling harmless, and a delivery may run for up to
30 minutes. A configured production queue must return a task identity. A
transient initial enqueue exception leaves the transactionally persisted job
as `pending` for scheduled recovery; an explicitly disabled production queue
still fails fast. A second deterministic task checks the job after two minutes
and, if it is still queued or running, replaces the pending notification with a
clear "still working" message.

While recovery-required work exists, the Cloud Scheduler reconciler calls
`/process/jobs/reconcile` every five minutes. After a two-minute grace period it
compare-and-set claims missing dispatches, expired-running leases, overdue retry
waits, and incomplete terminal delivery. It redispatches with a
revision-qualified deterministic task ID. Work older than three hours
transitions atomically to failed before normal failure cleanup and notification
persistence run. Terminal records are retained
for operational review until an owner applies the AI Analytics retention
controls. That manual cleanup deletes terminal jobs in the selected age window
but preserves active work and terminal jobs whose delivery is still pending;
automatic terminal compaction remains disabled. If a retained job's referenced
input has already been deleted, reconciliation skips input-dependent
failure callbacks, resolves its pending notification, records the missing input
in diagnostics, and completes delivery
so the orphan is not retried indefinitely.

The Administrator AI analytics view shows each retained job's opaque ID and links
to a transferable JSON diagnostic. That projection includes bounded timing,
dispatch/recovery state, safe input entity references, checkpoint stage, and
AI-generation summaries correlated through the opaque telemetry ID. It excludes
parameters/feedback, checkpoint payloads, generated content, authorization data,
lease tokens, and provider/tool payloads.

Deferred provider requests use at most two SDK attempts before durable job
backoff owns recovery. AI quota failures use application-owned base backoff at
60 and 300 seconds plus up to 30 seconds of positive jitter, allowing two
deferred retries after the initial attempt. Other transient provider failures
retain 60, 180, and 600 second durable backoff and three retries. Exhausted
provider failures use the concise user message "The model is too busy right
now. Try again later." Organize separately checkpoints
`uploads_finalized`, `summaries_ready`, `plan_ready`, and `ready_to_apply`, so a
late form-submission completion failure does not repeat planning. Reports keep
the active job reference in process state; deleting a report tombstones the job
and deletes its queued deterministic Cloud Task before deleting report-owned
state.

The shared cohort covers report generation/revision, reviewed report execution,
page/task autofill, page generation, site export, file OCR, and file summary.
Ingress, scheduled task uncompletion, and cache maintenance retain their
specialized orchestration.

Reviewed report execution retains its own internal deferred-job record and
updates the report's inline running/complete/failed state, but its notification
policy is `none`: it neither creates nor completes an inbox notification. Ask,
Organize, and Create generation/revision jobs retain their normal final
notification, which is also the generic terminal email path for email-origin
reports.

AI reports may temporarily persist a JSON `upload_manifest` containing signed
direct-upload records. It is excluded from indexes and cleared after the
background Organize process has converted every record into an attached `File`.
The staged source remains available until that file and its manifest checkpoint
are saved, allowing a worker retry to repeat an interrupted copy. The report's
`input_files` relation remains the durable post-finalization state.

Email-origin reports use `origin: "email"` and an index-excluded
`inbound_manifest` containing only normalized subject/body, selected address,
requested/resolved workflow routing data, received timestamp, and safe
attachment display metadata. Provider IDs,
headers, and signed URLs remain outside the report. Email attachments are
ordinary `File` entities with a temporary `report_user` view relationship so
the submitting user can read report-only evidence without gaining edit or
placement rights; normal Page/Task relationships remain authoritative if a
reviewed Organize proposal later places a file.

## Entity Registry (`entities/__init__.py`)

The `Entities` singleton (`EntityRegistry`) is the central access point for all entity operations:

| Method | Description |
|---|---|
| `Entities.fetch(*identifiers, request=Fetch...)` | Fetch a graph to an explicit total depth, independent of whether roots are keys or typed entities. |
| `Entities.fetch_one(identifier, request=Fetch...)` | Singular explicit-depth fetch; returns the entity or `None`. |
| `Entities._load(*identifiers, related=...)` | Internal batch/attachment primitive used by the explicit-depth fetch API. |
| `Entities.save(*entities)` | Plan and execute entity upserts; auto-set timestamps, active state, and permissions. |
| `Entities.save_root(entity, property_mask=...)` | Persist one root, optionally with a Datastore property mask, with full index exclusions and without lifecycle, intent, or cache work. |
| `Entities.save_document_checkpoint(entity, advance_parent=False)` | Persist only collaborative-document assets/history and their typed history intents; optionally combine the lifecycle parent/list-owner advancement in the same masked plan. |
| `Entities.advance_document_parent(entity)` | Advance only the document parent and Page list-owner `modified` fields after a previously persisted checkpoint. |
| `Entities.delete(*entities)` | Plan and execute merged survivor repairs and cascade deletion. |
| `Entities.touch(*entities)` | Update only `modified`, then persist it with a property mask through the same exclusion-preserving boundary as `save_root`. |

Mutation plans are executed directly with
`lagniappe.core.mutations.execute_mutation(plan)`; the entity registry does not
expose a passthrough for this lower-level boundary.

`Entities._load()` is the low-level compatibility/batch primitive. It normalizes
entity-object inputs immediately and urlsafe/key string inputs into Datastore
keys for the first batch. Because string inputs are not typed until after that
first batch, `related=True` has slightly different depth depending on what was
passed in:

- Urlsafe/key string inputs: the first batch fetches the requested entities;
  the related pass fetches those entities' direct `related_keys`.
- Entity-object inputs: direct `related_keys` are known before the first batch,
  so they are fetched with the requested entities; the related pass then also
  fetches direct `related_keys` from those first-level related entities.
- `related=False` skips the post-fetch related pass. It does not remove
  already-known direct related keys from entity-object inputs.

After loading, `Entities._load()` calls `attach(key_map)` on each entity to wire
resolved relationships. Request routes must use the explicit fetch API instead
of relying on this identifier-dependent depth.

### Explicit fetch depth

High-fan-in request boundaries use `Fetch` instead of relying on the
identifier-sensitive meaning of `related`:

```python
from lagniappe.core.definitions import Fetch, FetchReason

roots = Entities.fetch(user_key, page_key, entity_key, request=Fetch.direct())
page = Entities.fetch_one(page, request=Fetch.direct())
task = Entities.fetch_one(
    task,
    request=Fetch.nested(
        because=FetchReason.TASK_SAVE_REQUIREMENTS,
    ),
)
```

Request authentication uses the first line as a fixed boundary: user, user
page, and requested entity are all roots, so all three receive one direct
relation level in the same bounded load. Routes that genuinely need another
level re-fetch the already-typed entity with a registered nested reason in the
handler. Task mutation routes, for example, load page and list-owner relations
before `Task.save()` recomputes their stored `requires` hashes; readonly task
routes do not need that save projection. The attached direct relations are
reused; only missing second-level keys require another database batch.

The depth is the total graph promised to the consumer:

| Request | Available graph | Additional relation batches for a typed root |
| --- | --- | --- |
| `Fetch.root()` | Root entities only | 0 |
| `Fetch.direct()` | Roots plus their direct relations | At most 1 |
| `Fetch.nested(because=...)` | Roots, direct relations, and relations of those direct relations | At most 2 |

Nested requests must use a registered `FetchReason`. `DEBUG_TRACING` records
the declared depth, reason, root/relation stage, key counts, and database-read
counts with the request endpoint. Root entities loaded in the same batch may
satisfy a stored relationship only when that complete relationship is present;
other stored relationships remain unloaded so strict checks cannot be masked.
Application callers use `fetch()` or `fetch_one()` and choose an explicit
`Fetch` depth; `_load()` is an internal implementation primitive.

`Entities.delete()` handles cascade deletion: deleting a Category deletes its Pages, which deletes their Tasks, Files, and Filters. Deleting a Project deletes its ModelTasks and orphaned Forms.

## Index System (`entities/index.py`)

Index classes provide paginated, permission-filtered list views for entity
types. They extend `Site`, a deliberately non-`Entity` base for site-level
objects with lazy properties and database access, and are used by index routes
to render table pages.

### Base Index

The `Index` base class provides:

- **Cursor-based pagination**: `cursor` (Datastore cursor for next page), `limit` (items per page, default 25)
- **User context**: `user` (defaults to `current_user`), used for permission filtering
- **Prefetch support**: `prefetch` URL set by routes for frontend prefetching, `append` URL for infinite-scroll loading
- **Table properties**: Each index defines `_get_properties()` returning a table configuration (column definitions, sort behavior)

### Index Types

| Class | Kind | Data Property | Permission Filtering |
|---|---|---|---|
| `TaskIndex` | task | `tasks` | Filters by user's page restrictions. If restricted, only shows tasks whose parent pages the user can access. |
| `TaskHistoryIndex` | task | table only | Supplies the task-history table configuration for an already loaded task. |
| `PageIndex` | page | `pages` | Filters by user's page restrictions. Shows only pages in allowed categories. |
| `FormIndex` | form | `forms` | Checks form restrictions. Loads associated categories and model tasks. |
| `UserIndex` | user | `users` | Filters by user restrictions. Also provides `groups` and `public_group` properties. |

### Query Pattern

Each index type's data property (e.g. `TaskIndex.tasks`) follows the same pattern:

1. Check user restrictions from `user.properties.restrictions`
2. If unrestricted (`False`): query Datastore directly with cursor pagination
3. If restricted: look up allowed entity hashes from the search cache, then query only those
4. Load results via `Entities.fetch(..., request=Fetch.direct())` to resolve direct relationships
5. Store cursor for next-page loading

Task pagination uses two already ordered Datastore streams: dated tasks are
ordered by ascending due date, followed by undated tasks ordered by descending
modification time. `Entities.fetch()` preserves the query-key order, so
`TaskIndex.tasks` does not apply a second in-memory sort to each page.

## Task Scheduling (`properties/task_scheduling.py`, `properties/task_dates.py`)

Tasks support three scheduling models for recurring work. The scheduling system uses `ProcessProperty` to store schedule configuration as JSON sections within the task's `schedule` process key.

Reviewed AI report task creation uses the same process sections. Its canonical
`create_task.data.schedule` is validated during proposal preparation and mapped
deterministically into `recurring`, `scheduled`, or `periodic` state during
execution; report execution never invokes the scheduling model.

### Schedule Property

The top-level `Schedule` property orchestrates the three scheduling types:

- `update(form_data)` -- routes form data to the active schedule type
- `schedule` -- returns the active schedule property (`Recurring`, `Scheduled`, or `Periodic`)
- `skipped` -- calculates how many scheduled occurrences were missed
- `set_next_due_date()` -- calculates and sets the next due date based on the active schedule
- `clear()` -- removes all scheduling data

### Recurring

Simple interval-based repetition. Stores `interval` (number) and `unit` (days/weeks/months/years). Next due date is calculated by adding the interval to the current due date.

### Scheduled

Calendar-based scheduling with four modes:

| Mode | Configuration | Example |
|---|---|---|
| `daily` | No additional config | Every day |
| `weekly` | `days` (list of weekday numbers 0-6) | Every Monday and Wednesday |
| `monthly` | AI-generated from natural language | "First Tuesday of every month" |
| `yearly` | AI-generated from natural language | "March 15th every year" |

For monthly and yearly modes, the user provides a natural language description. The AI generates structured schedule data (`day`, `ordinal`, `weekday`, `month`, `type`) which is stored in the process section. If generation fails, the error is stored and displayed.

### Periodic

AI-generated schedules from freeform descriptions. The user provides a prompt (e.g., "every two weeks on payday") and the AI generates `interval`, `unit`, and `description`. Uses the same prompt/generate pattern as Scheduled.

### Date Calculations (`task_dates.py`)

Task date properties:

| Property | Description |
|---|---|
| `Completed` | Boolean completion status. Stored separately from completion time. |
| `CompletedOn` | Datetime when task was completed. Stored as UTC, displayed in user timezone. |
| `DueDate` | Task due date. Stored as UTC, displayed in user timezone. Editable in table columns. |

Date calculation functions in `tools/dates.py`:

| Function | Description |
|---|---|
| `get_next_recurring_date(schedule)` | Adds interval to current due date |
| `get_next_scheduled_date(start, schedule)` | Finds next occurrence matching the schedule pattern |
| `get_next_periodic_date(start, schedule)` | Finds next occurrence for periodic schedules |
| `get_starting_due_date(task)` | Gets the base date for next-date calculations |
| `calculate_skipped_scheduled_tasks(task, schedule)` | Counts missed occurrences between last completion and now |
| `calculate_skipped_recurring_tasks(task, schedule)` | Same for recurring schedules |

### Task Completion Flow

When a task is completed and has a schedule:

1. `set_next_due_date()` calculates the next occurrence
2. A new task is created with the next due date (via Cloud Tasks in production)
3. The task stays active but is marked `completed=True` until the scheduled uncomplete step clears completion state

### Task Combination Flow

The task combine service operates on a task and one or more selected peers from
the same page. Peers are compatible only when their model-task keys are equal;
this means modeled tasks require the exact same model task, while unmodeled
tasks can combine only with other unmodeled tasks. The route and service also
require delete permission for every selected task.

The surviving task is the one with the newest `completed_on` when any selected
task has a completion timestamp. If none do, the newest `modified` task
survives; entity keys provide a deterministic final tie-break. Before deleting
the other tasks, the service creates history entries under the survivor for
each loser's current state and copies every existing loser history entry. These
snapshots retain the history schema's names, descriptions, completion metadata,
page links, form/schema version, submission, attachments, and assets. Stable
destination history keys make a retried migration idempotent.

TaskHistory rows are immutable snapshots. They retain the ordinary
`Entity.fingerprint` because generic entity rows and directly keyed GET routes
use it for DOM and ETag contracts, but their `modified` value is permanently
their creation time. The fingerprint therefore stays stable and deliberately
does not use `SubmitterMixin.fingerprint`, which would make an old snapshot
appear to change when the attached live Form advances to a later version.

## Property File Organization

Properties are organized by entity type and concern:

| Prefix | Contains |
|---|---|
| `common_*` | Shared properties (entity, assets, related) |
| `page_*` | Page-specific (assets, related) |
| `task_*` | Task-specific (dates, related, scheduling) |
| `file_*` | File-specific (assets, entity, ingress, options, related) |
| `user_*` | User-specific (entity, groups, permissions, related, restrictions) |
| `form_*` | Form field types (checkbox, inputs, links, select, special, submission, table, todo, textarea) |
| `base_*` | Base classes (asset, columns, db, filters, process, property, schema, submission) |
| Single files | `category.py`, `project.py`, `filter.py`, `home.py`, `index.py`, `schema.py` |
