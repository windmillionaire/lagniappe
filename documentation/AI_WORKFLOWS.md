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

Page generation distinguishes top-level Page metadata from attached form
submission. Without a form, `name` and `description` are generated directly.
With a form, canonical top-level values win and the corresponding form fields
mirror them consistently.

Create and Organize expose optional Page rich text to models as
`document_markdown`. Shared proposal validation renders it to sanitized,
editor-compatible `document` HTML before the proposal is stored. Existing
ready reports that already contain `document` HTML remain executable.

## Organize

Organize evaluates an upload batch as a whole:

1. finalize direct uploads one at a time and checkpoint `upload_manifest`;
2. generate and save a summary plus at most two search terms for each File;
3. query up to five Category/Page/Form candidates per term from Redis;
4. plan workspace structure with the primary model and read tools;
5. validate file coverage, references, action shapes, and ordering;
6. repair locally or through one model pass when needed; and
7. run a focused form-completion generation only for form-backed targets.

The stages `uploads_finalized`, `summaries_ready`, `plan_ready`, and
`ready_to_apply` are durable. A retry resumes without repeating completed
uploads, summaries, or planning.

Planning clusters Files by stable subject and chooses specific existing or new
Pages. It does not create one Page per document by default or use a broad
overview Page as a catch-all. A Category default Page form is proposed only
when nearly every Page is an instance of one small repeated schema.

Every uploaded File must appear in an executable attachment action with an
exact target. If repair cannot produce complete safe coverage, the result is a
review-only proposal. Large or unreadable Files remain represented by metadata
and visible issues so the proposal does not silently drop evidence.

An instruction-only Organize request uses Ask because no file placement stage
is needed.

## Autofill

Autofill is a direct mutation for one Page or Task form. Its prompt includes:

- target name, description, schema, and partial submission;
- compact parent Page and Category context for Tasks;
- the target document where applicable; and
- readable Files attached directly to the target.

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

Create and Organize proposals may include reviewed create, move, rename,
attach, schema, and submission actions. `reporting/execution/` owns deterministic
application; the model is not called during execution.

Supported action families include:

- creating Pages, Tasks, Forms, Projects, and Categories;
- attaching or moving Files;
- moving Pages or Tasks;
- adding a Category or Form to a Page;
- renaming one exact entity;
- updating exact existing submission fields;
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

## Workspace semantics

Across workflows:

- Categories are collection scopes.
- Pages are durable subjects within those scopes.
- Files are source artifacts.
- Tasks are actions or occurrences concerning a Page subject.
- Forms model repeated structured values, not arbitrary one-off metadata.

Keep these semantics in shared guidelines and validators so workflow prompts do
not drift into different workspace models.
