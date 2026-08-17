# AI Pipeline

This document describes the AI pipeline from browser submission through
durable execution, Gemini generation, workspace tool calls, deterministic
application, and browser reconciliation.

Related implementation details are documented in
[BACKEND_TOOLS.md](BACKEND_TOOLS.md),
[BACKEND_ENTITIES.md](BACKEND_ENTITIES.md),
[FRONTEND_VIEWS.md](FRONTEND_VIEWS.md), and
[SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md); runtime model, retry, and caching
configuration is documented in [INFRA_CONFIG.md](INFRA_CONFIG.md).

## Safety boundaries and known limits

The pipeline protects data through these boundaries:

- model output is a proposal or prepared value, not an unrestricted mutation;
- workspace tools are read-only and permission-filtered;
- generated reports pass typed schemas, application validators, repair, and
  safe review fallbacks;
- report application is deterministic, permission-checked again, and protected
  by a resumable per-action ledger;
- deferred jobs carry only a durable job key through Cloud Tasks, reload their
  actor and inputs, and inspect durable state before apply; most adapters also
  checkpoint a prepared final output first;
- terminal operation revisions act as invalidations and the browser refetches
  authoritative server-rendered state; file OCR and summaries additionally
  converge through watched entity fingerprints and durable notifications.

The pipeline does not yet have generation-wide budgets, so one unusually broad
tool result or repeated file retrieval can be expensive even in a one-person
workspace. Other known boundaries are narrow race and retention edges with
safe recovery or reload paths already in place.

Privacy-bounded generation summaries and the owner dashboard provide the
production evidence needed to determine whether prompt size, serial tool
execution, cache misses, queue contention, or the structured-final call cause
material latency or cost.

## Scope and terminology

This document covers:

- `lagniappe/core/tools/ai/`, including prompt construction, model calls,
  guidelines, function declarations, validation, repair, and report execution;
- `lagniappe/core/tools/deferred_jobs.py` and
  `lagniappe/core/tools/deferred_job_adapters.py`;
- AI entry routes, uploads, durable notifications, operation polling, and
  frontend destination reconciliation;
- runtime model settings, provider retries, Cloud Tasks delivery, and queue
  setup where they affect the AI path.

Actual prompt, cached-content, output, thought, and total token counts are
recorded by the privacy-bounded generation summary and can also appear in
`AI_DEBUG` response breadcrumbs.

## Architecture at a glance

```text
Browser form
  -> route validates the request and persists target/report
  -> DeferredJobs.start(typed inputs, parameters, client/notification contract)
  -> DeferredJob + pending Notification transactionally get/create by operation ID
  -> Cloud Task contains only {job_key}
  -> POST /process/jobs authenticates, claims a lease, reloads actor/inputs
  -> adapter rechecks current permission and prepares provider output
       -> Prompt builds stable policy + dynamic context + output contract
       -> GenAI resolves a live model for one top-level generation
       -> initial Gemini request
       -> optional model-selected workspace/search tool rounds
       -> optional structured-final request
       -> application validation, local repair, or model repair
  -> most adapters save final prepared output in DeferredJob.checkpoint
  -> adapter inspects current durable state and applies idempotently
  -> job/result/notification terminal state saved
  -> operation status revision becomes visible through POST /l/poll
  -> shared polling coordinator refetches the authoritative destination
  -> notification Redis state and entity revisions refresh other mounted surfaces
```

There are three different checkpoint systems and they should not be conflated:

1. `DeferredJob.checkpoint` typically stores a prepared final output before the
   adapter's final apply; Site Export instead relies on domain-specific
   idempotent state.
2. `report.upload_manifest` records per-file Organize ingestion progress.
3. `report.result` is the versioned per-action execution/undo ledger used after
   a user approves a proposal.

Email-origin reports add a transport handoff in front of this same pipeline.
The signed Resend webhook claims an HMAC-only replay record, retrieves and
normalizes the message, matches one exact stored user email, creates a
deterministic pending `AIReport`, and starts `EMAIL_INGEST`. That adapter streams
ordinary attachments and intentional inline content into deterministic
report-owned `File` entities and then
starts the normal `REPORT_ASK`, `REPORT_CREATE`, or `REPORT_ORGANIZE` job. For
the shared `ai@` alias, attachment-only messages deterministically select
Organize when it is available; otherwise a no-tools/no-search utility-model
classifier selects an eligible workflow from subject/body and safe attachment
metadata before any download. The result is persisted in `inbound_manifest` for
retry stability.
Explicit aliases bypass classification. This does not create a second proposal
implementation. Acceptance and
terminal result email are independently idempotent; Create/Organize proposals
still require browser review and deterministic execution.

### Main ownership boundaries

| Layer | Current owner | Responsibility |
|---|---|---|
| Prompt composition | `ai/prompt.py` and workflow builders | System instruction, context/instructions ordering, output contract, attachments, tools, search, model/tier, and limits. |
| Provider lifecycle | `ai/core.py` | Runtime model selection, Gemini configuration, SDK calls, tool loop, structured-final call, cleanup, and debug usage. |
| Workspace retrieval | `ai/functions.py` and `function_definitions/` | Tool declaration, hash normalization, permission-filtered handler execution, exact-call cache, result/file parts, and failure trace. |
| AI workflow | `ai/ask.py`, `create.py`, `organize.py`, `autofill.py`, `email_router.py` | Workflow-specific context, tool selection, email intent classification, generation stages, and fallback. |
| Report proposal contract | `ai/reporting/contracts.py`, `proposals.py`, and `organize_completion.py` | Shared action schemas and ordering, proposal validation/repair, and Organize file-summary/submission completion. |
| Durable generation | `deferred_jobs.py` and adapters | Job creation, claim/lease, retries, checkpoint, inspect/apply, cleanup, and durable notification state. |
| Proposal application | `ai/report_runner.py` and `ai/reporting/actions/` | Ledger coordination plus callback-registered deterministic action inspection, execution, retry, compensation, and undo. |
| Browser completion | `/l/poll`, `PollingCoordinator`, `DeferredOperationManager`, `Core`, and `EditWatcher` | Operation acknowledgement, owner-safe status, revision validation, notification refresh, collection reconciliation, and watched-form refetch. |

## End-to-end workflow

### 1. Request and durable start

An AI-enabled form is prepared in the browser before submission. Preparation
can include direct uploads. The request includes the submitter role and optional
explain/preview intent.

The route performs its ordinary request and permission checks, persists the
pending report or target state, and calls `DeferredJobs.start()` with a typed
`DeferredJobSpec`. The browser supplies an operation UUID and the registry
binds it to an immutable canonical request fingerprint. Job and pending
notification are transactionally get/created; replay of the same stable spec is
idempotent and UUID reuse for a different spec is rejected. Report creation and
site export allocate their domain record immediately before this
transaction, outside the durable job/notification transaction. The durable job
contains entity references and bounded parameters rather than fully rendered
prompts or file bytes. File processing creates only a terminal notification.
Email ingestion creates no pending or success notification; it creates a linked
terminal notification only when ingestion fails, while the child report job
retains its ordinary report-completion notification.
Production then schedules the shared `process.deferred_job_process` endpoint at
`POST /process/jobs`; its Cloud Task payload contains only the job key. An
explicitly disabled queue fails and compensates immediately. A transient
enqueue exception leaves the durable dispatch intent pending for the scheduled
reconciler.

The immediate response is an acknowledgement such as
`{deferred: true, operation: ..., notification: ...}`. Report routes can also
return a rendered pending report row carrying the operation. The browser batches
those opaque references through an owner-safe bounded status endpoint; the
server validates that `source_widget` and `destination` are either both present
or both absent before accepting a completion contract.

### 2. Claim, authorization, and input loading

The worker transactionally claims a queued or retry-wait job with a lease token.
It reloads the actor and every typed input rather than trusting request-time
objects. The adapter rechecks current access at worker start. A heartbeat renews
the claim while provider work blocks, and provider/tool boundaries check the
attempt deadline, cancellation, and lease. Immediately before final application
the runner reloads the actor and mutation inputs again, reauthorizes, compares
their start-time fingerprints, and verifies the active claim.

The generic AI gate is driven by `adapter.required_ai_access`. Ask jobs require
`AI.ASK`; generation, organization, execution, autofill, page generation, and
file summarization require `AI.CREATE`. Domain adapters add their own checks,
such as edit access to an autofill target or owner access to site export. Every
adapter with a required tier delegates to the shared authorization method, and
a parameterized registry test protects the tier contract. The synchronous
multi-file upload summary path applies the same `AI.CREATE` gate at its route
boundary.

### 3. Prompt and model selection

`Prompt` holds more than its rendered text:

- a system instruction;
- context and instruction blocks;
- output format and optional provider response schema;
- examples;
- inline bytes and provider-hosted file parts;
- Google Search and selected function declarations;
- thinking budget, primary/utility model tier, service tier;
- tool-round and per-turn file-part limits;
- stable-instructions-before-context ordering.

`GenAI` reads live `site/ai` settings at the start of each top-level generation
and falls back to deployed settings. It pins that resolved model through the
initial request, tool rounds, retries inside that generation, and any
structured-final pass. Separate Organize stages and later deferred-job attempts
are separate generations and can resolve newer settings.

### 4. Provider and tool loop

The initial provider request contains rendered prompt text, initial attachments,
and provider configuration. When JSON, tools, and a response schema are all
enabled, the initial/tool turns deliberately remove the JSON MIME type and
response schema. This lets Gemini request functions without fighting the
structured-output constraint.

If Gemini returns function calls, the application:

1. records a failure-oriented trace for the round;
2. normalizes all hash references in the requested batch;
3. executes each requested handler in order;
4. caches each exact `(tool name, normalized arguments)` result for this
   generation;
5. appends the model call, function responses, and allowed original-file parts
   to the conversation;
6. sends the complete growing transcript back to Gemini.

The prompt asks Gemini to request independent calls together. The SDK can
represent parallel function calls, but the current dispatcher executes the
same-turn list serially. This preserves deterministic ordering and simple Flask
and entity context, but forfeits potential latency savings for independent
read-only calls.

When a response schema exists in this JSON-plus-tools path, the application
always performs a separate structured-final request after tool discovery—even
if the initial response did not request a function. The minimum planning cost
for Ask/Create/Organize is therefore two provider requests; one tool round makes
the minimum three. The terminal model response is appended to the transcript
before the structured-final instruction so useful planning or synthesis is not
discarded when the model needs no tool or has just completed its tool loop.

Autofill deliberately does not use a provider response schema. Its submission
keys are dynamic form field ids, and an untyped object response schema can steer
compliant models to `{}`. Autofill instead carries an explicit JSON/submission
contract in the prompt and filters the returned object through the target's
actual form validation. Without stored-file tools, JSON response MIME still
constrains the initial request. When `get_file` is available, the shared tool
path leaves the provider response unconstrained during tool discovery and
accepts the model's terminal JSON directly; no structured-final request is
added just because an attachment exists.

### 5. Validation, repair, and durable application

Ask, Create, and Organize validate model output against application-owned
contracts in `ai/reporting/`. `contracts.py` owns the allowed action set, action
ordering, and typed action-data schemas; `proposals.py` owns their shared
validation, normalization, and repair. Organize adds its workflow-specific
file-summary and form-submission completion in `organize_completion.py`,
including new records and exact existing page/task targets. Existing targets
receive only evidence-backed changed fields, projected as reviewed
`update_submission_fields` rows; the paired source file remains a normal
attachment action. Narrow deterministic repairs cover stable field IDs and
unambiguous form links, before spending another model call on repair. Unsafe
residual actions become review items; a structurally unusable plan becomes an
accurately labeled review-only proposal.

Most deferred generation saves the final prepared proposal or submission in the
job checkpoint before its final domain apply. Site Export is an exception: its
adapter relies on its own idempotent metadata/archive protocol during apply.
The adapter then inspects current state to distinguish already-applied from
not-applied work and applies idempotently. AI report generation only saves a
proposal. A later user-reviewed execution is queued as a distinct deferred job;
its worker calls `run_report()` through the separate `report.result` recovery
ledger. `report_runner.py` owns that version-1 ledger and ordered lifecycle;
the action package owns one explicit callback adapter per contract action and
groups domain handlers by entity, form, file, task, and shared-operation
responsibility. The registry is checked against the proposal contract so a new
action cannot silently exist on only the generation or execution side.

### 6. Terminal notification and browser refresh

Terminal progression remains split into cleanup, notification, and final
visibility markers so infrastructure retry can resume an incomplete durable
transition without rerunning domain apply. These are Datastore checkpoints,
not provider deliveries. Completion means terminal, not necessarily
successful; authoritative job/report/target state carries the outcome.

The shared polling coordinator batches active operation references. A terminal
status includes only bounded source/destination/entity identifiers and a
monotonic revision. The browser rejects older revisions, locates the mounted
destination, and fetches its authoritative replacement route. It pauses while
hidden, unfocused, or offline and backs off with jitter while quiet. File
completion converges through the durable Notification entity's Redis projection
plus `EditWatcher`'s entity fingerprint refetch.

## Workflow comparison

| Workflow | Initial context strategy | Dynamic capabilities | Provider stages | Durable result |
|---|---|---|---|---|
| Ask | Lean question/report context | Google Search, shared workspace tools, task history, filter schema/query | Initial, zero or more tool turns, structured final, optional repair | Answer plus optional reviewed actions |
| Create | Lean creation request and workspace concepts | Google Search and shared workspace tools | Initial, zero or more tool turns, structured final, optional repair | Reviewed creation proposal |
| Organize | Uploaded-file metadata, saved summaries, up to two retrieval terms per file, bounded Redis candidates | Shared workspace tools; no Google Search in planning | Utility summary per missing file, primary plan/tool loop, optional repair, optional primary form completion | Reviewed organization proposal |
| Shared AI email router | Subject/body and safe attachment metadata only | No search or tools; entitlement-filtered Ask/Create/Organize enum | One utility-model structured classification | Persisted workflow selection, then the normal email/report pipeline |
| Page/task autofill | Eager target/form/submission context, compact parent/category/document context, and target-specific `File.to_ai()` projections | Google Search; conditional two-round `get_file` fallback only | One JSON/tool conversation plus local validation | Generated submission applied to target |
| File summary | File plus summary instructions | Utility model and optional retrieval-term generation | One generation, provider/file fallback as supported | Summary/process state on File |
| Report execution | Already reviewed proposal; no model | Deterministic action handlers only | No provider call | Versioned execution/undo ledger and domain mutations |

### Ask and Create

Ask and Create follow the useful "small initial prompt, retrieve on demand"
pattern. They expose only read tools and retain reviewed application as a
separate boundary. Their main context risks are broad tool/schema overhead,
unbounded results from a few handlers, a 50-round ceiling, Google Search being
available even for internal-only requests, and the unconditional
structured-final call when a response schema is configured.

Ask preparation returns a prepared proposal/status value without mutating
the input report. The generic runner checkpoints that value before
`ReportAdapter.apply()` owns the durable report save.

When an email-origin Ask includes ordinary attachments or intentional inline
content, preparation first uses
the existing bounded report-file summary path with search indexing disabled.
The prompt receives a `submitted_files` context containing safe metadata,
summaries, and read-only `get_file` references. Those files are evidence only;
Ask does not gain Organize placement actions.

### Organize

Organize has the strongest deliberate context design:

1. direct uploads are finalized one at a time with an upload-manifest
   checkpoint;
2. the utility model creates and saves a summary and up to two nonempty,
   deduplicated retrieval terms for each missing summary;
   PDFs rejected as having no readable pages are saved as unreadable, skipped
   on recovery, and named in the proposal's Issues section with an
   encrypted/password-protected hint;
3. each term retrieves at most five category/page/form candidates from the
   permission-filtered Redis index without another model call;
4. the primary model plans the whole batch using summaries, metadata, candidates,
   and tools when needed;
5. local validation/repair protects file coverage and action structure;
6. when form-backed new or existing targets exist, one focused completion call
   fills or partially updates them from compact schemas, current values,
   relationships, and assigned summaries, without tools or original files.

This avoids loading the whole workspace or every original file into planning.
The job checkpoints finalized uploads, saved summaries, the structural plan,
and completed submissions as separate stages, so a late retry resumes without
repeating completed provider stages.

### Autofill

Autofill uses a prompt-first, single-form contract. It receives the target's
name, description, schema, partial values, compact parent/category/document
context, and full readable projections for files attached directly to the
target. Task history, prior completions, sibling/page tasks, parent-page files,
and general workspace lookup are deliberately out of scope. Google Search is
available for missing public facts; `get_file` is exposed only when a stored
target attachment exists and has a two-round extracted-text/original-file
fallback. Existing page/task targets retain their durable form lock and
form-revision guard. Prompt observability identifies the prompt-first contract
as version 2 and the explicit submission-output contract as version 3. Autofill
does not attach an
untyped provider response schema: the prompt names exact field ids and formats,
and normal form submission validation removes unknown keys and normalizes values.
When stored files expose `get_file`, a summary-backed response that requests no
tool is accepted as the terminal answer instead of being regenerated.

Multi-file page upload is a separate synchronous path. When batch summarization
is selected, the HTTP upload route checks `AI.CREATE`, runs the Organize summary
prepass sequentially, and then saves the files. It does not use the shared
durable job.

## Context placement and growth

### Request layers

The effective request is larger than `Prompt.preview()`:

| Layer | Placement/lifecycle | Operational note |
|---|---|---|
| System instruction | Provider `system_instruction` | Stable and generally cache-friendly. |
| Rendered context/instructions | `Prompt.build()` | Organize puts stable instructions first; Ask/Create/autofill usually put dynamic context first. |
| Output prose/examples | End of rendered prompt | Can overlap provider response schema and application validation. |
| Tool declarations | Provider config | Up to 16 schemas; not shown by preview. |
| Response schema | Provider config/final pass | Material request overhead; not shown by preview. |
| Initial files/bytes | Separate content parts | Governed per file consumer, but not represented in preview text. |
| Tool calls/results | Appended after each round | Full results remain in every later request. |
| Tool-returned original files | Added as user file parts | Organize caps two per turn, not cumulatively per generation. |
| Structured-final instruction | New user turn after discovery | Adds one provider boundary and replays the accumulated transcript. |

### Stable prefixes and caching

Only Organize consistently calls `set_instructions_before_context()`, placing
stable policy before request-specific summaries and evidence. Ask, Create,
autofill, and direct builders normally place context first.

Gemini implicit caching is automatic. Explicit cached-content resources add
lifecycle, invalidation, regional, and privacy considerations and only make sense
when measured reuse exceeds the provider's minimum and retention cost. Current
Google documentation describes [implicit and explicit context caching](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview),
and the API also provides a [token-count operation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/count-tokens).
Calling CountTokens before every generation would itself add latency; prefer
actual response usage for production measurement and use preflight counting for
diagnostics, CI budgets, or unusually large requests.

### Tool-result accumulation

There is no generation-wide character/token budget for tool output. Several
handlers are bounded—workspace search defaults to 10 and caps at 25, category
pages cap at 10, task history caps at 50, and form instances and structured
filters cap at 100. Others return complete collections or projections:

- `list_workspace_resources` can return all visible categories, projects, model
  tasks, and forms;
- `get_page_details` includes every task and file by default;
- `get_page_tasks` and `get_page_file_list` return complete page collections;
- `get_entity` can return a rich `to_ai()` projection;
- `get_file` can include the complete extracted-text asset.

An exact-call cache prevents repeated handler work during one generation, but
the cached result is still returned to the model and replayed in later
transcript turns. A repeated cached `get_file` in a later round can also attach
the same original file again because the two-file Organize limit resets each
turn. There is no cumulative unique-file cap.

There is currently no semantic pagination or cumulative result limit.

### Guidelines and duplicated policy

`get_guidelines` defers specialized policy until it becomes relevant, which is
generally preferable to embedding every form/schema/report rule in every
request. Current bundles overlap substantially, however. Category/project/page
and task bundles repeat schema-type or form material, and the tool accepts only
one bundle name per call even though prompts encourage batching independent
calls.

Organize prompts say that particular bundles must be read before form creation
or schema evolution. This is prose guidance, not enforced tool mode. Successful
tool provenance is discarded after generation, so the validator cannot prove
that the required read happened. The tool accepts one bundle per call and does
not retain a guideline-evidence ledger.

### Output cleanup

`GenAI.cleanup()` removes only citation-shaped numeric markers such as
`[1]`, `[1, 2]`, and `[4-6]`, including recursively cleaned JSON strings.
Ordinary bracketed text such as `[urgent]` or `[source]` is preserved. If a
future provider format needs broader cleanup, add its exact syntax or use
grounding metadata rather than returning to a catch-all bracket expression.

## When and why tools are called

There are three separate decisions:

1. **The workflow chooses availability.** `enable_tools()` selects all or a
   named subset of the registered declarations. Ask/Create/Organize have
   different sets; autofill conditionally exposes only `get_file` when its
   target has stored attachments. `enable_search()` similarly exposes Google
   Search.
2. **The model chooses use.** The current provider configuration does not force a
   named function. Gemini decides whether it needs a function or search and can
   request multiple independent functions in one response.
3. **The application executes and validates.** The dispatcher normalizes
   references, runs permission-filtered handlers, caches exact calls, and returns
   results. Later application validators decide whether the final proposal is
   safe, but they do not currently validate the tool path used to reach it.

Google's current [function-calling documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/tools/function-calling)
supports multiple function calls in one turn. The dispatcher still executes
same-turn calls serially.

Google Search is enabled for Ask, Create, autofill, and several direct generation
flows, but not Organize planning. The model still decides whether to search.

## Deferred-job reliability

### Current durable contract

Deferred jobs use contract version 2 and store typed inputs, actor/policy
snapshot and target
fingerprints, parameters, client metadata, request identity, dispatch state,
status revision, a renewable five-minute lease, a 24-minute attempt deadline,
bounded progress phase, checkpoint, result/error, telemetry correlation, and
cleanup/notification delivery bits. The combined inline contract is
limited to 750 KiB. Cloud Tasks gives a shared AI
delivery up to 30 minutes. A production job with an initial notification also
gets one deterministic two-minute feedback task.

Quota failures receive application-owned delays of 60 and 300 seconds plus
positive jitter. Other classified transient failures use 60, 180, and 600
seconds. Infrastructure failures return a retryable response to Cloud Tasks;
domain/provider failures are converted into durable job state and separately
scheduled application attempts.

Autofill has a dependency wait before provider preparation: readable attached
files with summarization enabled must finish summarizing first. Pending
summaries reschedule the same job after 60 seconds without consuming a provider
retry; a terminal summary failure stops autofill and asks the user to fix or
remove the attachment. This keeps the provider prompt from racing the file
pipeline while preserving one user-visible autofill operation.

Once task dispatch succeeds, the runner is designed for at-least-once delivery.
Cloud Tasks itself should be assumed to deliver more than once, as described in
Google's [Cloud Tasks overview](https://docs.cloud.google.com/tasks/docs/dual-overview).
Deterministic task IDs deduplicate dispatch of the same job attempt; they do not
deduplicate two user submissions. Jobs receive internally generated random
idempotency keys when callers omit one.

### Lease, deadline, and nested retries

Foreground provider calls can attempt a request five times, with a 120-second
timeout per request boundary, for 408, 429, and selected 5xx responses. Deferred
provider calls use at most two SDK attempts, leaving longer recovery to the
durable job schedule. Ask, Create, and Organize still allow up to 50 tool rounds;
there is no tighter generation-wide semantic or cumulative budget.

Each delivery receives a 24-minute attempt deadline inside Cloud Tasks' 30
minute deadline. A five-minute lease is renewed every 60 seconds by a lightweight
heartbeat that also covers a blocking SDK call. `GenAI` checks the shared
execution control before and after provider stages and tool handlers, and the
runner checks it before durable apply. The two-minute reconciler grace prevents
an ordinary lease edge from immediately duplicating live work.

Nested retry ownership remains visible but bounded: the short deferred SDK
profile handles connection blips, while a later Cloud Task owns minute-scale
backoff. Stage checkpoints keep that later attempt from repeating completed
Organize upload, summary, and planning work.

Organize leaves the initial attempt on the provider's Standard tier and sets
Priority for every later deferred-job attempt, including every summary,
planning, repair, and completion generation in that attempt. Ask, Create, and
autofill do not have an equivalent application-level Priority-on-retry policy.

### Checkpoint boundaries

The generic runner persists a prepared final result after `adapter.prepare()`
returns. One-stage autofill and proposal generation use that final checkpoint.
Organize additionally persists these validated intermediate stages:

1. uploads finalized;
2. summaries ready;
3. structural plan ready;
4. submissions ready / ready to apply.

The `report.upload_manifest` and saved per-file summary/process state are the
durable authorities for the first two stages. The job stores bounded
stage markers and the expensive structural plan before form completion rather
than duplicating completed file records. The protocol keeps one
user-visible job rather than creating per-file child jobs.

### Durable start/outbox and idempotency

Job and notification are transactionally get/created from a
browser-generated operation UUID. The job persists a canonical immutable
request/spec fingerprint, dispatch state, deterministic task identity, and
dispatch time; UUID reuse with different job type, actor, inputs, parameters,
or client routing is rejected. Cloud Task dispatch remains outside the
Datastore transaction. An explicitly disabled production queue fails fast;
transient enqueue failure leaves the durable intent pending so the scheduled
reconciler can redispatch it. An intentional later run receives a new operation
UUID, so it is not suppressed by target-key idempotency.

### Queue isolation and operations

Setup creates a bare shared Cloud Tasks queue. AI jobs, ingress, cache
maintenance, and scheduled work can compete for the same web-service capacity.
The application owns bounded job status/recent-operation views and a
five-minute stale-job reconciler. Owner-triggered retention cleanup removes
completed terminal jobs alongside AI Analytics records while preserving active
or delivery-pending work. Automatic compaction and a Cloud Tasks queue-lag
dashboard remain absent. There is no dedicated AI or utility queue.

Relevant operational signals are queue depth, oldest task/job age, stage
duration, running count by type, retries, quota exhaustion, lease loss, and
terminal-delivery failures. Google documents the available
[Cloud Tasks monitoring metrics](https://docs.cloud.google.com/tasks/docs/monitor).

### Cancellation, drift, and retention

Cancellation writes a `CANCELLED` tombstone, revokes the lease/token, and
deletes known deterministic tasks; replacement report work similarly writes a
`SUPERSEDED` tombstone. A running HTTP request stops when execution control sees
the revoked/replaced claim. Deferred-job persistence uses lease-token
compare-and-set, and apply reloads authorization/target state immediately before
its final active check. A domain mutation that cannot share a transaction with
the job still has a small validate-to-write race.

The reconciler fails work older than three hours, clears active claim fields,
and completes cleanup and durable terminal state before considering a
job delivered. Terminal records remain retained and can duplicate large
proposal/checkpoint data. Automatic compaction is not implemented.

## Frontend communication

### Completion contract

- The job's `status_revision`, terminal status, and destination metadata are
  durable.
- `operation` subscriptions return that bounded projection through `/l/poll`.
- A matching per-job Redis status revision verified during the last minute
  lets an owner quiet poll skip that durable-job row. Cache misses, mismatches,
  and verification-due entries reload and repair only the requested jobs;
  collaborator checks always load durably for authorization. Notification
  mutations use a separate expiring Redis projection and cannot invalidate an
  operation hint.
- A terminal result fetches authoritative destination HTML/data; it never
  carries AI context or output in the polling payload.
- Notification entities are saved durably; their post-commit Redis generation,
  revision, and count reach active tabs through `/l/ping`, existing poll traffic,
  or one cold-cache seed poll.
- `lp-deferred` remains online-only and does not replay later against
  potentially changed permissions or target state.

### Shared status reconciliation

Browser-acknowledged deferred operations install an `operation` subscription
with the shared coordinator and refresh the declared destination at terminal
state. It:

- batches all active operations in one request;
- echoes each job's durable status revision and skips only fresh matching owner
  projections, with bounded durable verification;
- exposes only type, state, coarse phase, retry time, destination, and terminal
  outcome/revision—not checkpoint, prompt, inputs, or token;
- uses adaptive backoff, jitter, and visibility/connectivity checks;
- stops cleanly when the view/widget is destroyed;
- rejects stale/superseded operation revisions before reconciliation.

Standalone file OCR/summary converge through durable Notification entities,
their expiring Redis badge/list projection, and the watched entity fingerprint.
Collaborative documents use their separate revisioned Redis contract.

### Prompt preview

`Prompt.preview()` displays the system instruction and rendered prompt string.
It does not automatically show provider configuration, actual tool declaration
schemas, response schema, inline/file parts, later tool calls/results, or the
structured-final request. Ask/Create previews are reasonably representative of
the initial static text but cannot predict dynamic retrieval. Organize preview
is less representative: it uses upload metadata before the deferred job finalizes
uploads, creates summaries, and builds retrieval candidates, and it cannot show
the later completion generation.

The UI calls this **Initial Prompt** and explains that later permitted
tool/search context is dynamic. It does not show a bounded static/dynamic
manifest.

On a direct-upload-backed form with selected files—most notably Organize—clicking
Initial Prompt runs `prepareSubmit()` and preuploads/reuses those files
before the explain role is appended. Preview is not metadata-only.

## Operational measurement and evaluation

### Baseline metrics

Collect distributions by workflow, stage, actual model, service tier, and job
attempt:

- queue-to-start and queue-to-terminal duration;
- provider calls, tool rounds, calls per round, and same-turn serial duration;
- prompt/cached/output/thought/total tokens;
- tool result characters/tokens, truncation, cache hits, and attached originals;
- structured-final and repair call frequency;
- validation failure, local repair, model repair, safe fallback, and terminal
  failure rates;
- SDK retry, durable retry, quota, timeout, lease loss, and deadline outcomes;
- operation-poll latency, terminal reconciliation, and notification refresh;
- job depth/age, stage resume, duplicate operation, cancellation, and drift
  conflict counts.

Use representative production telemetry where policy permits and synthetic
large-workspace/file fixtures for controlled limits. Managed-local wall-clock
provider timings are not a stable performance baseline. Do not set an arbitrary
cache, concurrency, retention, or pagination threshold before observing the
data distribution and provider limits.

### Evaluation gates

An optimization should advance only when it:

1. preserves permission filtering and deterministic application safety;
2. passes the Ask/Create/Organize/autofill corpus and validators;
3. reduces the targeted call/token/latency/error metric on a representative
   workload;
4. does not materially increase repair/fallback, missed evidence, quota bursts,
   or user-visible conflicts;
5. has a documented rollback and compatibility path.

## Documentation conventions

- Keep current architecture here, supporting tool details in
  `BACKEND_TOOLS.md`, and route/browser contracts in `BACKEND_WEB.md`.
- Use explicit checkpoint nouns: deferred-job provider checkpoint,
  `report.upload_manifest` ingestion checkpoint, or `report.result` execution
  ledger.
- Describe terminal operation status as a refresh signal, not a success event.
- Do not describe deterministic Cloud Task IDs as user-operation
  deduplication.

## Primary external references

Provider and Cloud Tasks behavior changes over time. Recheck these primary
sources before implementing provider-specific work:

- [Google function calling](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/tools/function-calling)
- [Google token counting](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/count-tokens)
- [Google context caching](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview)
- [Google custom API-call labels](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/add-labels-to-api-calls)
- [Cloud Tasks overview and delivery model](https://docs.cloud.google.com/tasks/docs/dual-overview)
- [Cloud Tasks monitoring](https://docs.cloud.google.com/tasks/docs/monitor)
- [Cloud Tasks App Engine handler deadlines](https://docs.cloud.google.com/tasks/docs/creating-appengine-handlers)
