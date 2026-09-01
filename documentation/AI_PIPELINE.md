# AI Pipeline

Lagniappe treats model output as prepared data or a reviewed proposal, never as
authority to mutate the workspace directly. AI requests use permission-filtered
read tools, application-owned validation, durable jobs, and deterministic
application handlers.

Use the focused guides alongside this overview:

| Guide | Covers |
| --- | --- |
| [AI_CONTEXT.md](AI_CONTEXT.md) | Prompt construction, model calls, tools, context growth, validation, and observability. |
| [AI_WORKFLOWS.md](AI_WORKFLOWS.md) | Ask, Create, Organize, Autofill, file summary, and reviewed report execution. |
| [AI_EMAIL.md](AI_EMAIL.md) | Resend setup, signed inbound email, workflow routing, and feedback. |
| [AI_EXTERNAL_API.md](AI_EXTERNAL_API.md) | Bearer credentials, shared read tools, uploads, and provider-free Organize proposals. |
| [BACKEND_JOBS.md](BACKEND_JOBS.md) | Durable job records, locks, leases, retries, recovery, and browser status. |

## End-to-end path

```text
Browser form
  -> route validates request, resource permission, and AI tier
  -> route persists the target or pending AIReport
  -> DeferredJobs.start(typed inputs and browser destination)
  -> DeferredJob + Notification + optional target lock commit
  -> Cloud Task carries only the job key
  -> worker reloads actor, inputs, and job
  -> adapter reauthorizes and prepares output
       -> Prompt composes policy, context, files, tools, and output contract
       -> GenAI resolves and pins a model for this generation
       -> Gemini request and optional read-tool rounds
       -> structured final response when the workflow uses one
       -> application validation and repair
  -> adapter checkpoints prepared output
  -> adapter reloads state, checks drift/lease/lock, and applies idempotently
  -> terminal cleanup, Notification, and status revision commit
  -> /l/poll reports terminal invalidation
  -> browser refetches the authoritative destination
```

The polling payload never transports prompts or generated content. It returns
only bounded state, phase, retry timing, revision, and destination metadata.
Terminal means the operation has reached an outcome; the refetched report or
target determines whether that outcome succeeded.

External clients can enter the report pipeline without invoking the configured
provider. The external-agent API creates a draft report, exposes the shared
read-tool registry, and validates a tool-specific Ask, Create, or Organize
contract. Ask publishes a completed read-only answer. Create and Organize
publish at the normal ready-for-review boundary and can enter the same
deterministic execution adapter through a proposal-scoped execution key.

## Safety boundaries

- Workspace function tools are read-only and enforce the requesting User's
  view permissions.
- The route and worker both enforce ordinary resource permissions and the
  required `AI.ASK` or `AI.CREATE` entitlement.
- Report output uses typed action contracts, deterministic normalization,
  repair, and review-only fallback for unsafe actions.
- Report application is a separate user-approved operation with its own
  resumable per-action ledger and undo checkpoints.
- Autofill and other direct mutations checkpoint generated values, reload
  current state, and compare a workflow-specific target revision before apply.
- Cloud Tasks carries only a durable key; actor, inputs, permissions, and
  request identity are reloaded from application data.
- Redis accelerates status polling but never authorizes an operation or owns
  its terminal result.
- Generation summaries exclude prompts, outputs, tool arguments/results, file
  content, and User/entity identifiers.

## Ownership map

| Boundary | Owner |
| --- | --- |
| Prompt structure and preview | `tools/ai/prompt.py` and workflow builders. |
| Provider lifecycle | `tools/ai/core.py`. |
| Function declarations and execution | `tools/ai/functions.py`, `function_definitions/`. |
| Workflow context and stages | `ask.py`, `create.py`, `organize.py`, `autofill.py`, `email_router.py`. |
| Proposal schema and validation | `tools/ai/reporting/contracts/`, `proposals/`, `completion/`. |
| Durable request values | `properties/deferred_job_request.py`, `deferred_job_dispatch.py`, `deferred_job_lifecycle.py`. |
| Job orchestration | `tools/deferred_jobs/` and `tools/database/deferred_jobs.py`. |
| Deterministic report apply/undo | `tools/ai/reporting/execution/`. |
| Reviewed proposal display | `tools/ai/reporting/display/`. |
| Browser completion | `/l/poll`, `PollingCoordinator`, `DeferredOperationManager`, and destination widgets. |

## Three checkpoint systems

Use precise names because the systems have different ownership:

1. A deferred-job checkpoint stores prepared adapter output before final apply.
2. `AIReport.upload_manifest` records per-file Organize ingestion progress.
3. `AIReport.result` is the action-by-action execution and undo ledger after a
   proposal is approved.

Do not use one checkpoint as authority for another stage.

## Request and authorization

The browser supplies an operation UUID. `DeferredJobs.start()` binds it to a
canonical fingerprint of job type, actor, inputs, parameters, and client
destination. Repeating the same request is idempotent; reusing the UUID for
different work is rejected.

The worker reloads the actor and inputs at claim time and again before apply.
Adapters declare their required AI tier. Ask needs `AI.ASK`; generation,
organization, execution, autofill, and file summary need `AI.CREATE`. Domain
authorization—such as edit access to an Autofill target—is checked separately.

## Preparation and application

Most adapters follow `prepare -> checkpoint -> inspect -> apply`:

- `prepare` may call the provider but must not perform the final domain
  mutation;
- the job stores the validated prepared result;
- `inspect` determines whether a previous delivery already applied it; and
- `apply` performs an idempotent domain mutation after reauthorization, drift,
  lease, and lock checks.

Report generation saves a proposal only. **Execute Proposal** creates another
deferred job that applies the reviewed actions through `report.result`. Each
action has a deterministic idempotency key, before-state, expected committed
state, and applying/complete/failed checkpoint. Retry reconciles an interrupted
action before invoking its handler again. Undo uses the same checkpointed model
in reverse.

## Browser completion

An `lp-deferred` submit is online-only. The acknowledgement installs an
`operation` subscription. `/l/poll` batches active jobs and returns a monotonic
status revision. On terminal state the browser rejects stale revisions and
fetches the declared authoritative replacement route. A Page/Task Autofill lock
also appears through `form-lock`, allowing another tab or a reload to restore
the progress state without fingerprint drift.

See [FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md) and
[SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md).

## Before changing an AI path

1. Identify the route permission, required AI tier, and durable input owner.
2. Keep tools read-only and permission-filtered.
3. Put dynamic response validation in application code, not only a provider
   schema or prompt instruction.
4. Decide which expensive stage needs a durable checkpoint.
5. Define target drift, idempotency, failure cleanup, and browser destination.
6. Record privacy-bounded observability that can distinguish provider, tool,
   validation, and queue failures.
7. Cover preparation, duplicate delivery, retry, authorization change, drift,
   apply, and terminal reconciliation at the smallest faithful test layer.
