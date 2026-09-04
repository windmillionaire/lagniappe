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
| `agent_api_credentials` | One expiring, digest-only external-agent credential per user. |
| `agent_api_plan_operation_claims` | Shared per-report fence keys for leased API Plan transitions and one-shot browser mutations. |

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

`agent_api.py` owns transactional bearer-key rotation and revocation, plus the
shared per-report Plan-operation fence. Its stable opaque credential id supports
lookup without exposing the user's key; the credential row never stores the
shown-once bearer secret. API create-upload, finalize-upload, and submit claims
contain only an operation id, phase, random fencing token, and expiry. Each API
operation re-reads the authoritative report after acquiring its claim. Every
report/File checkpoint compares the pre-mutation report snapshot and verifies
the exact claim token in the same Datastore transaction that writes the prepared
entity mutations, so a lease takeover cannot commit a stale report.

Browser mutations of an API-origin report use the same claim key as a one-shot
fence without retaining a browser lease. Skip, execution start, every undo
checkpoint, execution-failure persistence, terminal execution cleanup, and
delete compare the raw Report snapshot, reject an active valid API claim, and
delete even an absent or expired claim key in the transaction that commits
their entity writes or deletes. That claim-key mutation conflicts with a
simultaneous API claimant, while the Report compare-and-set catches an API
operation that completed and released its claim first. Delete also rejects a
report with a deferred execution or `undoing` status; it does not cancel an
active queued execution. An eligible guarded delete includes report-only File
entity deletion, while temporary-upload and other blob/cache cleanup remain
post-commit effects.

Storage session creation and blob copying necessarily remain outside Datastore.
The File key is deterministic per upload batch and record, but each finalization
owner copies into an attempt-unique destination path derived from its internal
claim nonce. The provider copy requires the exact temporary-source generation
and a previously absent destination. As soon as the copy succeeds, its path and
generation are registered on the upload attempt before the content-type metadata
patch, which is conditional on that same generation. The path and generation
are then stored in the File checkpoint, and the temporary source remains until
that fenced checkpoint commits. A definitely uncommitted outcome conditionally
deletes only the copied generation; a generation mismatch preserves a
replacement. An ambiguous checkpoint outcome retains the copy for later
reconciliation rather than risking deletion of committed data.

Temporary-source deletion is likewise generation-conditional and treats an
already absent object as success. Finalization records the exact source
generation it verified and copied before checkpointing. If deletion fails after
the File/Report checkpoint, the completed upload-manifest entry remains durable
and finalization fails. A retry uses that completed entry to repeat the
idempotent source cleanup without copying or checkpointing the File again; the
manifest is cleared only after all completed sources have been cleaned. Report
and terminal-job cleanup also retry every valid manifest source, including a
completed entry left by an earlier cleanup failure.

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

Blob deletion is normally a post-commit effect. Never delete an asset before the
Datastore mutation that removes or replaces its descriptor commits. The narrow
pre-commit exception is cleanup of a definitely uncommitted upload-finalization
attempt, and that deletion must name the exact attempt-unique path and generation.
Temporary upload sources are instead deleted after their File/Report checkpoint,
using a generation precondition and idempotent already-absent handling.

## Data migrations

`database/migrations.py` executes the registered migration catalog through the
Administrator **Apply Updates** action. It queries raw rows, transforms copies,
writes validated changes in bounded chunks, and records a durable per-entry
ledger plus a control lease. Startup baselines the catalog only when it has
just seeded an empty database. See [DATA_MIGRATIONS.md](DATA_MIGRATIONS.md).

## Runtime versus operator data paths

Runtime code reads and writes only `(default)` and the three application
buckets. Manual-backup creation, automatic-backup preparation, portable
archives, and restore are privileged installer workflows using the saved human
operator identity and the separate recovery bucket. See
[INFRA_DATA_LIFECYCLE.md](INFRA_DATA_LIFECYCLE.md).

## Change checklist

- Put raw provider access in `tools/database/`, not routes or properties.
- Keep transaction reads and writes within one repeatable body.
- Preserve entity mutation and post-commit boundaries.
- Declare byte consumers before materializing files.
- Update indexes and focused unit tests for new query shapes.
- Use raw migration writes only inside the migration framework.
