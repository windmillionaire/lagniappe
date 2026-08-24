# Backend Ingress

CSV ingress is a versioned durable workflow owned by
`lagniappe/core/tools/ingress.py`. `IngressService` is the only runtime owner of
stage transitions, configuration invalidation, generated-entity planning,
cursor-checked execution, result progress, and retry/stop behavior. Ingress properties
are presentation facades, and Flask routes are authorization/transport
adapters.

## Durable record

Every supported ingress row has `ingress_format = 1` and two JSON documents:

- `workflow`: current/highest-completed stage, configuration revision, and the
  stage sections used by the wizard;
- `execution`: run status, committed cursor, total rows, dispatch sequence, and
  any execution error.

Parsed rows and indexed result slots remain private JSON assets. A result slot
is written before its row transaction, but readers expose only slots below the
committed cursor. A failed or stale attempt can therefore overwrite an
uncommitted slot without publishing it.

Missing, malformed, or unsupported formats are rejected with an instruction to
upload the CSV again.

## Stage and execution transitions

`IngressStage` is strict; unknown names do not fall back to `PROCESS_CSV`.
The machine-readable transition inventory is `INGRESS_TRANSITIONS`.

| Action | Valid source | Durable result |
|---|---|---|
| Create/parse | New record | `PROCESS_CSV`, parsing complete, execution `idle` |
| Navigate | Configuration stage, execution `idle` | A stage whose prerequisites are complete |
| Advance | `PROCESS_CSV` through `ASSIGN_COLUMNS` | Validate/finalize and move forward |
| Start | Valid `VERIFY_IMPORT` | `IMPORTING/queued` |
| Stop | Queued import | `stopped` at a transaction boundary |
| Row commit | Active import at expected cursor | Domain mutations and cursor advance in one transaction |
| Restart | Stopped or failed | `queued` at the existing cursor |
| Finish | Cursor equals total rows | `COMPLETED/completed` |
| Duplicate delivery | Cursor already advanced or execution terminal | No mutation |

Invalid transitions return HTTP 409. User-correctable validation remains on
the current stage with a persisted error. Editing a configuration stage clears
its completion and every dependent section, increments the configuration
revision, and detaches setup relations that no longer apply. Configuration is immutable
after execution starts.

## Service boundaries

`IngressService` composes four focused boundaries:

- `IngressParser` validates and parses CSV content into metadata and row data;
- `IngressMapping` projects canonical form/column/page-match mappings;
- `IngressMutationPlanner` converts one row into a serializable result and
  deterministic entity mutations;
- service execution writes result slots, commits row plans, and stops, fails,
  or finishes the durable run.

Task imports expose separate special mappings for page name, task name,
completion date, and due date. Multiple source columns may map to one field;
task-name and ordinary text values are combined in source-column order. Each
source column maps to at most one destination field.

Every task-import row creates a distinct task, even when another imported or
existing model-linked task targets the same page. Multiple completion-date
columns within one row remain the supported history projection: those dates
are applied only to that row's task and may create its completion history.

Generated categories, projects, models, forms, pages, tasks, and task histories
use keys derived from the ingress key, configuration revision, row index, and
role. Replaying the same planned work therefore targets the same entities.
Generated setup entities detached by later configuration changes are retained;
they are not automatically deleted.

Each row uses the normal entity mutation planner to discover entity and
relation effects. The row's Datastore entities, ingress cursor, result-asset
metadata, and required site fingerprints are committed atomically after
checking the persisted cursor and active status. A duplicate worker that planned
the same row loses the cursor comparison and exits without another durable
write. Cache refresh is post-commit. Infrastructure failures put the import in
resumable `failed` state; row validation errors are ordinary results and do not
stop the run.

## Routes and workers

All `/files/ingress` routes require `Resource.SITE`. They load the entity,
invoke `IngressService`, and return the standard progress projection. Existing
URLs remain:

- `GET/POST /files/ingress`
- `GET/PUT /files/ingress/<key>/stage`
- `PATCH /files/ingress/<key>/update`
- `PUT /files/ingress/<key>/next`
- `POST /files/ingress/<key>/import`
- `POST /files/ingress/<key>/stop`
- `GET/DELETE /files/ingress/<key>/delete-imported`
- `GET /files/ingress/<key>/get-page-form`

`POST /process/ingress` authenticates the Cloud Task and runs one 25-row batch.
If rows remain, the final row commit advances the dispatch sequence and the
worker dispatches the next batch. Cloud Tasks may deliver duplicate workers;
the persisted cursor is the single-writer boundary. A follow-up dispatch
failure returns a retriable infrastructure response; an initial dispatch
failure is persisted as `failed`. Redis is not part of the execution authority.

The progress response contains `stage`, `run_status`, `processed`, `total`,
`error`, `stopped`, allowed `actions`, `poll_after_ms`, and rendered progress
and status HTML. `widgets/ingress.mjs` uses the allowed actions and run status
for start/stop/restart/polling; stage-specific browser branches only initialize
DOM controls.

## Verification

Focused unit coverage lives in `test_006b_ingress_entity.py` and
`test_006d_ingress_service.py`. It covers strict formats and transitions,
downstream invalidation, duplicate deliveries, cursor compare-and-set, stop
boundaries, failure/restart, ordered result visibility, deterministic row
behavior, and page/task mapping parity. The ingress wizard E2E file covers
upload, every configuration stage, generated/existing parents and forms,
navigation/error persistence, completed page imports, ignored columns, and
task page-form matching.
