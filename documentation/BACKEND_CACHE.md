# Backend Cache

Redis accelerates search, saved filters, notification state, deferred-operation
polling, collaborative documents, rate limits, and short-lived presence. It is
never the sole authority for entity content, permissions, notifications, or
background jobs.

## Filter result responses

Filter previews and saved-filter runs use normal permission-scoped ETags.
Saving a changed Page/Form restriction, changing a Page's attached Form, or
changing a Form schema advances the Tasks collection fingerprint with the
source save. This index invalidation does not load descendants. Asynchronous
restriction reconciliation updates their search and detail projections.

Project filter result ETags include the Tasks fingerprint, so a permission
change cannot return a stale 304. Mounted Project filter pages watch both their
Filter entity (whose revision includes its Project) and the Tasks channel.
Category filters watch their Filter/Category revision. Viewer authorization
participates in both kinds of filtered result revision.

Collection refresh loads the parent revision and queries membership only when
that revision or viewer authorization changed. With an unchanged parent, it
compares the supplied row fingerprints against cached details without loading
the collection's entities. Changed rows load for authorization and rendering.
Restrictions participate in the row fingerprint,
so inherited permission changes do not require rewriting descendant content or
its durable modification timestamp. Only changed/new authorized rows are
rendered; rows that have become forbidden are removed.

## Initialization and namespace

`tools/cache/core.py` creates one Redis client and the RediSearch index. TLS
uses the shared verified connection options from configuration. The JSON cache
reuses the same client.

All cache cleanup is namespace-aware. Test environments delete only their
configured prefix. A full Redis flush is reserved for the unprefixed runtime
rebuild path.

## Search and entity details

Entity mutations call `entity.to_cache` after durable commit. Search hashes
store searchable fields plus pointers to compact details:

| Field | Role |
| --- | --- |
| `name` | Highest weighted text field. |
| `desc` | Description text. |
| `doc` | Collaborative document text. |
| `values` | Form submission text. |
| `kind`, `type` | Tag filters. |
| `requires` | View-access ancestry tags; task-owned Files include the Task hash. |
| `restricted_to_page` | Local Page group alternatives. |
| `restricted_to_page_form` | Page Form group alternatives. |
| `restricted_to_task_form` | Task Form group alternatives. |
| `details_key`, `parent_key` | Pointers to current display details. |

`details.py::get_details_by_hash()` hydrates current detail and parent blocks.
Search results therefore do not carry a second embedded copy of display data.
`query.py` applies the viewer's `requires` tags, boosts exact name coverage,
and hydrates results only after the permission-filtered search.

An entity may retain its hash-details pointer while opting out of its searchable
row. Report-owned Files use this boundary before execution: exact report and
contract references continue to resolve, but unattached evidence does not
appear in website or AI workspace search. Attaching the File restores its
search row through the ordinary entity mutation refresh.

The public AI `search_entities` exact-name mode uses the separate
`exact_name_search()` cache query. It is candidate-bounded, may add a parent
hash through the existing `requires` index, and confirms normalized full-name
equality after hydration. Do not fold this behavior into `search()`: the main
full-text query, ranking, snippets, and website callers have a different
contract.

External AI keyword discovery uses `candidate_search()` without changing that
shared full-text query. It retrieves a bounded strict candidate pool and, for
two through twelve significant terms, performs at most one grouped OR query
when fewer than three strict candidates remain (or the requested limit, if
smaller). A normalized exact-name hit stops relaxation. Both queries retain
the same caller/group, kind, and optional parent scope. Candidate pools are
capped at 100 records per query; the AI response limit remains 25.

The merged result ranks normalized exact names first, then known all-term
matches, name-prefix coverage, and Redis relevance. It uses cached detail and
parent hydration only, including stale-row removal; it does not fetch full
entities to repeat visibility checks. Internal Gemini search, the automatic
Organize retrieval prepass, browser search, and execution-time Page-name
fallback retain their existing matching behavior.

Saved filters use a separate Redis JSON projection keyed by parent and access
scope. See [BACKEND_FILTERS.md](BACKEND_FILTERS.md).

## Entity revisions and restriction reconciliation

Cached details include `modified` (the MD5 of the durable ISO timestamp), the
calculated `fingerprint`, effective `restricted_to` when nonempty, and
`form_version` for Forms, Pages, and Tasks. A Form stores its own version; a
Page/Task stores its attached Form's version or an empty string. Datastore
modification timestamps and browser timestamp fields remain datetimes/ISO strings.

The shared fingerprint helper hashes `base:form_version:restrictions` for
Pages/Tasks and `base:restrictions` for Files. `restrictions` is a compact,
canonical JSON mapping with nonempty `page`, `page_form`, and `task_form` group
arrays. Groups are sorted and unique within each source; the source boundaries
remain part of the fingerprint. TaskHistory retains its immutable base
fingerprint. Cached `id` is the
entity's key. A user's Page has display kind `user`; `identify_entity()` resolves
it as a Page. Public hydration removes the internal relation pointers.

Pages combine their own groups and Page Form groups; Tasks add Task Form groups.
Files inherit their primary Task or Page's complete rule. A viewer must match
at least one group in every nonempty source. Redis indexes the three source
arrays in separate TAG fields, with a missing field representing an unrestricted
source. Searches AND three missing-or-membership clauses using the viewer's
actual groups. `Restriction.BELONGS_TO_ALL` bypasses the group predicate for
administrators; ordinary ungrouped users send `Restriction.BELONGS_TO_NONE` and
match only unrestricted records. `Restriction.UNRESTRICTED` omits the independent
required-access predicate.

After a Form/Page/Task restriction source changes, the save writes its source
projection and dispatches `process/reconcile-restrictions`. Form schema changes
also dispatch, because attached entity fingerprints include the schema version.
The task carries a source key, the Category/Project owner keys already resolved
during the save, and a continuation cursor/offset. It rereads current source
state. Matching Page/Task instances load at root depth in batches of 100. Local
Page restrictions remain independent of the Form's restrictions.
Each root batch also contributes list-owner keys from the stored Page `model`
and `categories` fields, or Task `project` field. This reads no owner relations.
The worker deduplicates these keys with any owner hints from the source save
and carries their union through both instance-cursor and descendant-offset
continuations. Completion therefore includes the actual instance collections
even when the source save supplied no owner hints.
Categories and task templates reuse the edited Form during the save to refresh
their schema-dependent projections. They do not inherit its restrictions.
Indexed descendants are found with ORed root hashes in `requires`. Task roots
are included explicitly because a Task does not require its own hash.

For a Form change, the worker replaces or removes that Form's source list on
each target's cached details and search row. A Page change replaces the Page
and Page Form sources; a Task change replaces all three sources on its Files.
Other source lists remain intact, including when one source is administrator-only.
Only Pages/Tasks directly using the changed Form receive its new `form_version`;
a descendant Task retains its own Task Form version, and Files have none.
The worker recalculates fingerprints from the resulting source mapping, own
Form version, and cached base modified digest. It reads only the targeted cache
records, without loading cached ancestor records to reconstruct restrictions.
Reconciliation operates on available cache records; rebuilding the cache is a
separate maintenance operation.

After writing, the worker loads the batch's entity keys nested and compares their
resolved fingerprints with the current cached fingerprints. This detects both
direct saves and inherited permission changes. Mismatches rebuild only those
entities' cache projections; deleted entities have their cached rows removed.
Repairs are verified again, with continued changes returning the job for retry
after three verification attempts. A changed source restarts the scan. These
updates provide eventual consistency across Datastore and Redis. Inherited
restrictions do not require descendant Datastore writes; local Page/Form group
hashes remain the durable sources.

Stable `details_key` ordering keeps permission field updates from shifting rows
between batches. Continuations carry the Pages/Tasks collection revision;
a concurrent move, creation, or deletion restarts the scan so offset shifts cannot
skip remaining records. Once all batches complete, the worker advances the
Tasks channel again and touches the collected Category/Project list owners,
loading the unique keys directly without repeating an owner-discovery query.
This completion signal prompts another browser refresh after descendant
projections are ready. Search reflects restriction changes
after reconciliation finishes; rich entity access uses current durable permissions.

Cache/dispatch failures are returned as failed saves. A Redis pending marker
survives source replacement so an unchanged retry can redispatch. Worker errors
return 503 for Cloud Tasks retry. Local environments with Cloud Tasks disabled
execute the same worker inline.

## Notification state

Notification rows and the per-user aggregate are durable in Datastore. Redis
stores a reconstructable projection containing:

- schema version and generation;
- projection and message revisions;
- ordinary and unread-message counts; and
- ordinary Notification key membership.

The public badge count is the sum of the durable counters. Bodies and message
history are never stored in this projection.

Cold population watches both the projection and a separate mutation epoch,
queries Notification keys, and publishes only if neither key changed during
the read. A committed create, update, delete, or clear publishes one
post-commit effect. If the projection is absent, the effect advances only the
epoch and lets the next seed rebuild membership.

`/l/ping` peeks at warm Redis state without loading Flask-Login. A miss or
Redis error leaves the health result intact; the browser requests a seed
through `/l/poll`. Both keys expire after 30 minutes of inactivity.

## Deferred-operation hints

The durable `DeferredJob` is authoritative. Redis keeps only schema,
`status_revision`, terminal state, and the last durable verification time for
each watched job. A revision-checked update prevents a delayed publisher from
overwriting newer status.

An Owner poll may skip the job read when its cursor matches a projection
verified within the last minute. Misses, mismatches, and due verification load
only the job keys that browser tracks and repair Redis. Non-owner status checks
always use the durable authorization path. Projection keys expire after 30
minutes.

## Collaborative documents

Documents are the high-churn Redis-owned working-state exception. One isolated
document key stores a generation, monotonic revision, compact checkpoint,
bounded deltas, author projections, and durable asset fingerprint. Presence
uses separate expiring document and client keys.

Redis loss starts a new generation from the durable document asset. Accepted
checkpoints persist the asset and history through the entity mutation layer.
See [SYNC_DOCUMENTS.md](SYNC_DOCUMENTS.md).

## Keys and ownership

`tools/cache/keys.py` defines core, search, and sync key families. Keep cache
code separated by projection:

- `add.py` writes entity search/details and parent filter indexes;
- `details.py` hydrates compact entity references;
- `query.py` owns search;
- `notification_state.py` owns the notification wire codec;
- `notifications.py` owns Redis notification transactions;
- `operations.py` owns deferred-status hints; and
- `documents.py` owns document working state and presence.

Ingress state is durable and is not represented as Redis authority.

## Public discovery

`public_discovery.py` owns two rebuildable projections under one expiring
revision epoch. The JSON public-directory catalog has a 15-minute TTL; sitemap
XML has a one-hour TTL. A warm `/public/` request performs one Redis read and
does not read Datastore. On a miss, the directory's durable seed is one live
settings read, the public-Page query, and a direct relation batch for the
explicitly selected Category.

The cached catalog is deliberately privacy-bounded: public IDs, relative
paths, public titles and descriptions, and explicitly published Category
labels only. It never includes documents, internal descriptions, photos, or
unselected Category labels. The sitemap derives Page URLs from this same
catalog so the two discovery surfaces cannot disagree about eligibility.

Public Page saves or deletes, Category saves or deletes, and the live site
discovery switch invalidate both outputs after the durable write. The common
epoch is watched during publication, preventing an older build from winning a
race with invalidation. Redis errors fall back to a single durable build and
never roll back a committed mutation. If invalidation itself cannot reach
Redis, an old directory can survive only until its 15-minute TTL; public Page
routes still enforce current visibility directly. The single sitemap fails
closed above 50,000 URLs rather than silently truncating; sharding is the
intended expansion point.

## Design rules

- Every projection must name its durable seed and race contract.
- Redis failure must degrade to a durable read or a rebuild, never authorize a
  request or roll back a committed mutation.
- Keep cache values privacy-bounded; do not duplicate full job inputs,
  notification bodies, or entity documents into convenience hashes.
- Publish after durable commit.
- Use optimistic transactions when a seed can race with mutation.
- Give short-lived projections explicit expiration and bounded verification.
