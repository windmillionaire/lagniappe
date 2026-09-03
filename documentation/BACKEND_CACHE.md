# Backend Cache

Redis accelerates search, saved filters, notification state, deferred-operation
polling, collaborative documents, rate limits, and short-lived presence. It is
never the sole authority for entity content, permissions, notifications, or
background jobs.

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
| `requires` | Permission tags. |
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

Saved filters use a separate Redis JSON projection keyed by parent and access
scope. See [BACKEND_FILTERS.md](BACKEND_FILTERS.md).

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
