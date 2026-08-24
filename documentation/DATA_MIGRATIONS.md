# Durable Data Migrations

Data migrations turn persisted source shapes into the current canonical shape.
They are explicit operator actions: setup and application startup never run
transforms automatically.

Implementation lives in
`lagniappe/core/tools/database/migrations.py` and
`lagniappe/core/tools/database/migration_steps/`. The owner-facing controls are
under **Admin → Site Settings → Maintenance**.

## Operator workflow

After deploying a release that includes migrations:

1. Sign in as an application Administrator.
2. Open **Admin → Site Settings → Maintenance**.
3. Click **Apply Updates**.
4. Resolve any linked failure and retry.
5. Click **Refresh Cache** after every migration is current.
6. Smoke-test the affected features.

**Refresh Cache** rebuilds derived Redis and search state. It does not transform
Datastore records, and the route rejects the request until migrations are
current.

## Catalog and ledger

`MIGRATION_CATALOG` is an ordered tuple of immutable `MigrationDefinition`
values. Each entry has:

- a strictly increasing `sequence`;
- a stable `id`;
- the release in `introduced_in`;
- an operator-facing `label`; and
- an idempotent `runner`.

Append new work to the catalog. Once an entry ships, do not reuse its ID,
change its sequence or release, or redefine its purpose. Follow-up corrections
belong in a new entry so every installation sees the same ordered catalog.

Each entry has a Datastore ledger record:

```text
site/data-migration:<migration-id>
```

The record stores catalog identity, execution state, completion version and
build, timestamps, and bounded attempt details. Absence means pending;
persisted states are `running`, `failed`, and `complete`. Completion remains
sticky across application releases.

`site/data-migrations-control` is the renewable execution lease. It prevents
concurrent owner requests. A stale `running` entry is presented as interrupted;
the next retry records that attempt and resumes at the first incomplete entry.

Site Settings summarizes the catalog as:

- `current`: every entry is complete;
- `pending`: at least one entry has not run or is blocked by an earlier entry;
- `running`: another request owns the active lease;
- `failed`: the first incomplete entry failed or was interrupted; or
- `audit-error`: stored ledger identity or payload conflicts with the catalog.

Completed release groups are collapsed. Incomplete groups show attempts,
repairs, errors, and links to the affected application surface.

## When a migration is required

Add a migration when a release changes the stored shape or meaning of durable
data, such as:

- renaming, splitting, or nesting persisted properties;
- normalizing a source value type;
- materializing canonical data required by current code; or
- repairing a known source shape across active, inactive, or history records.

Do not add one for frontend-only changes, cache projections, or defaults that
the runtime can compute safely.

## Authoring a migration

### Define stable identity

Append the next `MigrationDefinition`. Put substantial transforms in a named
module under `migration_steps/`; the catalog should remain easy to scan.

### Make the transform deterministic

A transform should:

- accept one raw Datastore record;
- validate the source and canonical values it reads;
- preserve unrelated and unknown fields;
- prefer an already-valid canonical value;
- return the same result on repeated runs;
- report whether the candidate changed; and
- describe deterministic cleanup with `MigrationChange(..., repairs=...)`.

Raise `MigrationDataError` only when choosing a result would lose meaning or
damage unrelated data. Unambiguous invalid values should be corrected or
removed and reported as successful repairs.

The framework clones records and writes only validated changed candidates. Do
not construct typed entities from malformed source properties or call ordinary
save hooks unless their timestamps, cascades, and relation effects are part of
the migration design. Cloud Storage reads must treat missing objects and invalid
metadata as entity failures; blob mutation requires its own backup and recovery
plan.

### Use bounded runners

The runner receives a `MigrationContext` containing the raw query factory,
writer, Datastore client, and lease heartbeat. Prefer `scan_kind`, filter by
kind and `type`, include inactive and history rows when relevant, and keep
writes within `MIGRATION_CHUNK_SIZE`. Batch relation reads instead of fetching
one related entity per record.

Entity-specific runners provide a reference callback so every repair and error
can link to a form, page, file, or settings surface. Internal failures use a
stable key and an actionable message.

A runner may continue examining unrelated records after one record fails. The
catalog itself is fail-stop: a failed entry is checkpointed, later entries do
not run, and a retry resumes at that entry.

### Design for an in-progress deployment

Application reads must remain correct before, during, and after the operator
applies updates. Partial execution and retry must be safe, and rollback needs a
forward conversion plan. If one deployment cannot meet those constraints,
redesign the data change.

## Required tests

Cover at least:

- representative source data becoming canonical;
- canonical data remaining unchanged;
- precedence when both shapes are present;
- deterministic invalid values becoming linked repairs;
- ambiguous data failing without mutating its record;
- idempotence on a second transform call;
- discovery of all intended kinds, types, inactive rows, and history rows;
- ordered checkpointing, fail-stop behavior, and retry;
- completion remaining current under a later build;
- fresh-install baselining; and
- bounded attempt details with actionable references.

Use focused unit tests and add route or frontend coverage when the response
envelope or Maintenance UI changes. Follow
[TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md), then run:

```bash
venv/bin/python run.py traceability --changed --check
```

## Fresh installations

Database initialization detects a newly seeded empty database.
`initialize_fresh_install()` then records every bundled catalog entry as
complete with source `fresh-install`; it does not execute transforms. Any site
with existing data or ledger state follows the normal pending workflow.

## Failure recovery

`POST /l/site-update` returns `200` only when the final catalog state is
`current`. Pending, running, failed, interrupted, and audit-error results return
`409`; a second request during a live run observes the lease rather than
starting another runner.

For a record failure, repair the linked entity or correct the migration,
deploy if necessary, and apply updates again. Never edit immutable ledger
identity fields to bypass work. Resolve an `audit-error` only after comparing
the stored record with the checked-in catalog.

Migration code and completion records are durable release infrastructure. Keep
catalog entries available for every installation the project allows to update,
and replace ledger storage only through a deliberate ledger-schema migration.
