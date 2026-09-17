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
until execution begins. Approval, execution ledgers, skip controls, and undo use
the existing deterministic report runner.

## Upgrade boundary

Pause intake and drain deferred report/email jobs before upgrading. Do not
migrate saved reports, proposals, or old job checkpoints. New reports carry
format_version=1. Leftover old or structurally incompatible reports render
`this plan is no longer available` in lists and details, with the normal Delete
control and no polling, execution, revision, or undo. Deleting a report preserves
files that have workspace references.

Email routing uses the code-defined `ai` alias. Installation settings retain
operator choices and provider credentials; workflow changes neither migrate
their email envelope nor require rewriting generated settings. Runtime ignores
saved workflow policy metadata and uses code-defined routing and limits.
There are no old route, MCP starter, or worker aliases. External contract version
9 requires file_usage and rejects old submission contracts. Upgrade the app and
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

The homepage Plans & Reports panel has independent Active, Executed, and Answers
filters. Active includes unfinished proposals and pending requests (including
failed, revising, and undone states); Executed includes completed proposals.
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
path: report-only uploads and undo history are removed, while workspace changes
and attached files remain. Missing, changed, busy, or ineligible reports are
skipped; individual failures do not stop the remaining deletions.

AI proposals may include reviewed create, move, rename,
attach, schema, and submission actions. `reporting/execution/` owns deterministic
application; the model is not called during execution.

Because execution is provider-free, viewing, skipping actions, running,
retrying, undoing, and deleting a saved report do not require `User.ai_access`.
They remain creator-bound browser operations, and every action rechecks current
resource permissions. Generating or revising an internal report still calls the
configured provider and therefore retains its Ask or Create entitlement.

Supported action families include:

- creating Pages, Tasks, Forms, Projects, and Categories;
- attaching or moving Files;
- moving Pages or Tasks;
- adding a Category or Form to a Page;
- renaming one exact entity;
- updating exact existing submission fields;
- completing one exact existing Task with `complete_task`;
- adding fields or missing options to a Form schema; and
- recording a manual Page-deletion suggestion instead of deleting it directly.

Each action records its idempotency key, before-state, preallocated outputs,
expected committed state, attempt count, and lifecycle status. Retry validates
the completed prefix and reconciles an interrupted action. Undo restores prior
parents, schemas, submissions, and relationships and deletes only report-created
entities/links. Interrupted undo resumes from its own checkpoints.

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
Already-completed Tasks are unchanged. Undo reopens through the normal archive
boundary and restores compatible prior active answers and
attachments. The original completion remains in history, including for an
occurrence that recurrence already reopened. Later edits or incompatible form
changes stop the undo. Repeating an undo after an interrupted save recognizes
the restored active state without deleting or duplicating the completion.

Undoing an imported event on a reused Task would rewrite a recorded completion;
that correction remains unavailable and fails before changing answer assets.
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
