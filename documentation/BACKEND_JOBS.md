# Backend Deferred Jobs

Deferred jobs provide one durable execution model for report generation and
execution, Form changes, Page/Task autofill, file OCR, file summary, AI
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
attempt has a nine-minute application deadline, below App Engine automatic
scaling’s ten-minute request limit. Cloud Tasks retains its 30-minute delivery
deadline. Report planning also has a ten-minute total lifetime from job creation,
including queue waits; each attempt uses the earlier deadline. Execution control is checked between provider rounds and
tool calls and immediately before apply.

While awaiting a provider, cancellation checks run about once per second and
read the durable lease token without writing the job. Local deadline, known
claim loss, and heartbeat failure checks run before and after that read.
During an attempt, the initial execution heartbeat and the 60-second background
heartbeat extend the lease; progress and checkpoint writes retain their existing
purposes.
Cancellation therefore remains observable at the next one-second provider check
(plus database latency), independently of renewal. Each execution boundary still
reads ownership afresh, and publication/checkpoint transactions retain their
authoritative token checks. No cached ownership hint authorizes a mutation.

Site generation of corrective plans requires AI.CREATE, including retries and
proposal revisions. The report adapter rechecks that entitlement before provider
preparation and publication. External corrective proposals and their approved
execution remain independent of site provider access.

Autofill uses a form-specific revision and active lock, so unrelated target
settings do not cause false drift. Other mutation adapters use their declared
target fingerprint. Report execution also checks the report's active operation
and proposal fingerprint.

## Retry and recovery

Dependency checks use the `waiting_dependency` phase. Report execution labels
this as “Waiting for form update”; other dependencies use “Waiting for related
work.” A normally scheduled dependency check is not presented as automatic
recovery. Stale work, pending dispatch repair and actual failure retries display
“Taking longer than expected” without claiming that a recovery worker is active.
Status projection also corrects older dependency-wait
records that used the file-summarization phase.

Server dependency checks are separate from the browser's status polling.
`ReportExecutionAdapter` checks again after 5, 10, 20, then 30 seconds, retaining
the 30-second interval for longer migrations. Other adapters default to 60
seconds. Each adapter declares its nonempty `dependency_retry_delays` tuple;
the runner uses the saved dependency-wait count to select a delay, persists the
due time, and dispatches the continuation with the same delay. These checks do
not consume the provider retry budget. The existing job leases, publication
guards and per-action ledger still protect dependent actions and repeated work.

Report planning uses generation-owned asynchronous clients behind the synchronous
workflow interface. Blocking requests are cancelled at execution-control boundaries;
SDK retries are disabled. At most one transient retry is recorded durably per job
and repeats the current request with its existing conversation. After 16 retrieval
rounds or with three minutes remaining, the model must finalize without tools.
A lost report worker without a validated proposal checkpoint requires manual Retry;
recovery never restarts discovery. Saved proposals can resume publication within
the job lifetime.

Other provider-backed jobs make at most two SDK attempts; durable retry owns
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

Elapsed time in status and AI Analytics measures the job lifetime from creation,
including queue and retry waits. Active jobs use the current time; succeeded,
failed, cancelled, and superseded jobs stop at the terminal `progress.updated_at`
timestamp. Later cleanup or notification writes do not extend that duration.
Older terminal records without a valid progress timestamp use stored `modified`;
records without either timestamp return zero instead of continuing to count.

Every client-visible status revision publishes a small Redis hint after the
Datastore transaction. `/l/poll` returns bounded phase, retry, terminal, and
destination metadata; it never returns inputs, checkpoint data, model output,
or lease tokens. Terminal status is a refresh signal: the browser fetches the
authoritative destination route. See
[FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md).

## Cancellation, replacement, and retention

Cancellation and report replacement write terminal tombstones, revoke the
lease, and delete known deterministic tasks. Report list/detail views and Analytics runs expose **Cancel generation**, bound
to the exact job and operation identity. The creator or an existing Analytics
administrator can cancel without AI entitlement. Cancelling initial generation
leaves a cancelled report with **Retry generation**; cancelling revision restores
the saved proposal. Cleanup and notification delivery are durable recovery steps.
Proposal publication checks the report snapshot and active job lease in one
transaction. An in-flight planning request is cancelled at its next
execution-control boundary. Terminal jobs remain available to the Owner's
AI Analytics diagnostics until explicit age-based retention cleanup. Cleanup
preserves active and delivery-pending work.

The Administrator diagnostic projection contains bounded timing, dispatch,
recovery, stage, safe entity references, and AI-generation summaries correlated
by an opaque ID. It excludes prompts, parameters, checkpoints, generated
content, authorization data, and provider/tool payloads.

In Analytics, expand a Recent Run to see its report link when available, elapsed job time,
and the individual AI stages recorded for the selected period. Each stage
separates model requests, tool rounds/calls, input and cached tokens, output
and reasoning tokens, and duration. Cached tokens are a subset of input tokens;
stage durations are not the whole job's elapsed time. Tool names appear once
each, with repeated calls labelled by count; this is not an ordered transcript.
The JSON export preserves the original tool-name entries. Missing summaries
are shown as unavailable.

Recent Runs omits report-execution jobs without AI generation summaries. Those
jobs apply reviewed actions, including exact schema-conversion candidates for
both on-site and external reports. Builder utility conversions run under their
separate Form Change job. Execution diagnostics remain accessible through the
existing diagnostic route, and executions still retain their ordinary job and
report history. Missing summaries for AI planning jobs remain visible.
The Form Change worker supplies its own telemetry ID at the utility-model
boundary, so new conversion summaries join to that job's run JSON.

Result processing is separate from job success. `normalized` (shown as
**Formatted / normalized**) means validation changed the representation, for
example by rendering Markdown as HTML or adding default fields. Explicit local
corrections still record `local_repair`; **Locally adjusted** also accommodates
older records that used that value for ordinary normalization. `model_repair`
means the workflow requested a separate model repair. Explicit repair/review
outcomes take precedence over subsequent normalization. Historical JSON is not
rewritten, and the export retains these machine-readable outcome values.

**Copy run JSON** reads the existing owner-only operation diagnostic endpoint
and copies its indented JSON, including available retained stages for the run
and the query-limit indicator. A selectable text field appears if clipboard
access fails. This is the preferred handoff for per-run evaluation; it does
not require a separate cloud query or capture additional content.

Report links are offered only for reports owned by the current user, matching
the report route's existing access rules. Other users' jobs still expose the
owner diagnostic JSON and its safe references.

## Form changes

`tools/forms/changes.py` and `deferred_jobs/adapters/form_change.py` implement one
Form update without a separate migration subsystem. Builder Save uses
`start_writes()` to persist the
Form's `pending_form_change`, DeferredJob, Notification and Form-scoped lock in
one guarded transaction. The pending payload owns the proposed schema/content,
conversion operations, actor timezone and source/target generations. Selection
in the builder does not query submissions. AI Save and AI report preparation
check complete population visibility before reservation.

The worker and schema previews share `tools/forms/population.py` to enumerate
all live Page/Task rows attached to the Form, including completed Tasks, in
cursor batches of 50. `tools/forms/contracts.py` owns the persisted keys and
payload helpers shared by publication, previews, locks, and execution. Edit
access to the Form authorizes its
deterministic schema migration across all attached submissions, including those
on restricted Pages. The job rechecks Form edit access; it does not require the
actor to view or edit each Page/Task. Submission restrictions still govern viewing
values, notices and history, and directly editing answers. Preflight validates
generations and record sizes before application starts. Each application write
checks the current job lease, Form owner marker and exact submission row, then
patches only answer/generation/notice/receipt fields and required projections.
Task links, list owners and caches use normal mutation effects. Rows with this
change's receipt skip conversion on retry but retry their display effects.

AI conversions (textarea→table/todo and table↔todo) share this worker. Builder
calls use the utility tier synchronously for one target's affected fields at a
time, with bounded input/output and one malformed-output repair. A prepared
`ai_batch` checkpoint precedes the live write; a replay verifies source hashes
and reuses those results. On-site Organize and external candidates come from an
immutable approved report; no provider is invoked. The presence of a linked
report selects prepared conversion, independently of report origin. Retry carries
any pending prepared batch to the replacement worker. Every AI-originated
migration, deterministic included, checks
Form edit and complete population view access before application and rechecks
current access per target. This does not require per-target edit access. Builder AI
calls additionally require AI.CREATE. Initial restricted/stale preflight failure
releases only an unapplied change using guarded rejection state; partial changes
retain ownership. Manual deterministic builder migrations retain Form-only
authority as described above.

The on-site utility prompt requires absent table cells to omit their column keys.
Its output boundary also treats null and blank-string cells in known columns as
absent, preserving explicit zero/false and rejecting populated values of the wrong
type. Unknown columns and empty rows/collections remain validation failures;
all reviewed report candidates retain exact-shape validation without normalization.
Validation failures name the field, column, row and expected type where available.
The worker retains target/field references in private job error context; builder
status resolves an affected Page/Task link only after checking current visibility
and Form membership. Existing errors containing only column IDs are translated
using the pending schema. Retry continues unfinished work and preserves receipts
for already-converted answers.

`update_form_schema` report actions flush their current execution batch and record
the child migration ID before starting it. The report runner raises the existing
dependency-pending signal and releases
its worker while the child runs. Retry checks the pending owner/publication
receipt, and dependent actions proceed only after publication. Candidates remain
inside the linked report, whose fingerprint is rechecked by the worker. No bulk
Undo is allowed after a migration starts, and deletion is fenced while pending.

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

Analytics and exported operation diagnostics reconcile running report telemetry
against durable terminal job state, replacement attempts, and the ten-minute
limit. Orphaned attempts appear as interrupted, rather than remaining in-flight.

Report execution uses general batches with a shared working entity map; action
dependencies do not require intermediate commits. Workspace writes and their report
results share a transaction and a batch receipt. Recovery reads that receipt before
replaying a failed group. A completed report with pending document publications is
still considered unfinished by the execution adapter until those publications have
been reconciled. See [AI workflows](AI_WORKFLOWS.md) for batching and overwrite semantics.
