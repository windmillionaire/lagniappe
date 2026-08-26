# Infrastructure Data Lifecycle

Backup, archive, and restore are privileged installer workflows. They run as
the saved human operator, never through runtime `DataServices`, and use the
operator-only recovery bucket.

```bash
./setup.sh backup create
./setup.sh backup list
./setup.sh backup prepare AUTOMATIC_BACKUP_ID
./setup.sh backup delete BACKUP_ID
./setup.sh archive [BACKUP_ID] [--output PATH] [--zip]
./setup.sh archive validate ARCHIVE_PATH
./setup.sh restore BACKUP_ID --dry-run
./setup.sh restore BACKUP_ID
```

Use `setup.cmd` on Windows. Mutating delete and restore commands require the
exact printed confirmation.

## Recovery infrastructure

Setup enables the Cloud Firestore API before configuring a seven-day Firestore
PITR window, daily native backups retained for 14 days, Sunday backups retained
for 14 weeks, and 14-week noncurrent generation retention on runtime buckets.
Provider data protection is reconciled as its own setup step; deferred-job
Scheduler setup does not import or execute the application runtime. Lifecycle
commands preserve stored application records as they exist and never run the
Owner-controlled data migration catalog. Backup and restore fail read-only if
the official asset-generation migration is not complete, with directions to
the Owner's **Apply Updates** action.

The recovery bucket has no browser CORS and no runtime-account access. The
human installer/deployer has object administration. `GIBBERISH` deterministically
locates the bucket; keep the encrypted settings snapshot and its key off-machine.

## Automatic and manual backups

`backup create` chooses one whole-minute PITR timestamp, exports every kind and
namespace from `(default)`, inventories entity asset descriptors at the same
read time, and copies those exact Storage generations into a self-contained
manual backup. The manual backup remains until explicitly deleted.
`manifest.json` is create-only and written last, so incomplete prefixes are
neither listed nor consumed.

Google's scheduled automatic backups remain provider-managed and expire at the
end of their configured retention. `backup prepare` converts a selected
automatic backup into the same self-contained manual-backup format so it can be
restored with its exact referenced files or converted to a portable archive.
The command accepts the displayed automatic-backup ID and resolves its full
provider resource only within the saved target project; missing or ambiguous
IDs fail without creating recovery resources.
Delete invalidates the manifest before removing the exact prefix. A sanitized
summary is projected into the private runtime bucket for the authenticated
Admin view; backup objects and provider URIs remain confined to the
operator-only recovery bucket.

## Portable archives

Archive consumes one complete manual backup. Without an ID it first creates one.
It imports Datastore into a temporary named database, stages bounded pages in
owner-only local SQLite, replaces provider keys with typed portable identities,
and reads only generation-bound recovery copies. Ordinary content uses its
stored hash, users use a digest of their case-normalized unique email, and
hashless reserved models use a key-partition-independent internal identity
while retaining their explicit reserved role for target mapping.

Output is either `archives/<backup-id>/` or a ZIP. It contains:

- a key-free portable JSON contract and machine schema;
- canonical document HTML;
- local referenced assets;
- checksums, inventory, and relationships; and
- a network-free Owner-oriented site at `site/index.html`.

Archives contain private Owner-visible content and are not encrypted.
Publication is atomic; `manifest.json` is the final ZIP entry. `archive
validate` checks paths, hashes, counts, identities, relations, links, assets,
and the absence of recognizable Datastore keys without network access.

PITR and automatic backups remain inside Google Cloud and are limited by their
retention windows. A portable archive is instead an independent, downloadable
copy containing provider-independent data, rendered documents, and referenced
files. It can be validated without Google access, but it is not accepted as the
input to the in-place restore command; restore uses the manual backup ID.

Interrupted work resumes only for the exact project, command, backup, and
output. Failed scratch databases and private staging state remain for targeted
inspection/retry. Successful publication survives cleanup failure; rerunning
the exact command finishes cleanup.

## Restore model

Restore merges the manual backup into `(default)`:

- matching keys are overwritten;
- missing manual-backup keys are recreated; and
- live keys absent from the manual backup remain.

Provider import supplies the exact key-overlay semantics; restore does not
compare application `modified` timestamps.

## Restore safety sequence

A mutating restore:

1. enters maintenance and pauses deferred-job recovery and the Cloud Tasks
   queue;
2. captures a FULL-view queue audit, purges the queue, and waits for empty;
3. lets requests on the prior App Engine version drain;
4. creates a PITR safety clone of the quiescent database and records live asset
   generations;
5. imports the recovery data and copies exact recovery asset bytes to runtime
   paths;
6. rebinds entity asset descriptors to the copied generations;
7. discards nonterminal jobs, locks, Scheduler control, and active operation
   pointers;
8. performs relation-aware validation, then clears Redis so no pre-restore
   cache entry can survive the database merge;
9. regenerates only task-uncompletion deliveries represented by durable Task
   markers; and
10. restores traffic and queue/Scheduler state, writes an audit, and deletes
    the safety clone.

After a successful restore, the console directs the Owner to **Admin → Site
Settings → Maintenance**, where the Owner applies any pending updates and then
selects **Refresh Cache**. Those explicit application-owned actions must complete
before cache-backed search and navigation are treated as verified. The installer
clears Redis using the saved setup connection, but it does not import application
migrations, Flask, or authorization to transform records or rebuild user-scoped
cache projections.

Cloud Tasks has no atomic list-and-purge receipt; the queue audit is an
observation after producers are paused. Ordinary purged deliveries are not
replayed because their durable workflows recover from application records.

## Failure behavior

`--dry-run` performs reads only and reports overwrite/recreate counts. A
mutating run stores local and secret-free remote journal checkpoints and resumes
only the same project/manual backup.

Failure leaves the application in maintenance with the safety clone and asset
versions available for diagnosis. Restore does not automatically roll back.
The Admin **Backups & Archives** tab is informational; restore and delete remain
exact-confirmation operator commands.

## Restore journal compatibility

Restore journals are resumable only when they describe the current in-place
`(default)` database workflow and match the exact application version. Released
versions `v0.1.0` and `v0.2.0` did not include lifecycle restore journals, so
there is no released named-database cutover format to migrate.

Pre-release journals that target a separate named database or describe rollback
are never executed. The installer rejects them before confirmation or provider
mutation with guidance to inspect and archive the obsolete journal before
starting a current in-place restore. Named databases remain part of the active
design only as temporary, targeted safety clones and archive scratch databases.

## Change checklist

- Keep the recovery bucket outside runtime credentials.
- Bind every manual backup to one database read time and exact asset generations.
- Write publication manifests last.
- Keep archives provider-key-free and validate them offline.
- Pause producers and capture a safety clone before mutating restore.
- Regenerate only work with a durable application marker.
- Make resume identity exact and cleanup targeted.
