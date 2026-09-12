# Backend Deferred Jobs

Deferred jobs provide one durable execution model for report generation and
execution, deterministic Form changes, Page/Task autofill, file OCR, file summary, AI
email handoff, and selected site work. Ingress, filter-cache maintenance,
notification email, and scheduled task uncompletion use focused workflows.

## Durable records

`DeferredJob` stores the bounded contract needed to recreate and inspect work:

- typed entity references and validated JSON parameters;
- actor and required access tier;
- immutable request fingerprint and operation identity;
- dispatch task identity and attempt state;
- status, monotonic revision, retry time, lease, and attempt deadline;
- bounded progress and checkpoint data;
- result/error and privacy-safe telemetry correlation; and
- cleanup, notification, and terminal-visibility markers.

Cloud Tasks carries only `{ "job_key": "..." }`. The worker reloads the actor,
inputs, and current job record. A browser operation UUID plus canonical request
fingerprint makes an exact repeated start idempotent and rejects reuse for
different work.

`DeferredJobLock` is a small target/scope ownership row. Autofill creates the
job, pending Notification, and `form-autofill` lock in one transaction. Keeping
the lock outside the Page/Task prevents lifecycle bookkeeping from changing
the target fingerprint or being overwritten by a complete entity save.
Terminal cleanup compare-deletes the lock by operation ID.

## Ownership

| Module | Responsibility |
| --- | --- |
| `deferred_jobs/service.py` | Public start/cancel/status/retention API and adapter registration. |
| `dispatch.py` | Deterministic Cloud Tasks, local dispatch, and feedback tasks. |
| `context.py`, `control.py` | Adapter context, deadline, cancellation, and lease renewal. |
| `runner.py`, `retry.py` | Claim, prepare, checkpoint, inspect/apply, delivery, and backoff. |
| `recovery.py`, `scheduler.py` | Stranded-work repair and Cloud Scheduler convergence. |
| `locks.py` | Target-lock lookup and cleanup. |
| `adapters/` | Domain-specific authorization, preparation, apply, and cleanup. |
| `database/deferred_jobs.py` | Cross-record transactions and compare-and-set writes. |
| `properties/deferred_job_*` | Pure durable values and browser-safe projections. |

## Start and dispatch

`DeferredJobs.start()` validates a typed `DeferredJobSpec`, creates or reuses
the job transactionally with its notification and optional lock, then dispatches
outside the transaction. Production requires a returned Cloud Task identity.
An explicitly disabled queue fails and runs compensation; a transient enqueue
error leaves the durable dispatch intent for recovery.

The job is added to `site/deferred-jobs-control` in the creation transaction.
That record tracks all queued, running, retry-wait, and delivery-pending jobs,
plus desired/applied Scheduler state and a generation-checked synchronization
lease.

## Execution

A delivery claims the job with a lease token. The worker:

1. reloads the actor and typed inputs;
2. checks current resource and AI permissions;
3. prepares provider or domain output;
4. stores a checkpoint before final mutation where the adapter supports it;
5. reloads authorization and mutation inputs;
6. verifies the lease, deadline, lock, and target revision;
7. inspects whether the result is already applied;
8. applies idempotently; and
9. completes cleanup, notification, and terminal visibility markers.

The five-minute lease is renewed every 60 seconds during blocking work. A job
attempt has a 24-minute application deadline inside the 30-minute Cloud Tasks
delivery deadline. Execution control is checked between provider rounds and
tool calls and immediately before apply.

Autofill uses a form-specific revision and active lock, so unrelated target
settings do not cause false drift. Other mutation adapters use their declared
target fingerprint. Report execution also checks the report's active operation
and proposal fingerprint.

## Retry and recovery

Provider calls inside jobs make at most two SDK attempts; durable retry owns
longer outages. Quota failures use 60- and 300-second delays plus positive
jitter. Other retryable provider failures use 60, 180, and 600 seconds.

The Scheduler reconciler runs every five minutes while recovery-required work
exists. After a two-minute grace period it claims missing dispatches, expired
leases, due retries, and incomplete terminal delivery. Work active for three
hours is moved to failure cleanup. The first tracked job enables the schedule;
a clean empty reconciliation pauses it.

The control record's generation prevents a stale pause from winning over a
concurrent new job. Membership is repaired from durable status queries, not
from Redis.

## Terminal delivery and browser status

Terminal state is split into cleanup, notification, and visibility checkpoints.
A delivery retry resumes at the first incomplete marker without repeating
provider preparation or domain apply.

Every client-visible status revision publishes a small Redis hint after the
Datastore transaction. `/l/poll` returns bounded phase, retry, terminal, and
destination metadata; it never returns inputs, checkpoint data, model output,
or lease tokens. Terminal status is a refresh signal: the browser fetches the
authoritative destination route. See
[FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md).

## Cancellation, replacement, and retention

Cancellation and report replacement write terminal tombstones, revoke the
lease, and delete known deterministic tasks. An in-flight request stops at its
next execution-control boundary. Terminal jobs remain available to the Owner's
AI Analytics diagnostics until explicit age-based retention cleanup. Cleanup
preserves active and delivery-pending work.

The Administrator diagnostic projection contains bounded timing, dispatch,
recovery, stage, safe entity references, and AI-generation summaries correlated
by an opaque ID. It excludes prompts, parameters, checkpoints, generated
content, authorization data, and provider/tool payloads.

## Deterministic Form changes

`form_changes.py` and `adapters/form_change.py` implement one Form update without
an AI report or approval plan. Builder Save uses `start_writes()` to persist the
Form's `pending_form_change`, DeferredJob, Notification and Form-scoped lock in
one guarded transaction. The pending payload owns the proposed schema/content,
conversion operations, actor timezone and source/target generations. Selection
in the builder and Save itself do not query submissions.

The worker enumerates all live Page/Task rows attached to the Form, including
completed Tasks, in cursor batches of 50. Edit access to the Form authorizes its
deterministic schema migration across all attached submissions, including those
on restricted Pages. The job rechecks Form edit access; it does not require the
actor to view or edit each Page/Task. Submission restrictions still govern viewing
values, notices and history, and directly editing answers. Preflight validates
generations and record sizes before application starts. Each application write
checks the current job lease, Form owner marker and exact submission row, then
patches only answer/generation/notice/receipt fields and required projections.
Task links, list owners and caches use normal mutation effects. Rows with this
change's receipt skip conversion on retry but retry their display effects.

`pre_migration` retains the earliest before-value and schema for changed fields.
Table notices display only changed cells. Completion envelopes are preserved;
legacy completed Tasks receive an original envelope before conversion. TaskHistory
is never a migration target. The source definition stays published until all
rows are converted, then ordinary Form publication archives its retired generation
and commits the target definition with a Save receipt.

During application, readers select source or target schema by each row's
generation. Typed filter/aggregate fields are withheld while their Form is pending.
The mutation executor fences affected full saves, answer patches, attachment
changes, completion/reopening and deletes at commit, including writers that began
before the lock. New attachments adopt the published generation; stale answers
must reconcile before saving.

The builder exposes progress and Retry through its notification slot, with Save
disabled and no cancellation control. The backend's pre-application cancellation
guard still revokes the job, removes the pending marker and cleans owned attempt
assets. After application starts, there is no bulk
rollback: terminal failure/expiry keeps the durable pending marker and lock. Any
current Form editor can Retry after a terminal or missing job. A fresh job takes
over the same change ID, rechecks targets and skips converted receipts. This
remains recoverable even after normal job retention removes the previous job.
`before_cancel()` prevents generic cancellation from discarding partial work.

## Adapter checklist

When adding a deferred adapter:

1. define typed, bounded request inputs and required authorization;
2. make the operation fingerprint stable;
3. decide whether a target lock is required;
4. checkpoint expensive prepared output before apply;
5. make `inspect` and `apply` safe under duplicate delivery;
6. reauthorize and check target drift immediately before mutation;
7. define compensation, terminal notification, and browser destination;
8. add claim, retry, duplicate, cancellation, drift, and recovery tests.
