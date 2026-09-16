# AI Workflows

Lagniappe uses one provider and durable-job foundation for several workflows,
but each workflow owns its context, tools, validation, checkpoints, and apply
contract.

## Comparison

| Workflow | Context and tools | Provider stages | Durable outcome |
| --- | --- | --- | --- |
| Ask | Question/report context; Search, workspace reads, Task history, filter schema/query. | Initial/tool loop, structured final, optional repair. | Read-only answer. |
| Create | Creation request and workspace concepts; Search and workspace reads. | Initial/tool loop, structured final, optional repair. | Reviewed creation proposal. |
| Organize | Uploaded-file metadata, saved summaries, retrieval candidates, workspace reads. | Utility summaries, primary plan/tool loop, optional repair, optional form completion. | Reviewed organization proposal. |
| Autofill | One target, form, partial submission, parent context, direct attachments. | One JSON/tool conversation and local validation. | Submission applied to the target. |
| File summary | One File and summary options. | Utility-model generation with extraction/provider fallback. | Summary/process state on the File. |
| Report execution | Approved proposal; no model tools. | No provider call. | Action ledger, domain mutations, and optional undo. |

Lagniappe preserves canonical MIME types on stored Files and downloads. At the
Gemini request boundary, recognized Markdown (`text/markdown`) and vCard
(`text/vcard`) inputs are sent as the provider-supported `text/plain` media type;
their content remains unchanged. The same normalization applies to stored-file
URI parts and direct inline autofill attachments.

## Ask

Ask uses a lean initial prompt and retrieves workspace data on demand. Its
tool set includes shared entity/file reads, Task history, saved-filter schema,
and permission-filtered structured filter queries. A result requires a nonempty
summary, confidence from 0 to 1, optional Markdown, and an empty actions array.
The validator converts the Markdown through the shared sanitized,
editor-compatible renderer and stores the resulting answer HTML.

The `AskReportAdapter` checkpoints the prepared answer before publishing it to
the `AIReport`. Ask is always read-only, so a valid answer becomes complete. A
request for workspace changes is redirected to Create or Organize rather than
being represented as Ask actions.

Email-origin Ask may summarize attached evidence first. Those Files remain
read-only evidence and do not grant Organize placement actions.

## Create

Create uses the same small-prompt/read-tool pattern for Pages, Categories,
Projects, Forms, and Tasks. Its output is always a proposal. It may use Search
for public facts and workspace tools for existing structure, then passes the
shared proposal contract and repair boundary.

The in-app Create prompt includes the authenticated user's guaranteed editable
personal Page reference directly, matching the external Create plan contract.
The same reference also remains available from `list_workspace_resources`.

Create Page proposals distinguish top-level Page metadata from attached form
submissions. Without a form, `name` and `description` live directly on the
Page action. With a form, canonical top-level values win and the corresponding
form fields mirror them consistently.

Create and Organize expose optional Page rich text to models as
`document_markdown`. Shared proposal validation renders it to sanitized,
editor-compatible `document` HTML before the proposal is stored. Existing
ready reports that already contain `document` HTML remain executable.

Updates to normal Page documents use `append_page_document`: preserve existing
content and append the requested text with a server-generated source/time quote
before the addition. Form-builder generation uses a separate prompt and may
replace static instruction text in its local draft; that replacement behavior
does not apply to normal document updates.

## Organize

Organize evaluates an upload batch as a whole:

1. finalize direct uploads one at a time and checkpoint `upload_manifest`;
2. generate and save a summary plus at most two search terms for each File;
3. query up to five Category/Page/Form candidates per term from Redis;
4. inspect targets and schemas, then author the complete proposal including final
   form values and all requested updates/completions/document additions;
5. validate file coverage, references, action shapes, schema conversions and ordering;
6. apply safe mechanical corrections, or return the precise validation error to
   the same model conversation for at most two correction attempts.

A valid candidate is accepted directly, without another model rewriting its JSON.
Correction turns retain prior tool results and the exact-call cache; they share
one pinned model and the existing tool-round budget. Technical validation failure
raises a generation error if corrections are exhausted. It does not become a
generic question with a stale success summary. Models may still propose
`needs_review` for genuinely ambiguous intent or conflicting evidence.

Planning preflight compares each requested outcome with its executable target
actions; summaries must describe only those actions and omissions belong in
review issues. Existing-target table patches are checked against current schemas
(and preceding schema updates), including internal-link resolution, before
acceptance. References to newly created action targets or newly assigned forms are checked
at execution.
Execution validates all patches on detached fields before changing a submission.
Table cells propagate validation errors to their table; a missing internal-link
record cannot silently disappear while its task is marked complete. Failed
updates block dependent completions. Older reports with skipped submission errors
display those errors instead of an unconditional “Work done.”

Finalized uploads remain report-only evidence before browser execution. They
are addressable through the owning report and its exact file references, but
are omitted from ordinary workspace search while they have no Page or Task
attachment. A successful attachment action makes the File searchable through
the normal post-commit cache refresh. This boundary is shared by API, email,
and on-site Organize uploads.

The stages `uploads_finalized`, `summaries_ready`, `plan_ready`, and
`ready_to_apply` are durable. A retry resumes without repeating completed
uploads, summaries, or planning. New `plan_ready` checkpoints include
`proposal_complete: true` and proceed directly to `ready_to_apply`. Older upload
checkpoints without that marker retain the legacy completion path so a deployment
update can resume an already-prepared structural plan safely.

Planning clusters Files by stable subject and chooses specific existing or new
Pages. It does not create one Page per document by default or use a broad
overview Page as a catch-all. A Category default Page form is proposed only
when nearly every Page is an instance of one small repeated schema.

Every uploaded File must appear in an executable attachment action with an
exact target. If corrections cannot produce complete safe coverage, generation
fails with its validation error. Large or unreadable Files remain represented by metadata
and visible issues so the proposal does not silently drop evidence.

Website, API/MCP, and email Organize support the same fileless existing-record
update profile, including `create_task` on editable existing Pages. A proposal
can create a destination Task and move existing files into it using
`move_file.data.to_task_action` plus `depends_on` referencing the earlier task
creation action. Other creation actions remain exclusive to Create or file-backed
Organize. Trusted intake origin and the absence of uploads select that
profile. Instruction-only website Organize requests now produce reviewed update
proposals. The email classifier can choose
Organize for an update without attachments, but does not discover targets itself.
The planner discovers exact editable records, reads relevant schemas, and
proposes bounded updates for the same browser approval and execution pipeline.
No additional toolbar option or top-level completion command is introduced.

The update profile omits upload summaries, retrieval prepasses, and secondary
form completion. Its planner authors final task submissions and field patches
directly, including on revision or validation repair. Once uploads are supplied,
normal file coverage and final-value obligations apply. External starters return a compact
action contract; `start_organize(actions=[...])` can include selected schemas in
that first response. Clients request additional schemas and guidance on demand.
Table-shaped patches are checked during proposal validation, so malformed row
arrays enter the existing proposal repair flow before browser review. Execution
also checks the current Form's exact column ids before saving any field patches.

## Autofill

Autofill is a direct mutation for one Page or Task form. Its prompt includes:

- target name, description, schema, and partial submission;
- compact parent Page and Category context for Tasks;
- the target document where applicable; and
- readable Files attached directly to the target.

Existing answers use the same exact field-ID projection as `get_schema`, including
typed table cells. Labels are context, never submission keys. Autofill validates
the response against the target's effective schema using the same detached field
validator as Organize. Unknown IDs and invalid values enter the shared conversation
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
`AI.CREATE`, runs the Organize summary prepass, then saves the Files.

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

The homepage Plans & Reports panel has independent Active, Executed, and Ask
filters. Active includes unfinished Create/Organize proposals (including failed,
revising, and undone states); Executed includes only complete Create/Organize
proposals. All Ask reports stay in Ask regardless of status. Counts include
hidden reports. The browser remembers each user's choices, initially Active and
Ask, and reveals a newly created report's category.

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

Create and Organize proposals may include reviewed create, move, rename,
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
a provider. Native Organize binds and validates candidates inside its conversation
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
