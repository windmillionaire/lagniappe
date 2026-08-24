# Backend Persistence

`lagniappe/core/tools/database/` is the only raw Datastore and Cloud Storage
boundary used by application services. Entity mutation planning sits above it;
installer-only backup and restore operations sit outside the runtime package.

## Runtime data services

`DataServices` owns clients for the canonical `(default)` Datastore database
and the three runtime Storage buckets. All clients receive the same
project-bound runtime credential. Named Datastore databases are temporary
operator resources used during archive and restore workflows and are never
selected through runtime configuration.

`KINDS` maps domain types to prefixed Datastore kinds:

| Kind | Main contents |
| --- | --- |
| `instances` | Pages and Tasks. |
| `models` | Projects, Categories, Forms, ModelTasks, and Groups. |
| `users` | Users. |
| `files` | Files and Ingress records. |
| `filters` | Saved Filters. |
| `history` | Task, form, and document history. |
| `activity` | Notes and Notifications. |
| `analytics`, `ai_observability` | Owner analytics and bounded AI summaries. |
| `site` | Singleton settings, fingerprints, controls, and ledgers. |
| `jobs`, `job_locks` | Durable background work and target locks. |

## Keys, reads, and writes

`database/get.py` normalizes a Datastore Key, typed entity, or URL-safe key.
Runtime key decoding preserves its stored partition. Setup-owned archive code
uses separate typed portable identities.

Broadly shared operations are exposed through the `database` façade:

| Operation | Purpose |
| --- | --- |
| `entity(...)`, `entities(...)`, `reserved(...)` | Raw singular, batch, and reserved-row reads. |
| `create_key(...)`, `create_named_key(...)` | Random or deterministic keys. |
| `save_mutations(...)` | Complete and property-masked writes. |
| `save_raw(...)` | Migration writes without entity hooks. |
| `delete_entities(...)` | Durable typed deletes and fingerprint effects. |
| `delete_blobs(...)` | Post-commit Storage cleanup. |
| `initialize()` | Seed reserved rows and report whether the database was empty. |

Domain-specific transaction modules stay concrete:

- `deferred_jobs.py` owns job claims, locks, lifecycle CAS, and Scheduler
  control state;
- `ingress.py` owns cursor-checked row commits;
- `messaging.py`, `mentions.py`, and `notifications.py` own communication
  transactions;
- `notification_email.py` owns delivery rows and leases;
- `ai_email.py` owns inbound event claims;
- `site.py` owns singleton site settings; and
- `analytics.py` owns analytics and AI-observability rows.

Shared bounded Datastore contention retry lives in `transactions.py`. A retry
must repeat the complete read/check/write transaction body.

## Query contract

`database/filter.py` wraps Datastore queries with `eq`, `any_of`, `all_of`, and
compound filters. Query modules return keys or raw rows to their owning service;
permission checks and typed relation hydration remain above the persistence
layer.

`Filter.requires([])` is an explicit deny-all, not an absent filter. Denied
branches compose as false inside OR expressions, while a denied top-level/AND
filter dominates the query. Every `Query` terminal method returns its typed
empty result without constructing a Datastore query when the filter denies all.

Keep queries bounded and ordered. When a browser list uses a cursor, preserve
provider order through `Entities.fetch()` instead of applying a second sort
after hydration.

## Storage assets

`database/assets.py` addresses buckets by visibility:

| Bucket | Contents |
| --- | --- |
| `public` | Site images and public entity assets. |
| `private` | User uploads and collaborative document assets. |
| `history` | Document history assets. |

It provides upload, ranged download, metadata, text read/write, provider-side
copy, prefix listing, signed URLs, deletion, and site-image upload. Private
signed URLs use IAM Credentials `signBlob`; the runtime stores no service
account key.

Callers that materialize bytes must declare a `FileConsumer`. Direct-upload
size is checked from Cloud Storage metadata before download. Provider-side copy
stays unbounded because bytes do not enter the application process. See
[BACKEND_TOOLS.md](BACKEND_TOOLS.md#file-tools).

Blob deletion is a post-commit effect. Never delete an asset before the
Datastore mutation that removes or replaces its descriptor commits.

## Data migrations

`database/migrations.py` executes the registered migration catalog through the
Administrator **Apply Updates** action. It queries raw rows, transforms copies,
writes validated changes in bounded chunks, and records a durable per-entry
ledger plus a control lease. Startup baselines the catalog only when it has
just seeded an empty database. See [DATA_MIGRATIONS.md](DATA_MIGRATIONS.md).

## Runtime versus operator data paths

Runtime code reads and writes only `(default)` and the three application
buckets. Backup, recovery-set materialization, portable archives, and restore
are privileged installer workflows using the saved human operator identity and
the separate recovery bucket. See
[INFRA_DATA_LIFECYCLE.md](INFRA_DATA_LIFECYCLE.md).

## Change checklist

- Put raw provider access in `tools/database/`, not routes or properties.
- Keep transaction reads and writes within one repeatable body.
- Preserve entity mutation and post-commit boundaries.
- Declare byte consumers before materializing files.
- Update indexes and focused unit tests for new query shapes.
- Use raw migration writes only inside the migration framework.
