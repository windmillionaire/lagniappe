# Durable Data Migration Workflow

Lagniappe installations may skip many releases. Data migrations therefore form
an append-only compatibility chain: every shipped migration has a stable
identity and release version, and every site keeps its completion state across
later builds.

The normal release-update flow is:

1. Run the release's documented upgrade workflow—normally
   `./setup.sh upgrade` for an unmodified installation—or merge the release
   into a maintained fork and run `./setup.sh update`, then deploy.
2. Sign in as the site owner and open **Admin → Site Settings → Maintenance**.
3. Click **Apply Updates**. Pending migrations run in catalog order.
4. Resolve any reported failure using the linked form or page, then retry.
5. When every migration is complete, click **Refresh Cache**.
6. Smoke-test the features affected by the migrations.

Setup and startup never run transforms automatically. A new empty installation
is baselined automatically because it already writes the current data shape.

## Durable model

`lagniappe/core/tools/database/migrations.py` contains `MIGRATION_CATALOG`, an
ordered tuple of immutable `MigrationDefinition` values. Each definition has:

- a strictly increasing `sequence`;
- a globally stable `id`;
- the application version in which it was `introduced_in`;
- an operator-facing `label`;
- an idempotent `runner`.

The catalog is append-only for the application's supported upgrade history.
Never reuse an ID, change its sequence or introduced version, or replace its
meaning after release. Add a new migration for a follow-up repair. Sites that
upgrade late will run all incomplete entries in sequence; entries completed by
an older build remain complete.

Each catalog entry has a separate Datastore record:

```text
site/data-migration:<migration-id>
```

The record repeats the immutable catalog identity, records `pending` through
the absence of a record, or persists `running`, `failed`, or `complete`, and
stores the completion version, build, source, and timestamp. Completion is
sticky: deploying a newer build does not make a completed migration pending.
The latest five attempts and at most 25 repair and error details per attempt are
retained; the completion summary remains after attempt history rolls over.

`site/data-migrations-control` is the execution lease. It prevents two owner
requests from running migrations concurrently and is renewed after each chunk.
A stale `running` record is displayed as interrupted. The next owner retry
records that interrupted attempt and safely resumes from the first incomplete
catalog entry.

The Site Settings status is catalog-wide:

- `current`: every entry is complete; cache refresh is allowed;
- `pending`: one or more entries have not run, or are blocked by an earlier
  incomplete entry;
- `running`: another request owns the live lease;
- `failed`: the first incomplete entry failed or was interrupted;
- `audit-error`: a stored ledger identity or payload is inconsistent with the
  checked-in catalog and must be repaired deliberately.

Completed release groups are collapsed in Site Settings. Incomplete groups are
expanded, with attempts, successful repairs, errors, and entity links shown
under the relevant migration.

## When to add a migration

Use a data migration when a release changes the canonical shape or meaning of
stored data, including:

- renaming, splitting, or nesting persisted properties;
- normalizing an old value type;
- adding derived canonical data required by new code;
- repairing a known historical write shape across active, inactive, or history
  rows.

Do not add one for frontend-only changes, cache-only projections, or runtime
defaults that are safe to compute lazily. **Refresh Cache** rebuilds derived
Redis/search state; it does not canonicalize Datastore.

## Authoring a migration

### 1. Choose immutable identity

Append one `MigrationDefinition` to `MIGRATION_CATALOG`. Use the next sequence,
a stable descriptive ID, and the exact application version that first ships
the migration. Existing definitions must remain byte-for-byte equivalent in
identity and order.

Put substantial transform logic in a versioned module under
`lagniappe/core/tools/database/migration_steps/`. Keeping shipped transforms
separate makes the supported upgrade chain reviewable.

### 2. Write an idempotent transform

A transform should:

- accept one raw Datastore entity or record;
- validate every old and canonical value it relies on;
- preserve unknown and unrelated fields;
- prefer an already-valid canonical value over a legacy value;
- produce the same result when run repeatedly;
- return whether it changed the candidate record;
- report deterministic cleanup through `MigrationChange(..., repairs=...)`;
- raise `MigrationDataError` only when a safe deterministic result cannot be
  chosen.

Invalid legacy values that have an unambiguous outcome should be fixed or
removed and reported as successful repairs. Do not fail merely because data
was written by an old version. Fail when guessing would lose meaning or damage
unrelated data.

The framework clones rows before transformation and writes only validated
changed candidates. Do not construct typed entities from malformed legacy
properties, and do not invoke normal save hooks unless their timestamps,
cascades, and relationship effects are intentionally part of the migration.

If a migration reads Cloud Storage, treat missing objects or invalid metadata
as entity failures. Do not mutate blobs without an explicit backup and
recovery design.

### 3. Write and register the runner

The runner receives a `MigrationContext` with the raw query factory, writer,
Datastore client, and lease heartbeat. It must return the result envelope for
its registered ID.

Use `scan_kind` where possible. Query raw rows, filter narrowly by kind and
`type`, include inactive/history records when their stored shape is affected,
and keep writes bounded by `MIGRATION_CHUNK_SIZE`. Batch relationship reads
instead of loading one related entity per row.

Entity-specific runners must provide a reference callback so repairs and
errors include a link to the relevant form, page, file, or settings surface.
Internal failures without an entity surface should use a clear stable key and
actionable message.

One failed row does not prevent the runner from examining unrelated rows in
that migration. At the catalog level, however, any failure checkpoints that
migration as failed and stops later migrations. Retrying starts at that failed
entry; previously completed entries are never rerun.

### 4. Preserve rolling-upgrade safety

The deployed application must be able to read both old and new shapes while an
owner applies updates. Retrying after a partial write must be safe, and rollback
must have a forward-recovery or conversion plan. Retain compatibility readers
for any row that may not have migrated yet.

If a transform cannot meet those constraints in one deployed version, redesign
it. Do not make correctness depend on a second verification run or a second
deployment.

### 5. Test the catalog entry

At minimum, cover:

- representative old data becoming canonical;
- already-canonical data remaining unchanged;
- precedence when old and canonical properties coexist;
- deterministic invalid values becoming successful, linked repairs;
- unrecoverable data failing without mutating its original row;
- idempotence on a second transform call;
- the runner finding all intended kinds, types, and inactive/history rows;
- ordered checkpointing, fail-stop behavior, and retry resumption;
- completion remaining current under a later application version/build;
- fresh-install baselining when the new migration ships;
- bounded attempt/error history and an actionable reference for failures.

Use focused tests under `testing/tests_unit/`. Add route or frontend coverage
when the response envelope or Site Settings presentation changes. After adding
or renaming source symbols, run:

```bash
venv/bin/python run.py traceability --changed --check
```

## Fresh installations

At startup, database initialization determines whether it just seeded a truly
empty database. Only in that case, `initialize_fresh_install()` records every
bundled catalog entry as complete with source `fresh-install`; no transform is
run. Existing sites, including sites with partial or failed ledgers, are never
baselined.

This behavior must be covered whenever startup seeding or the definition of an
empty installation changes. A fresh site should show all bundled releases as
complete, while an existing site upgrading from an older release should show
new catalog entries as pending.

## Failure recovery and operations

`POST /l/site-update` returns HTTP 200 only when the final catalog status is
`current`; pending, running, failed, interrupted, or audit-error results return
HTTP 409. A second click during a live run observes the lease and does not start
a concurrent runner.

For deterministic repairs, Site Settings explains what was removed or fixed
and keeps the migration successful. For failures, repair the linked entity or
the migration implementation, deploy the correction if needed, and click
**Apply Updates** again. Never edit immutable ledger identity fields to bypass
a migration. An `audit-error` requires inspecting the stored record and catalog
before making an explicit correction.

**Refresh Cache** is disabled in the UI and rejected by the route until the
catalog is current. This prevents derived projections from being rebuilt from a
mixture of old and new canonical data.

Release notes should say:

> After upgrading and deploying, open Admin → Site Settings → Maintenance,
> click Apply Updates, resolve any linked failures, and then click Refresh
> Cache once all updates are current.

## Retaining migration history

Do not remove a catalog entry merely because most installations have completed
it. A downloadable installation may upgrade years later, so the migration code
is part of the supported upgrade path.

An entry may be retired only when the project defines and enforces a minimum
supported source version newer than that entry, and provides a separate bridge
for older installations. Even then, leave durable site completion records in
Datastore unless a deliberate ledger-schema migration replaces them. Never
delete historical records as routine release cleanup.
