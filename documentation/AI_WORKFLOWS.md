# AI Workflows

## Unified reports

The homepage has one **Create a Plan** panel, subtitled “Organize files, create
structure, or ask a question,” with the existing upload, screenshot-paste,
prompt-preview, and report-review controls. A prompt and files are individually
optional; at least one is required. Files alone request filing. Questions can
use files as evidence without proposing their placement. Mixed questions and
changes stay in one report, including later revisions before execution.
On-site plan titles use the request text, a single filename, or a file count
without an AI prefix. Request-based titles retain the 80-character truncation.

Native planning and revision prompts and the external plan contract share the
same personal-Page guidance: the supplied `personal_page` is the authenticated
user's editable Page, and it does not appear in workspace search. Keep that
instruction in the shared guideline constant rather than only one entry point.
Selected `create_task` guidance also supplies the same scheduling rules to native
and external callers, including one-time due dates and recurrence semantics.

`POST /tools/ai` and `/tools/ai/direct-upload` replace the three old routes.
`REPORT_AI` runs `AIReportAdapter` and `tools/ai/planner.py`. There is no intent
router, upload-dependent action profile, or separate completion-model stage.
The report conversation has 17 common workspace read tools and Google Search.
Its initial structured output contract is compact: summary, optional
answer_markdown, confidence, issues, actions, and file_usage. The model obtains
exact action schemas and their guidance with
`get_guidelines(task="report_actions", actions=[...])`; actions must be a
nonempty selection. The shared validator checks the complete proposal and can
return errors to the same conversation twice for correction.

`AI.ASK` permits answers and evidence files. `AI.CREATE` additionally permits
proposals, constrained by live workspace permissions. Available actions do not
depend on whether files were uploaded. Jobs recheck entitlement before publishing
mutations; deterministic browser execution also checks resource permissions.
External clients use their own model and do not require provider entitlement.

Each upload has exactly one `{file, usage}` entry in the report's `file_usage`,
where usage is `evidence` or `organize`. Organize files require an executable
attachment destination; external proposals additionally supply one summarize_file
action and two retrieval terms for each organize file. Evidence files require
neither action. Native jobs checkpoint finalized uploads and summary preparation
before the single planning conversation, then checkpoint the validated proposal
and file_usage before publication.

A proposal contains summary, optional answer_markdown, confidence, issues, and
actions. Markdown is sanitized by the server. `output_kind` is derived from
actions: empty means answer, otherwise proposal. Answers complete immediately;
proposals become ready for browser review. Revisions may cross that boundary
until execution begins. Approval, execution ledgers, and skip controls use
the existing deterministic report runner.

Generation and revision can be cancelled from report list/detail views or AI
Analytics. The control is bound to the exact operation; it requires the creator
or Analytics administrator, without a provider entitlement. Initial cancellation
retains a visible cancelled report with **Retry generation**. Revision cancellation
restores the saved response. Retry creates a fresh job and planning lifetime.

Report planning has a ten-minute lifetime, including queue waits, and each worker
attempt is limited to nine minutes. Provider calls are cancellable, with one
transient retry in the current conversation. Interrupted jobs without a validated
proposal require manual Retry. See [Backend Jobs](BACKEND_JOBS.md) for recovery.

## Upgrade boundary

Pause intake and drain deferred report/email jobs before upgrading. Do not
migrate saved reports, proposals, or old job checkpoints. New reports carry
format_version=2. Leftover old or structurally incompatible reports render
`this plan is no longer available` in lists and details, with the normal Delete
control and no polling, execution, or revision. Deleting a report preserves
files that have workspace references.

Email routing uses the code-defined `ai` alias. Installation settings retain
operator choices and provider credentials; workflow changes neither migrate
their email envelope nor require rewriting generated settings. Runtime ignores
saved workflow policy metadata and uses code-defined routing and limits.
There are no old route, MCP starter, or worker aliases. External contract version
10 requires file_usage and rejects old submission contracts. Upgrade the app and
MCP service together.

## Autofill

Autofill is a direct mutation for one Page or Task form. Its prompt includes:

- target name, description, schema, and partial submission;
- compact parent Page and Category context for Tasks;
- the target document where applicable; and
- readable Files attached directly to the target.

Existing answers use the same exact field-ID projection as `get_schema`, including
typed table cells. Labels are context, never submission keys. Autofill validates
the response against the target's effective schema using the same detached field
validator as report planning. Unknown IDs and invalid values enter the shared conversation
correction loop (at most two corrections); generation is marked validated only
after this check succeeds. Existing nonempty answers, including false and zero,
remain authoritative. Guarded apply validates all new values before mutation and
preserves existing stored answers without converting them through AI text again.

It excludes Task history, sibling Tasks, completed Page Tasks, parent-Page Files,
and general workspace lookup. Google Search may supply focused public facts.
`get_file` appears only when a stored target attachment exists and is capped at
two rounds.

Autofill waits for enabled attachment summaries. A pending dependency reschedules
without consuming provider retry; a failed summary stops with an actionable
message. One-off prompt uploads are copied to a deterministically keyed File
only after successful guarded apply and are cleaned up on any terminal result.

Page/Task Autofill acquires a durable `form-autofill` lock. Submit, quick-edit,
and default-field routes reject conflicting mutations until terminal cleanup.
The worker checks current authorization, active lock ownership, and a
form-specific revision immediately before apply.

Multi-file Page upload summary is a separate synchronous route path. It checks
`AI.CREATE`, runs the shared report summary prepass, then saves the Files.

## File summary

File summary uses the utility model and the file's configured extraction path.
Provider input-limit results become clear domain errors rather than application
exceptions. File processing is dispatched only after the File and selected
options are durable. If summary and extraction are both selected, terminal
delivery starts one deterministic extraction successor even when summary
fails.

DOCX/XLSX files without a provider-readable attachment use the bounded OOXML
text fallback. Unsafe packages fail before the model call. When safe XML,
worksheet, row, cell, time, or prompt-text traversal reaches its fixed ceiling
after producing useful text, the model receives that prefix with an explicit
partial-extraction note.

## Reviewed report execution

The cohesive-update preparation service is
`lagniappe/core/tools/entity_patches.py::prepare_patch`. It accepts resolved
entity references and returns detached writes, complete before/after values,
and removed answers. Omitted fields are preserved. A Form
reassignment requires every target answer field explicitly; an unchanged Form
accepts selected answer patches. Completed tasks and pending Form migrations
are rejected. Project ordering must contain each existing model task once.
The writes use the ordinary mutation executor, including its Form migration and
completion-transition checks. Preparation itself does not save.
`reporting/entity_updates.py` resolves exact references and successful earlier
action outputs through this service. Its review snapshot binds action content
and Form definitions; execution rejects missing dependencies, changed proposals,
and changed Form schemas before returning any writes. The report
runner must persist those writes together with its execution receipt.
The native planner, REST/MCP submission, browser review, and forward runner use
this preparation layer. Earlier Form/model creations are previewed without
writing workspace records. Failed or skipped dependencies prevent dependent
updates, including paired description cleanup. Read `view="edit"` for complete
descriptions, exact answer IDs, revisions, and ordered Project models. Task
edit reads are paginated and share schemas within each response.

Document scope remains append-only for AI/MCP. Inline changes, replacement, and
removal of existing document content belong in the editor. The cohesive-update
upgrade does not add `update_document` or new block-editing/replay machinery;
plans requiring existing text to change must identify that manual editor step.

The homepage Plans & Reports panel has independent Active, Executed, and Answers
filters. Active includes unfinished proposals and pending requests (including
failed and revising states); Executed includes completed proposals.
Saved answers appear under Answers. Counts include hidden reports. The browser
remembers each user's choices, initially Active and Answers, and reveals a newly
created report's category. Unavailable old reports remain visible under Active
with their normal Delete control.

List snippets flatten Markdown to plain text and show at most five lines at
the current screen width. Full summaries remain available in each report.
Document creation and append details show plain-text previews limited to ten
lines, with a control to expand the full text. The stored proposal retains the
complete executable HTML; only its review display is shortened.

On-site and external schema plans carry exact converted values or explicit
unresolved reasons in `conversions`. The planning model prepares these from the
complete preview; the server validates them before review. Execution applies
the reviewed candidates without another model call. Todo conversion preserves
identifiable list items and tasks, but treats prose reporting an absence of items
as unresolved. Summaries describe proposed values, not changes already saved.

Selecting Executed alone exposes bulk history deletion with one count-based
confirmation. `DELETE /tools/reports/executed` accepts JSON `{"keys": [...]}`
and returns `deleted`, `skipped`, and `failed` key lists. The server rechecks
creator ownership and current completion, then guards each deletion against a
changed report or active API claim. Only the confirmed keys are considered;
later completions are retained. Cleanup shares the individual report-delete
path: unreferenced report-only uploads are removed, while workspace changes
and attached files remain. Missing, changed, busy, or ineligible reports are
skipped; individual failures do not stop the remaining deletions.

AI proposals may include reviewed create, move, rename,
attach, schema, and submission actions. `reporting/execution/` owns deterministic
application; the model is not called during execution.

`execution/actions/registry.py` owns the action catalog, completeness check,
and required-placement lookup. The runner selects an adapter there;
`ReportActionAdapter.apply()` invokes that adapter's bound handler and normalizes
its result without looking back into the registry. Checkpoint and recovery
helpers retain their existing lifecycle responsibilities.

Because execution is provider-free, viewing, skipping actions, running,
retrying and deleting a saved report do not require `User.ai_access`.
They remain creator-bound browser operations, and every action rechecks current
resource permissions. Generating or revising an internal report still calls the
configured provider and therefore retains its Ask or Create entitlement.

Supported action families include creation, cohesive `update_task`,
`update_model_task`, `update_project`, `update_page`, schema migration,
completion, document append, file attachment/movement, and explicit manual
cleanup suggestions. Superseded atomic update contracts and Undo are removed.

Each action records its idempotency key, before-state, expected committed state,
attempt count, and lifecycle status. Retry validates completed work and
reconciles interrupted writes. Changes are atomic per action, not across a plan.

After execution begins, **Create corrective plan** creates a new linked report.
The source must belong to the creator and have stopped; ambiguous writes and active Form
migrations must be reconciled first. The new report contains a bounded snapshot
of proposal/outcomes and reads current state to propose additional changes.
All embedded snapshot properties are excluded from Datastore indexes, including
long answer HTML, task descriptions, and execution notes.
Draft corrections leave source retry available. Browser approval checks the
source snapshot and atomically supersedes its execution; subsequent retries of
the source are rejected. External `start_plan`/REST creation accepts
`revises_plan_id` without provider access. Browser corrections require Create
access and create a site-origin report even when the original came from MCP.
The correction controls, generation/revision routes, and queued jobs enforce this
entitlement, including retries and revisions of the corrective proposal. Ordinary
answer revisions still require Ask access. Shared
evidence survives deletion while another linked report still references it.
Automatic record deletion is unsupported; identify manual cleanup explicitly.

Task actions with completion evidence may reuse exactly one matching editable
Task; the newest event stays on the live Task and earlier dates become history.
Ambiguous matches remain separate.
One source-dated completed occurrence uses one `create_task` with `completed=true`,
the source's `completed_on`, and an exact `task` reference when reusing a Task.
It does not require an extra completion for today. `complete_task` uses execution
time and cannot preserve a historical source date.

`complete_task` is distinct from historical `create_task` occurrences: it calls
normal Task completion with the executing actor and validates required fields.
It preserves submission values, descriptions, assignments and attachments,
except that normal recurrence may archive the completed occurrence and reset
the next occurrence immediately. Its completion history key is preallocated for
retry safety. Put field updates before completion and make it depend on them.
The existing scheduling policy is unchanged: near-term tasks reopen immediately
so the next occurrence appears on the homepage; other production completions
retain their midnight reopening job. Nonproduction still reopens immediately.
Already-completed Tasks are unchanged. Corrections preserve recorded completion history.
New imported completion events save their answers before capturing the original
answers and Form generation. Unknown generated field IDs are rejected before
existing values are reset. Normal Task AI reads use flat current values and the
current Form. Historical AI reads resolve the recorded generation; missing
originals are marked unavailable and recoverable answers use their saved IDs.

## Workspace semantics

Across workflows:

- Categories are collection scopes.
- Pages are durable subjects within those scopes.
- Files are source artifacts.
- Tasks are actions or occurrences concerning a Page subject.
- Forms model repeated structured values, not arbitrary one-off metadata.

Keep these semantics in shared guidelines and validators so workflow prompts do
not drift into different workspace models.

## Reviewed Form schema updates

Both site AI and external agents use `update_form_schema`. Read the
`schema_evolution` guideline and call `preview_form_schema_update` before proposing
changes to saved values. The shared preparation layer records complete affected
identities and source preconditions for review, and the Form-change adapter
handles deterministic and AI conversions in the same guarded mutation workflow.
Both report origins supply strict candidates before approval and execute without
a provider. Native report planning binds and validates candidates inside its conversation
validation loop, before the complete result is checkpointed. Malformed candidates
can be corrected before review; exhausted corrections fail generation. Publication and execution still recheck current
preconditions. Missing, invalid or stale candidates prevent proposal publication
or execution; execution never fills in missing conversions. Builder AI conversion
uses the same adapter without a report and retains its utility-model instructions
and resumable batches. The 750 KiB schema-proposal limit applies to both report
origins; oversized changes require a smaller scope or Builder. See
[the external contract](AI_EXTERNAL_API.md) and [Form jobs](BACKEND_JOBS.md).

Schema preparation assigns stable, collision-free IDs when the author omitted
an action ID, including when approving an older saved proposal. Existing IDs and
conversion values are preserved. Schema-impact review uses the original action
positions, matching the skip controls, so opening an ID-less report does not
mutate it or require regeneration.

Report execution prepares actions in proposal order against one working entity
map. Earlier creations and edits are immediately available to dependent actions
without an intermediate save or reload. Each entity's final state is written once;
shared owner touches and property masks are merged by the mutation planner.
Model creation loads the existing Project order before appending, while new
Projects start with an empty list. Category Form registration resolves any stored
but unloaded Form members before extending the list, preserving sibling Forms.
Groups commit at 50 actions or approximately 4 MiB of prepared root data. These
are general size boundaries, not boundaries between entity types or dependencies.
Form migrations flush prepared work before starting their asynchronous child job.

The report and its action results commit with the workspace writes in a guarded
transaction. A batch receipt distinguishes rejected writes from a lost commit
response. Retry resumes uncommitted groups; it does not replay successful creates
or reject completed work because it was subsequently edited. A preparation failure
discards that group's staged writes; recoverable skips rebuild only the uncommitted
group. There is no automatic per-action save/reload retry loop.

Approved patches have ordinary editor overwrite semantics. They apply the selected
fields to the working entity and retain omitted fields. Execution checks permissions,
values and Form definitions, but does not compare every field with the review's
before-state or guard whole linked Pages, Projects, and model tasks. Shared Form
migration/generation and completion fences still protect answer interpretation.
Transaction guards are consumed after a successful save, including guards on
Reports and Tasks reused in memory.

Public plan reads remove internal review snapshots before resolving references.
Temporary preview entity IDs never enter workspace lookups; public proposals
retain the original action references for round trips.

Document HTML and CRDT snapshots upload to isolated Storage objects during
preparation and populate the working entity's assets dictionary. Document references,
named pre-edit history, and action receipts join the batch. An existing Page receives
an assets/history/modified mask unless another action also edits its fields. One
pre-edit document version is retained per Page per batch. Collaborative state and
asset references are checked before committing; unsaved collaborative edits still
require reconciliation. A durable pending-publication list lets recovery finish
collaborative publication after a committed batch without appending text again.

For a report completed with skipped updates, use Create corrective plan to propose
only the remaining changes against the current workspace. The post-execution control
explains that this creates a separate linked report requiring review and approval;
unexecuted proposals retain the Revise Plan control.
