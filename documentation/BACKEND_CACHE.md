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

## Public sitemap

`sitemap.py` caches generated XML for one hour under `Keys.SITEMAP`. The
Datastore public-page query is the durable seed. A separate expiring epoch is
watched while XML is generated, so a visibility or per-page indexing mutation
cannot publish a stale build after its post-commit invalidation.

Page publication, page deletion, per-page indexing changes, and the live site
discovery switch invalidate the sitemap. Metadata text and document edits do
not, because the v1 sitemap contains only canonical URLs. Redis errors fall
back to direct generation and never roll back a committed page mutation. The
single sitemap fails closed above 50,000 URLs rather than silently truncating;
sharding is the intended expansion point.

## Design rules

- Every projection must name its durable seed and race contract.
- Redis failure must degrade to a durable read or a rebuild, never authorize a
  request or roll back a committed mutation.
- Keep cache values privacy-bounded; do not duplicate full job inputs,
  notification bodies, or entity documents into convenience hashes.
- Publish after durable commit.
- Use optimistic transactions when a seed can race with mutation.
- Give short-lived projections explicit expiration and bounded verification.
