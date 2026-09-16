# External Agent API

Lagniappe exposes a versioned, REST-first API that lets a user run the same
permission-bounded read tools as the built-in AI workflows. Ordinary questions
and task lookups use plan-free reads and are answered in the conversation. Only
when the user requests saving an answer or workspace changes does the client
create a Plan. All requests share one contract; the server derives output_kind
from actions. Proposals require browser approval, and the API never executes
workspace mutations or calls Lagniappe's model.

The API is part of the application and is gated by the installation's AI and
external-AI policy. When enabled, authenticated non-public users may manage a
key and use plans and reads within their workspace permissions,
regardless of their per-user provider entitlement. That entitlement controls
Lagniappe's built-in provider calls; an external client uses its own model and
tokens. Revoking the user's API key stops clients using that key. The optional
remote MCP service has separately revocable ChatGPT and Codex OAuth grants.

## Installation policy and access paths

| Installation choice | Available AI entry points |
| --- | --- |
| `AI_ENABLED: false` | No built-in generation, external API/skill, or MCP access. |
| `AI_ENABLED: true`, `EXTERNAL_AI_ENABLED: false` | Built-in AI under normal per-user entitlements; no external API/skill or MCP access. |
| Both enabled | Built-in AI plus permission-bounded external access; normal setup manages the optional Cloud Run MCP service. |

Normal setup asks about AI and then external AI/MCP. Change those choices with
`./setup.sh ai` and deploy the resulting configuration. Model defaults are an
informational line during setup; change models in Admin → Site Settings → AI
Models. Saved reports and provider-free browser review, execution and undo
remain available within normal permissions even when generation is disabled.

Legacy settings without these flags preserve existing built-in and REST access.
That compatibility default does not automatically provision MCP: normal
deployment selects it only with an explicit external-AI choice or an already
saved `MCP_RESOURCE`. Eligible active non-public users may connect; there is
no separate actor list or client switch in installation configuration.

Direct REST clients use a user API key; MCP clients use the installation's
Cloud Run `/mcp` URL and authorize on the Lagniappe website. The skill is a thin
REST bootstrap, not a prerequisite for MCP. Neither path executes proposals.
Disabling external AI blocks existing credentials as well as new connections;
it retains credentials and cloud resources, so re-enabling may restore access
for unexpired credentials. Use explicit revocation to invalidate a credential.

See [configuration](INFRA_CONFIG.md#ai-policy-and-remote-mcp),
[deployment](INFRA_DEPLOYMENT.md#remote-mcp-service), and the
[implementation overview](EXTERNAL_AI_IMPLEMENTATION.md) for ownership,
installation order, and the evolution of these choices.

## Security model

- A user can have one active API key. Generating another key immediately
  invalidates the old one.
- Keys expire after 30 days and can be revoked from the user's own Settings
  panel. The full secret is shown only when generated; Datastore stores only a
  SHA-256 digest.
- `/api` and `/api/v1` accept `Authorization: Bearer ...` only. A browser login
  cookie is not an authentication fallback, and the API blueprints are
  CSRF-exempt for that reason. The opt-in remote MCP envelope additionally
  requires a verified Google workload identity and a dedicated user-token
  header; an OAuth access token is never accepted as an ordinary API key.
- API calls run as the authenticated user. Existing read-tool handlers enforce that
  user's normal entity permissions. Plan access is also bound to its creator.
- External-plan capability never adds workspace permission. Proposal validation
  and browser execution use the same live resource checks as ordinary UI work,
  so a permission removed after validation is honored at execution time.
- Every user has an editable personal Page. `/me`, each plan contract, and
  `list_workspace_resources` identify it explicitly because personal Pages do
  not appear in ordinary workspace search. A User and personal Page
  intentionally share one public hash; the returned object identifies the
  reference as `kind: "page"`, and proposal normalization maps it to the Page's
  executable key. This grants no additional access: read tools remain
  permission-filtered and deterministic execution still uses normal Page
  permissions.
- The bearer key can inspect permitted data and draft, validate, save, and
  revise reports. It cannot apply proposals. The agent must
  present `preview_url` and direct the user to the authenticated browser report,
  where the existing Execute control is the only approval and application path.
- Answer submission only validates and saves a read-only answer. It has no
  execution lifecycle or execution-shaped response fields.
- Ready proposals remain open to read tools and repeated
  submission. Each valid resubmission replaces the complete saved proposal.
  Once browser execution starts, the report status changes and the API rejects
  further reads or submissions for that plan.
- Existing entities are represented as `hash:<12-character-hash>` references.
  URL-safe Datastore keys are rejected in submitted proposals.
- API responses are `no-store` and include the non-secret
  `X-Lagniappe-Build-ID` marker; no CORS policy is added. Original-file URLs,
  when explicitly requested through `get_file`, are signed for five minutes.
- Limits are 60 general requests per minute and 100 Plan-start attempts per
  hour per user/IP, 100 tool calls per plan, and 100 proposal actions. The
  Plan-start allowance covers all requests; starting a
  report does not invoke a model or execute workspace changes. Each plan
  allows 20 files per plan, 30 MiB per file, and 50 MiB total.

## Remote MCP adapter

The Cloud Run service in `mcp/src/lagniappe_mcp/` contains its HTTP server,
API catalog, REST mappings, validation, result projections and file transfers.
It exposes `upload_files` for ChatGPT attachment objects and
`prepare_file_uploads` / `finalize_file_uploads` for terminal clients. No remote
argument selects a server filesystem path. All draft/review and permission rules
above apply to MCP and direct REST access.
Terminal uploads send user-selected bytes directly to existing Google Storage
resumable sessions, then finalize the exact batch through authenticated MCP.
Only `prepare_file_uploads` exposes validated storage write URLs, in an explicit
upload manifest. Explicit `get_file(include_original=true)` reads may expose
one validated signed storage read URL in `original_file.download_url` when
`delivery.kind` is `download`. All other result fields still reject private
transport capabilities. OAuth and
service identity tokens never enter upload instructions or storage requests.
Treat the manifest as a temporary credential: save it mode 600, do not include
it in answers or tracked captures, and remove it after transfer. Upload session
URLs remain usable until storage expiry even if the OAuth grant is revoked;
finalization still checks the live grant and Plan owner.

Terminal clients need only their normal local file access and an HTTP client
such as `curl`. They do not install a Lagniappe upload helper, local MCP
package, source checkout, or Python environment:

1. Inspect each user-selected regular file for its base filename, MIME type,
   and exact byte size; pass that metadata and the existing `plan_id` to
   `prepare_file_uploads`.
2. Send each original file directly to its returned `uploads[index].session_url`
   in a single HTTP `PUT`, with the declared content type and byte count. The
   `chunk_size` field is a hint for optional chunked transfers, not a limit on
   whole-file transfers.
3. Require HTTP 200 or 201 for every file, then call `finalize_file_uploads`
   with the unchanged `plan_id` and `upload_batch_id`. A timeout, failed request,
   or HTTP 308 is not confirmation of completion; leave the batch pending.

The main Lagniappe application creates the Storage session using its own identity. The returned
URL authorizes that upload without forwarding the client's OAuth token or
requiring a Google account on the terminal. Google documents the
[single-request upload protocol](https://docs.cloud.google.com/storage/docs/performing-resumable-uploads#upload_the_data).

For example, after writing one URL as `url = "SESSION_URL"` in an owner-only
curl config file, the terminal can transfer a selected file without placing
that URL in command arguments or output:

```bash
curl --disable --proto '=https' --silent --show-error --fail \
  --connect-timeout 10 --max-time 240 \
  --request PUT --upload-file /absolute/file.vcf \
  --header 'Content-Type: text/vcard' \
  --config /tmp/private-upload.curl \
  --output /dev/null --write-out '%{http_code}\n'
```

Create temporary files privately from the outset (mode 600), do not follow
redirects, and do not add authentication or cookies. For a regular file curl
supplies Content-Length; inspect the command exit status and HTTP status before
finalizing. Remove the temporary URL/config files after use. The terminal is
responsible for reading the same selected bytes it declared.
ChatGPT web/app attachment uploads use `upload_files`.

See [Authentication](AUTHENTICATION.md#remote-mcp) and
[Deployment](INFRA_DEPLOYMENT.md#remote-mcp-service) for the installer-managed service.

The remote service is the only supported MCP transport. The internal
`mcp/` package supplies shared schemas, API mappings, result
validation and file transfer code. It has no user CLI, stdio entry point,
credential profiles, public wheel distribution, or client installer.

OAuth grants belong to the consenting Lagniappe user and client, independently
of the browser session. Logging out or signing into a different browser account
does not switch the MCP identity. ChatGPT and Codex connections can coexist;
revoking or reconnecting one does not replace the other. Review links still
require the report creator's browser session. See
[Authentication](AUTHENTICATION.md#remote-mcp) for expiry, rotation and revocation.

`answer_question` returns lightweight answering guidance, date/timezone, and
personal Page context; it does not call a model, create a session, or save a
report. Read tools accept an optional `plan_id`: omit it for ordinary retrieval.
The client model answers first and offers to save afterward; `start_plan` is the
explicit-save path, not the read bootstrap. Normal request/security logging
still applies; this is not a promise that the external model retains nothing.

Starters bundle current workflow context. MCP clients can pass
`start_plan(actions=["create_task"])` to receive the selected permitted schemas
in the initial `context.contract`, together with the current version, permissions
and workflow guidance. Multiple action names are supported. Startup uses its
existing contract read, so no additional client schema fetch is needed. The
selection does not narrow future proposals or broaden permissions; submission
still checks the full current contract. Omitting `actions` preserves the summary
startup behavior. If the post-start schema read fails, keep the returned Plan
and follow `context.recovery`; its arguments retain the requested selection.
For rejected selections, read that Plan's summary to see current allowed actions
and correct the selection rather than creating another Plan.

Plan starts without selected actions and completed uploads use a compact
contract summary. It retains all allowed action names and permissions,
but `proposal_schema` is null and `schema_scope` is `summary`. Fetch
`get_plan_contract(actions=[...], view="schema")` for the selected schemas without
repeating that context, or `view=full`
without actions for all schemas. `submit_plan` privately checks the full current contract
before saving. Consume one complete result representation when the client
provides both text and structured content. Legacy protocol clients receive an
object wrapper for non-object results, with matching schemas and result paths.

The MCP adapter accepts a bounded JSON Schema subset. Remote schemas may use
`format: date` for calendar dates; other formats remain unsupported. Check new
contract keywords through the adapter's full submission path, including a
proposal that does not use the new action: an unsupported keyword in any allowed
action can block submission even when a selected-schema read succeeds.

For task discovery or duplicate-work checks on a known Page, use
`get_page_tasks(id=..., compact=true)`. It returns active `tasks` and
`completed_tasks` with names, hashes, canonical browser URLs, completion state,
view/edit permissions, visible project/model/form references, and descriptions
bounded to 500 characters. `description_truncated` marks shortened descriptions;
due/completion dates use the viewer's timezone. Compact projection does not call
the full task serializer or load form schemas/submissions just to discard them.
Use `get_entity` for a likely match when its full description or field values
affect the decision, and `get_schema` on a task/form reference for exact fields.

Compact task reads accept `limit` (default 25, maximum 100) and `cursor`.
`task_list` describes the returned scope, limit, total visible active/completed
counts, `returned_count`, `has_more`, and `next_cursor`. Tasks sort by completion
state, name and hash. Continue with the same page and compact mode until the
relevant scope is examined. Cursors are bound to the viewer, page, scope and
ordered task revision snapshot; a changed list returns a restart instruction.
`incomplete` and bounded `serialization_errors` disclose unreadable tasks even
when `has_more` is false. Those errors and truncated descriptions are separate
from pagination. Counts never include hidden tasks. The current Page relation
loader still loads the authorized task collection; pagination bounds projection
and response size, not database reads.

`get_page_details(compact_tasks=true)` uses the same compact projection for its
**active-task** list, retaining the existing page/category/file detail shape.
Use `task_limit` and `task_cursor` to continue that endpoint's list, and
`get_page_tasks` when completed tasks are relevant. `exclude_tasks=true` takes
precedence and omits both tasks and `task_list`. Full-detail defaults remain
unchanged on both tools; pagination arguments require their compact option.

For a new task, locate its destination if unknown, compare the compact task
list or sufficient existing search evidence, fetch only missing task/form
details and guidance, then start with the known action selection and submit.
Duplicate checking is an evidence comparison, not a requirement for both a
search and a list read. A partial list or ambiguous description calls for
continuation or focused details, not an assumption that no duplicate exists.

`get_schema(id=<Page or Task>, include_values=true)` returns the schema and
current AI-readable values keyed by exact field id. This avoids matching
human-readable labels (which can repeat) and loading unrelated entity details.
Tables return `{"rows": [{"<column id>": value}]}`, preserving row order, repeated
column labels, missing cells, numeric zero and boolean false. Todo lists return
`{"items": [{"text": "...", "checked": false}]}`; checkboxes return JSON booleans.
Clients must use these collection envelopes and IDs rather than the former
display array keyed by column titles. Other fields retain their existing
actor-aware AI projections, including reference handling; this is not a raw
storage export. Follow the field type's submission format when writing. Unset
fields are omitted; a Form itself has no submission and returns `values: null`.
The same collection and boolean projections apply to entity, task-list and
history reads. Their outer field keys remain human labels; use `get_schema` when
exact outer field IDs are needed.

`get_task_history(id=..., include_original=true)` adds `original_completion` for
the currently completed Task: `{generation, schema, schema_available, values}`.
Values use exact field IDs and the saved completion's schema, even after the
live Form migrates. This opt-in read requires edit access, matching the website;
ordinary history still requires view access. Open Tasks return `null`. If the
historical definition is unavailable, `schema_available` is false, `values` is
null, and an `error` explains the gap. Private raw keys are never substituted for
an unavailable projection. The existing `task` and `history` fields retain their
current-task and older-occurrence meanings.

For patches, `get_guidelines(task="form_autofill",
actions=["update_form_values"], field_types=[...])` omits the full Autofill
and file-discovery workflow. Reuse guidance already received when sufficient.

Execution receipts expose applied/skipped counts for submission and schema
updates without returning private recovery data. Counts describe action outcomes,
not a fresh field-value read; use `get_schema(..., include_values=true)` to inspect
the saved result. Batch patches accumulate on one working entity per durable key
and save the combined result. Undo restores the same batch in reverse row order.
The browser report labels successful patches as `Task Updated` or `Page Updated`
with a link to each distinct applied target. Skipped-only targets are not labeled
as updated; this display projection leaves the execution/undo ledger unchanged.

Proposal plan reads and submission receipts also expose `action_summary`:
`{total, by_type, maximum}`. The external maximum is 100. These count the saved
proposal's action rows, including skipped and review-only rows, without
predicting how many records or history occurrences execution will create.
The shared website review shows the total and counts by action type; native
reports omit the external action maximum. Answers omit this metadata.

After a proposal executes, read workspace state without `plan_id`;
use `get_plan` for execution outcomes. A plan-scoped read rejected at this stage
includes that recovery instruction. MCP schema validation errors include the
applicable public numeric bound (for example `details.maximum: 50`), alongside
the existing path and validator, without echoing submitted values or schemas.

For clients that prefer direct HTTP, the API-key workflow and downloadable
[client skill](#minimal-client-skill) remain independent of OAuth and MCP.

## Workflow

All working endpoints are under `/api/v1` and require authentication, including
the API index and OpenAPI document. Direct REST clients send the bearer API key;
the MCP service uses the separate workload-identity/user-token envelope described
above. `GET /api` identifies the current version;
`GET /api/v1` returns direct links to the OpenAPI document, actor, tool catalog,
and plan collection. These small discovery responses do not duplicate the
contract. The OpenAPI `info.description` and operation descriptions carry the
tool-selection rules, lifecycle, and browser-approval boundary. Every plan
response returns its opaque identifier as the top-level
`id`. A plan's tool is immutable for auditability, but a conversational client
may create another plan with a different tool whenever the user's intent
changes. Fetch discovery, OpenAPI, and the tool catalog once per client run and
reuse the parsed values in memory. This is run-local reuse, not persistent HTTP
caching: API responses remain `no-store`, and the current plan contract must
still be fetched after uploads and immediately before submission.

1. `GET /` points a client given only the versioned base URL to the authoritative
   discovery resources.
2. `GET /client-skill.md` returns the optional canonical minimal `SKILL.md` for
   clients that support local skills. It points back to live discovery and does
   not duplicate schemas or permissions.
3. `GET /me` verifies the actor, reports the actor's persisted timezone and
   personal Page reference, and reports the provider-free external-plan
   capabilities. It intentionally does not expose or consult the unrelated
   site-funded model-provider entitlement.
4. `GET /tools` returns permission-bounded read tools as plain JSON Schema.
   Each full definition contains `input_schema`, `output_schema`, and
   `result_paths`. The output schema describes a successful direct shared-handler
   result; REST places it beneath the success response's `result` field. Inspect these
   contracts rather than guessing field names or whether a result is a list or
   object. A read tool with one required subject entity always names that argument
   `id`; its value is the returned `hash:<12-character-hash>` token. Names such as
   `form_id`, `parent_id`, and `source_id` are reserved for secondary filters or
   scopes when a request has another subject. Use repeated/comma-separated `names`
   to retrieve selected definitions, or `view=names` for only exact registered names.
   `list_workspace_resources` includes the personal Page alongside the
   permission-filtered workspace inventory.
5. For ordinary questions, get `/answer-context` and run permitted reads with
   `POST /tools/{tool_name}` using the same `{"arguments": {...}}` envelope.
   No Plan or answer is saved, and the general request rate limit still applies.
   Answer in the conversation and offer to save afterward.
6. Only for an explicitly requested saved answer or proposed change,
   `POST /plans` creates a provider-free draft with optional instructions/name. The returned Plan includes canonical `contract_url`,
   `submit_url`, and `status_url` links so callers do not construct paths.
   For report-scoped work, use `POST /plans/{id}/tools/{tool_name}` while the plan
   is a draft. Reads remain available after a saved answer and while a
   proposal remains ready for browser review.
7. `GET /plans/{id}/contract` returns the authoritative output
   schema, submission wrapper, machine-readable guidance requirements, workflow
   and reference rules, permissions, payload sizes, limits, actor timezone,
   personal Page reference, timezone-aware `current_date`, and top-level
   `contract_version`. Optional `view=summary` omits the schema; optional
   comma-separated `actions` selects exact action schemas without changing
   permissions. Default `view=summary` omits action schemas. Request `view=full` for the complete contract. `view=schema` is a follow-up projection containing only version,
   exact selected schemas, schema metadata and the submission wrapper;
   reuse previously obtained context or fetch full context if it is missing or
   state changed. All selections are checked against current permissions.
   All three views work through both terminal and hosted MCP; the hosted URL
   guard permits these queries only on the plan-contract GET route.
   Its `submission_format` gives the exact `POST` method,
   URL, and wrapper body shape. The contract also returns the authoritative
   finalized-upload inventory and per-file checklist.
8. `POST /plans/{id}/submit` validates and publishes the final result. It returns
   a compact receipt containing status, review URLs, and the normalized proposal
   fingerprint rather than echoing the proposal. It never calls a provider or
   applies workspace actions. Repeating this call with a valid complete result
   replaces the prior result while the report remains reusable; `status_url`
   retrieves the detailed Plan resource.

Contract version 9 is an intentional breaking cutover: the contract uses only
top-level `contract_version`, and primary read-tool subjects use only `id`.
There are no legacy aliases. Clients must refresh discovery, OpenAPI, the tool
catalog, and the current Plan contract rather than replaying an older shape or
retired action name.
Absolute API and review links use the installation's validated configured
origin; an incoming HTTP `Host` header never selects their destination.

### Minimal client skill

The authenticated discovery response includes `client_skill_url`. Its Markdown
response is the canonical short bootstrap for clients that support local
skills, served at `https://YOUR-LAGNIAPPE-SITE/api/v1/client-skill.md`. Generate
the key in your own My Page → Settings → External agent API panel, then make it
available as `LAGNIAPPE_API_KEY` without putting the secret in a prompt or skill
file. Use the intended site's origin for `LAGNIAPPE_URL`. For Pi, install or
refresh the Markdown with:

```bash
mkdir -p ~/.pi/agent/skills/lagniappe
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  "$LAGNIAPPE_URL/api/v1/client-skill.md" \
  -o ~/.pi/agent/skills/lagniappe/SKILL.md
```

The downloaded skill does not install an executable or upload helper. A client's
existing HTTP script may remain useful, but must follow live contracts; it is
not a dependency of the remote MCP service.

The skill deliberately contains no action schemas, permission lists, or
use-case-specific proposal instructions. It defines the answer/proposal
boundary, early uploaded-file safety, and run-local discovery reuse;
the live OpenAPI and each plan contract remain authoritative as the API evolves.
It also defines evidence provenance, long-file completion, review-state wording,
and compact-receipt behavior that should not be rediscovered per client.

Within proposals, a `data.submission` object contains the
Form values to create with that new Page or Task, keyed by exact Form schema
IDs; it is not an existing submission reference. Fields ending in `*_action`
contain the exact ID of an earlier proposal action that creates the referenced
entity. Existing workspace entities instead use their documented
`hash:<12-character-hash>` references.

### Context size and conversational revisions

Compact contracts reduce model-visible schema bytes, not authorization checks.
All allowed action names remain visible so the client can discover capabilities;
selection never silently infers a restricted action set from the user's prompt.
A client pays an extra read when it needs a new action schema, but can reuse
complete selected schemas within the same unchanged context. Complex planning
can request the full contract once. Submission always validates against fresh
full permissions, independently of which subset the client previously read.
Summary and selected/full responses advertise their scope explicitly; a summary
is not a permissive schema that can be submitted against.

`list_workspace_resources` accepts known `category_id` and/or `project_id`
references to omit unrelated collections; unscoped calls retain the broad
inventory. `get_category_pages(names_only=true)` returns just name, hash, kind,
and URL, with a default/maximum of 100 per page and the existing permission and
cursor semantics. Full/compact detail calls remain bounded to 10. Prefer ranked
keyword discovery and compare candidate context; an abbreviation such as MCP
need not equal a Page's full name. Name-only browsing is an optional way to
recognize a subject, not a required exact-name search or exhaustive scan.

Submission may include optional `name` and `instructions` alongside
`contract_version`, `file_usage`, and the complete `proposal`. These update the current report
brief atomically under the existing submission fence; `original_brief` retains
the initial title/instructions. Omitted fields are preserved. Executing reports
cannot be revised. A Plan GET includes the round-trippable proposal and, for
proposals, a bounded `execution` receipt with action IDs/types/statuses and
currently viewable resulting entity names, hash references, and URLs. Missing or
no-longer-viewable entities are null; stored ledger names, recovery snapshots,
private diagnostics and standalone internal entity keys are not exposed. An
unavailable entity does not mean its action never ran. An answer has no execution
receipt.

### Answers and proposals

A single Plan supports answers, new content, updates, and file organization.
The response has summary, optional answer_markdown, confidence, issues, and
actions. Empty actions publish an answer; nonempty actions publish a proposal
requiring browser review. Raw answer_html is rejected. Use human link labels
and canonical tool-returned browser URLs. Revisions can turn an answer into a
proposal or vice versa until execution begins.

Instructions and files are individually optional, with at least one needed
before publication. Classify every upload in file_usage as evidence or organize.
Evidence-only uploads do not require attachment or summary actions. Files with
no instructions must be organized. Each organize file requires an executable
attachment and one summarize_file action with two retrieval terms.

The planner chooses among the same permission-allowed actions whether files
are present or absent. Resolve exact editable targets and include complete
final form values. Load selected action schemas and relevant guidance as
needed; no separate intent classification request or form-completion generation
is used. The API deterministically validates the complete submitted candidate.

### Publication and browser approval

All intake paths expose the same permission-filtered actions, with or without
uploads. To move an existing file to a new Task, place `create_task` first and
reference its action id in `move_file.data.to_task_action` and `depends_on`.
Task Form submissions must contain final values.

Call `start_plan(actions=["update_form_values", "complete_task"])` when the
needed actions are known to include selected schemas in the first response.
Otherwise use the compact action list, then request
`get_plan_contract(actions=["update_form_values", "complete_task"])`
for exact shapes. Use read tools to identify the intended record and inspect its
current schema. Put final field patches before `complete_task`, with the patch's
id in completion's `depends_on`. Failed/skipped required updates prevent completion.
The completion action uses only `data.task` and optional `task_name`; it never
uses name-based matching or historical replacement semantics. Normal required
fields, recurrence, permissions, retry and undo still apply.

For `update_form_values`, the external action's `data` contains only `updates`.
Every row supplies `schema_id` (the exact Form field id), `new_value`, and exactly
one target: `page` or `task` for an existing entity, or `page_action` or
`task_action` for an earlier creation action. Repeat the target for each field,
including multiple fields on the same entity. Omitted fields retain their values.

```json
{
  "type": "update_form_values",
  "data": {
    "updates": [
      {"task": "hash:012345abcdef", "schema_id": "textarea-notes", "new_value": "Updated notes"}
    ]
  }
}
```

The external schema rejects top-level targets, missing row targets, and multiple
targets in one row before semantic validation.

`set_task_due_date` edits an existing incomplete Task using `data.task` and a
required `data.due_date`: a valid `YYYY-MM-DD` calendar date, or JSON `null` to
clear it. This is a task scheduling action, separate from Form-value patches. Resolve relative wording using the plan's current date and timezone.
Execution uses the acting user's timezone and the Task editor's calendar-date
behavior; it preserves recurrence rules, postponement metadata, assignment, and
submission values. A date already matching the requested local day is a no-op.
Completed Tasks must be reopened separately before changing their due dates.
The browser preview distinguishes setting a date from clearing it. Retry checks
the recorded scheduling state; undo restores the prior timestamp and refuses to
overwrite later due-date, recurrence, or completion changes.

For imported completed occurrences, a date-only `completed_on` represents
midnight in the acting user's timezone and is stored in UTC. Background report
execution passes that actor explicitly when preparing the checkpoint and when
recording either a live completion or older history. Calendar dates therefore
survive local readback across daylight-saving transitions. This does not rewrite
timestamps from earlier imports.

The current action vocabulary is deliberately not backward-compatible. Contract
version 9 uses `update_form_values`, `update_form_schema`, `add_page_category`,
`suggest_page_deletion`, and one `attach_file` action. Clients must refresh the
contract; new proposals cannot use `extend_form_schema`. Previously stored
additive schema actions retain their execution/recovery behavior.

`update_form_schema` accepts `add_field`, `add_select_option`, `update_field`
(`schema_id`, partial `patch`), `remove_field`, and `reorder_fields` (`ids`). IDs
remain stable. Read `schema_evolution` and call `preview_form_schema_update` with
`id`, `operations`, optional `include_values`, `limit` (1–50), and `cursor`.
The preview validates the whole target schema, classifies deterministic/AI
conversions, and checks every attached live Page/Task, including completed Tasks.
Restricted members block the entire migration with a generic admin-required
message. It returns `baseline`, `scope_fingerprint`, and cursor-paginated
`instances` with entity references, links, affected field IDs and source hashes.
Task instances also include a boolean `completed`; Page instances omit it.
Follow every cursor with unchanged operations; concurrent changes invalidate it.

Use `include_values=true` for conversion evidence. AI fields include their source
`value`, preserving exact rows and types. Affected deterministic scalar fields
include `before` and `clears`, plus `after` when the value survives. `clears: true`
explicitly means removal and omits `after`. Unaffected fields are not returned;
pagination and the existing response size guard still apply. Supply every populated AI
field in `data.conversions` as `{entity, schema_id, source_fingerprint, value}` or
`{entity, schema_id, source_fingerprint, unresolved_reason}`. Tables use
`{rows: [{column_id: value}]}` and todos `{items: [{text, checked}]}`; only exact
destination IDs and types are accepted. Copy `baseline` and `scope_fingerprint`
into the action. Missing, duplicate, unexpected or stale candidates fail before
publication. Empty collections cannot clear populated sources implicitly.

Supported AI pairs are textarea→table/todo, table→todo, and todo→table; todo is
Task-only. Table/todo→textarea remains deterministic. Internal links, assets,
identity inference and nested AI cell conversions are excluded. External
execution never calls a site model and does not require site AI entitlement.
Candidate values are reviewed in the browser alongside affected links and
explicit destructive-change warnings; viewing candidates rechecks permissions.
The parent report waits for Form publication before dependent actions continue.
Once a migration starts, report Undo is unavailable; partial failures use Retry.

The API envelope remains capped at 1 MiB. The prepared schema proposal, including
server-owned review metadata, has a 750 KiB guard to reserve Datastore space for
execution. Oversized complete values must not be truncated; use a smaller change
or the on-site builder. There is no external candidate-upload endpoint.

`attach_file` takes `file` (the exact report upload reference) and either `entity`
(an existing Page, Task, or TaskHistory) or `entity_action` (an earlier Page/Task
creation action). `entity_name` is display context only. This creates a file
link, not document text. Completed-occurrence evidence stays on that occurrence.

`append_page_document` takes `page` or `page_action` and `document_markdown`.
Supply only the requested addition; it starts a missing document but never
replaces existing text. New AI-created Page documents and each addition begin
with a server-generated UTC timestamp/source quote. Sources distinguish
Application, Email, Remote MCP, and External API / skill using trusted intake,
not proposal fields. Manual editor typing receives no header.

Document append execution requires a checkpointed collaborative baseline. Unsaved
edits stop execution for a retry; HTML-only older documents must be opened and
saved once first. Retry receipts prevent duplicate additions. Undo removes only
the unchanged addition and stops if subsequent document changes would be lost.
See [document sync](SYNC_DOCUMENTS.md#reviewed-document-appends) for persistence.

Pending uploads always block submission. Finalized files classified as
`organize` require summaries and placements; `evidence` files do not. Uploads
do not change which creation or update actions are available.

Submitting actions saves a `ready` report and returns a compact
receipt with the full `review_url`, shorter creator-session `preview_url`,
`status_url`, and `proposal_fingerprint`. Present the preview and direct the
user to review and approve it on the authenticated website. The
external API deliberately has no `/execute` operation. The existing browser
Execute control starts the normal deterministic runner and applies the exact
validated proposal without a model call.

The compact receipt is a response-shape change for clients that previously read
`proposal` directly from the submit response. Treat a successful receipt as
authoritative and fetch `status_url` only for later polling or an ambiguous
outcome. A Plan GET projects saved execution state back into the public
submission shape: existing references use `hash:` tokens and generated rich text
uses Markdown, while internal keys and executable HTML remain server-side. A
ready proposal, or saved answer, can therefore be
edited and resubmitted directly while the plan remains reusable.

First publication also creates one ordinary notification for the authenticated
creator, linking to the report. Drafts remain silent. The notification and unread
count commit atomically with the published Plan; retries and revisions do not
create additional alerts or restore dismissed ones. Optional notification email
follows the user's existing preferences. Existing published Plans are not bulk
backfilled; a later changed submission can create their first notification.

Opening, changing, executing, retrying, undoing, or deleting a saved report is
provider-free and therefore does not require site AI access. Those browser
operations still require the report owner's authenticated session, CSRF where
applicable, a valid report state, and current permission for every affected
resource. Internal report revision is different: it calls Lagniappe's configured
provider and still requires the corresponding site AI-access level. External
reports cannot invoke that provider-backed revision route.

For an API-origin report, browser skip, execution start, every undo checkpoint,
execution-failure persistence, terminal execution cleanup, and deletion use the
shared claim key as a one-shot transactional fence rather than taking a
long-lived API lease. Each transaction compares the exact Report revision,
reads the shared operation-claim key, and deletes an absent or expired claim as
part of the guarded mutation. An active API claim or a changed Report produces
a conflict with no mutation; mutating the claim key also forces a simultaneous
API claimant to retry and observe the browser or execution worker's winner.

Delete rejects an API-origin report that still has a deferred execution or is
in `undoing` status, so deletion is not an active-job cancellation mechanism.
Once deletion is eligible, its guarded transaction commits the Report and
report-only File entity deletions first. Temporary-upload cleanup and other blob
or cache effects happen only after that durable delete succeeds.

Submitting the same normalized result and file usage again is idempotent.
Until execution begins, replace the complete proposal for a follow-up, including
changing an answer into a mutation proposal or a proposal into an answer.
Browser execution locks further API revision.
Pending uploads, unknown or inaccessible references, disallowed actions,
malformed final submissions, and missing placements for organize files fail without
model repair. Exact form fields remain authoritative at the normal
`SubmitterMixin` execution boundary. A completed-task date later than the
submitting user's current date is rejected; future work remains open.

Before semantic validation, the external submit boundary validates the wrapper
and current permission-scoped proposal schema. Independent safe failures are
returned together under `error.details.errors`, bounded to twenty entries. When
needed, the final entry is a truncation marker. Each entry has a stable `code`,
JSON `path`, concise message,
and an `expected` value when useful. The top-level `validation_failed` message
and request ID remain concise; private target Form metadata and raw exceptions
are never added.

The browser review projects proposed submission values beneath each action,
using the referenced form's human field, option, and table-column labels when
available. Submission previews start on their own line. This projection makes
the stored proposal reviewable but does not normalize or change it; the
deterministic execution path remains authoritative.

Failures under `/api/v1`, including routing-level `404` and `405` responses,
use the same JSON error envelope and request ID. A `405` preserves the HTTP
`Allow` header. Read-tool handler failures use HTTP `422` with
`error.code: "tool_error"`; any corrective fields supplied by the shared
handler are preserved under `error.details` with the selected tool name.
When diagnosing a cURL failure, use `--fail-with-body` so the JSON envelope is
not discarded by cURL's nonzero exit behavior.

## File organization cURL example

For an interactive Bash session, read the key without echoing it or entering the
secret in shell history. Keep shell tracing off and exclude credentials and
upload responses from shared captures:

```bash
read -r -s -p 'Lagniappe API key: ' LAGNIAPPE_API_KEY
printf '\n'
export LAGNIAPPE_API_KEY
export LAGNIAPPE_URL='https://your-app.example'

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  "$LAGNIAPPE_URL/api/v1/me"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"instructions":"Organize the uploaded records into pages."}' \
  "$LAGNIAPPE_URL/api/v1/plans"
```

Copy the returned Plan fields into `PLAN_ID`, `CONTRACT_URL`, `SUBMIT_URL`, and
`STATUS_URL`. Use the ID for the Plan-scoped upload and read-tool templates from
OpenAPI, but follow the returned canonical URLs for contract, submission, and
status instead of reconstructing those three paths. Copy the upload-session
response's top-level identity into `UPLOAD_BATCH_ID`; do not derive it from the
session URL or file declaration:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"files":[{"filename":"records.pdf","content_type":"application/pdf","size":12345}]}' \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/uploads"
```

Store the returned session URL in a mode-600 curl config as described in
[Remote MCP adapter](#remote-mcp-adapter); the same Storage transfer protocol
applies to REST. Do not attach the API session's Authorization header to it:

```bash
curl --disable --proto '=https' --silent --show-error --fail \
  --connect-timeout 10 --max-time 240 \
  --request PUT --header 'Content-Type: application/pdf' \
  --upload-file records.pdf --config /tmp/private-upload.curl \
  --output /dev/null --write-out '%{http_code}\n'
```

Continue only after a successful transfer returning HTTP 200 or 201. An error,
timeout or HTTP 308 leaves the batch pending. Remove the temporary curl config,
then finalize the confirmed batch:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"upload_batch_id\":\"$UPLOAD_BATCH_ID\"}" \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/uploads/finalize"
```

Fetch the shared filing guidance after finalization, use the required read
tools and specialized bundles, then fetch the contract and submit the external
model's final JSON proposal:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"task":"filing"}}' \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/tools/get_guidelines"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  "$CONTRACT_URL"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @submission.json \
  "$SUBMIT_URL"
```

Present the returned `preview_url` and direct the user to the authenticated
website to review and approve the proposal there. The API performs no further
write step. A client may fetch the plan later to observe its top-level state:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  "$STATUS_URL"
```

The short `preview_url` lives with the other user-facing AI report routes at
`/tools/api-plan/<12-character-report-hash>`. It is deliberately a normal
browser-session route rather than a bearer endpoint or public capability. A
logged-in plan creator can open it, and the server resolves the hash beneath
that creator before redirecting to the full report URL. The URL alone grants no
access.

`submission.json` contains `contract_version`, `file_usage`, and `proposal`.
For example, after reading the source and checking the destination:

```json
{
  "contract_version": 9,
  "file_usage": [{"file": "hash:012345abcdef", "usage": "organize"}],
  "proposal": {
    "summary": "File the annual inspection record on a new page.",
    "confidence": 0.94,
    "issues": [],
    "actions": [
      {"id": "page", "type": "create_page", "data": {"name": "Annual Inspection"}},
      {"id": "summary", "type": "summarize_file", "data": {
        "file": "hash:012345abcdef", "summary": "Record of the annual inspection.",
        "retrieval_terms": ["annual", "inspection"], "search": true
      }},
      {"type": "attach_file", "depends_on": ["page"], "data": {
        "file": "hash:012345abcdef", "entity_action": "page"
      }}
    ]
  }
}
```

Replace the reference, destination, and summary with the actual inspected
content. Every `required_file_refs` entry must have exactly one `file_usage`
entry. An organization request needs an attachment and exactly one
`summarize_file` action per organize file. The summary action requires two
distinct retrieval terms; case-only duplicates are rejected. For a question
using uploads only as evidence, classify them `evidence` and return empty actions.

When `get_file` is called with `include_original: true`, the REST adapter
returns a five-minute `original_file.download_url` when the source is
available. Other transports may provide direct media instead. Extracted text
remains the default so clients do not fetch original bytes unnecessarily. A
metadata-only call reports when the REST download fallback is available but
does not create a signed URL. This remains true when the configured internal
model cannot directly attach that file's MIME type.

MCP preserves inline image/audio delivery up to 4 MiB. PDFs, other formats,
and larger media use the same REST signed-original URL, without buffering
download-only files in the MCP service. A download result includes
`delivery: {"kind": "download", "mime_type": "application/pdf"}` (with the
file's MIME type), `original_file.download_url`, `original_file.expires_in`,
and the existing `filename` and `mimetype`. `original_file.supported` describes
original availability through this transport; `attached` is true only when an
inline content block is present. Summaries and optional extracted `content`
remain distinct from original delivery. A missing original returns
`original_unavailable`; inline size limits select download delivery, while
unsafe URLs, MIME contradictions, and failed transfers remain errors.

Clients use their own HTTP/file or browsing tools to retrieve and inspect the
original. Use HTTPS GET without additional Authorization, cookies, or redirects.
The URL is a temporary credential: keep it out of answers, saved reports, logs,
and test captures; use the normal file page URL for citations. After expiry,
repeat `get_file` with the same file id and `include_original=true`. Downloads
do not require a Plan or browser session, and do not trigger OCR or a model.
File permissions are checked at issuance. Revocation prevents issuing new URLs;
an already issued URL can remain usable until its five-minute expiry.

Client acceptance requires actually reading source content, including a PDF
without extracted text. A successful tool response or a displayed download
link alone does not establish that a particular client can inspect the file.

Upload MIME types are normalized to their lowercase base media type, without
parameters such as `charset`. Recognized text formats, including `.vcf`
vCards, are decoded for inline `get_file` content; other stored formats remain
available through the signed-original fallback.

## Python skeleton

```python
from pathlib import Path
import os
import requests

base = os.environ["LAGNIAPPE_URL"].rstrip("/") + "/api/v1"
session = requests.Session()
session.headers["Authorization"] = f"Bearer {os.environ['LAGNIAPPE_API_KEY']}"


def api_json(method, url, **kwargs):
    response = session.request(
        method, url, timeout=(10, 240), allow_redirects=False, **kwargs
    )
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise RuntimeError("Unexpected API response; inspect before continuing.")
    return response.json()


plan = api_json(
    "POST",
    f"{base}/plans",
    json={"instructions": "Organize these files."},
)

path = Path("records.pdf")
upload_batch = api_json(
    "POST",
    f"{base}/plans/{plan['id']}/uploads",
    json={"files": [{
        "filename": path.name,
        "content_type": "application/pdf",
        "size": path.stat().st_size,
    }]},
)
upload = upload_batch["uploads"][0]

with path.open("rb") as source:
    transfer = requests.put(
        upload["session_url"],
        data=source,
        headers={"Content-Type": "application/pdf"},
        timeout=(10, 240),
        allow_redirects=False,
    )
if transfer.status_code not in (200, 201):
    raise RuntimeError("Upload incomplete; do not finalize this batch.")

api_json(
    "POST",
    f"{base}/plans/{plan['id']}/uploads/finalize",
    json={"upload_batch_id": upload_batch["upload_batch_id"]},
)
# Reuse this catalog for the rest of the run. Do not persist it as an HTTP cache.
tools = api_json("GET", f"{base}/tools")
filing_guidelines = api_json(
    "POST",
    f"{base}/plans/{plan['id']}/tools/get_guidelines",
    json={"arguments": {"task": "filing"}},
)["result"]
contract = api_json("GET", plan["contract_url"])
# Give the model the plan, tools, shared filing guidance, and
# contract. Run requested reads; settle structure first; then apply form_autofill
# and exact schemas to add final values before POSTing to plan["submit_url"].
```

## Unified contract version 9

Create drafts with `{instructions?, name?}`; `tool` is rejected. Drafts may start
empty for uploads, but publishing requires instructions or finalized files.
Submit `{contract_version: 9, proposal, file_usage, name?, instructions?}`.
Every finalized upload appears exactly once in file_usage with its file ref and
usage `evidence` or `organize`. Only organize files require attachment and summary
actions. With no instructions, all uploads must be organize.

The default contract is compact; request selected action schemas using actions
or `get_guidelines(task="report_actions", actions=[...])`. Full contracts remain
available for validation. MCP exposes only start_plan and retains answer_question
and plan-free reads. Answers are saved only on request; changes require a plan.
There are no aliases for previous starters or workflow-specific contracts.
Old reports are unavailable and deletable, not migrated. See the upgrade boundary
in [AI_WORKFLOWS.md](AI_WORKFLOWS.md#upgrade-boundary).
