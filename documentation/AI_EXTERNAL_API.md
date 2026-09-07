# External Agent API

Lagniappe exposes a versioned, REST-first API that lets a user run the same
permission-bounded read tools as the built-in AI workflows. Ordinary questions
and task lookups use plan-free reads and are answered in the conversation. Only
when the user requests saving an answer does the client create an `ask` Plan.
For requested changes it chooses `create` or `organize`. Ask publishes a
read-only answer; Create and Organize publish proposals for browser review and
leave approval and application to the existing authenticated website controls.
External plans never call Lagniappe's configured model, and the external API
has no operation that applies a proposal to the workspace.

The API is part of the application and is gated by the installation's AI and
external-AI policy. When enabled, authenticated non-public users may manage a
key and use Ask, Create, and Organize within their workspace permissions,
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
enabled `REMOTE_MCP` configuration. An existing explicit OAuth `actors` list
remains restrictive; without a list, eligible non-public users may connect.

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
  revise reports. It cannot apply Create or Organize proposals. The agent must
  present `preview_url` and direct the user to the authenticated browser report,
  where the existing Execute control is the only approval and application path.
- Ask submission only validates and saves a read-only answer. It has no
  execution lifecycle or execution-shaped response fields.
- Ready Create and Organize reports remain open to read tools and repeated
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
  Plan-start allowance is shared across Ask, Create, and Organize; starting a
  report does not invoke a model or execute workspace changes. Organize
  additionally allows 20 files per plan, 30 MiB per file, and 50 MiB total.

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
upload manifest. This is the sole upload-capability exception;
all ordinary results still reject private transport capabilities. OAuth and
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
The client model answers first and offers to save afterward; `start_ask` is the
explicit-save path, not the read bootstrap. Normal request/security logging
still applies; this is not a promise that the external model retains nothing.

Starters bundle current workflow context; Create, Organize and completed uploads use a
compact contract summary. It retains all allowed action names and permissions,
but `proposal_schema` is null and `schema_scope` is `summary`. Fetch
`get_plan_contract(actions=[...], view="schema")` for the selected schemas without
repeating that context, or `view=full`
without actions for all schemas. `submit_plan` privately checks the full current contract
before saving. Consume one complete result representation when the client
provides both text and structured content. Legacy protocol clients receive an
object wrapper for non-object results, with matching schemas and result paths.

`get_schema(id=<Page or Task>, include_values=true)` returns the schema and
current AI-readable values keyed by exact field id. This avoids matching
human-readable labels (which can repeat) and loading unrelated entity details.
Values use the existing AI field representations, not a raw storage export;
follow the field type's submission format when writing. Unset fields are omitted;
a Form itself has no submission and returns `values: null`.
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
   `POST /plans` creates a provider-free draft with `tool` set to `ask`,
   `create`, or `organize`. The returned Plan includes canonical `contract_url`,
   `submit_url`, and `status_url` links so callers do not construct paths.
   For report-scoped work, use `POST /plans/{id}/tools/{tool_name}` while the plan
   is a draft. Reads remain available after a saved Ask answer and while a
   Create or Organize proposal remains ready for browser review.
7. `GET /plans/{id}/contract` returns the selected tool's authoritative output
   schema, submission wrapper, machine-readable guidance requirements, workflow
   and reference rules, permissions, payload sizes, limits, actor timezone,
   personal Page reference, timezone-aware `current_date`, and top-level
   `contract_version`. Optional `view=summary` omits the schema; optional
   comma-separated `actions` selects exact action schemas without changing
   permissions. Default `view=full` without `actions` preserves the complete
   contract. `view=schema` is a follow-up projection containing only version,
   tool, exact selected schemas, schema metadata and the submission wrapper;
   reuse previously obtained context or fetch full context if it is missing or
   state changed. All selections are checked against current permissions.
   All three views work through both terminal and hosted MCP; the hosted URL
   guard permits these queries only on the plan-contract GET route.
   Its `submission_format` gives the exact `POST` method,
   URL, and wrapper body shape. Organize also returns the authoritative
   finalized-upload inventory and per-file checklist.
8. `POST /plans/{id}/submit` validates and publishes the final result. It returns
   a compact receipt containing status, review URLs, and the normalized proposal
   fingerprint rather than echoing the proposal. It never calls a provider or
   applies workspace actions. Repeating this call with a valid complete result
   replaces the prior result while the report remains reusable; `status_url`
   retrieves the detailed Plan resource.

Contract version 7 is an intentional breaking cutover: the contract uses only
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
use-case-specific proposal instructions. It defines the general Ask/Create/
Organize boundary, early uploaded-file safety, and run-local discovery reuse;
the live OpenAPI and each plan contract remain authoritative as the API evolves.
It also defines evidence provenance, long-file completion, review-state wording,
and compact-receipt behavior that should not be rediscovered per client.

Within Create and Organize proposals, a `data.submission` object contains the
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
`contract_version` and the complete `proposal`. These update the current report
brief atomically under the existing submission fence; `original_brief` retains
the initial title/instructions. Omitted fields are preserved. Executing reports
cannot be revised. A Plan GET includes the round-trippable proposal and, for
Create/Organize, a bounded `execution` receipt with action IDs/types/statuses and
currently viewable resulting entity names, hash references, and URLs. Missing or
no-longer-viewable entities are null; stored ledger names, recovery snapshots,
private diagnostics and internal entity keys are not exposed. An unavailable
entity does not mean its action never ran. Ask has no execution receipt.

### Ask

Ask is read-only. The client answers the specific
question from permitted workspace tools and outside research when useful. Its
final object contains a direct plain-text `summary`, optional
`answer_markdown`, a confidence value, and an empty `actions` array. Trusted
application code renders `answer_markdown` through the shared sanitized,
editor-compatible Markdown pipeline and stores the resulting `answer_html` for
the report view. Submission moves the report directly to `complete`; it returns
preview and review URLs. Ask rejects uploads and has no execution lifecycle.
Internal hash tokens remain tool-call references and may not appear as visible
answer text. When a read tool returns a URL containing such a token, clients may
use that exact URL as a Markdown link destination with the entity's human name
as its link label. The shared AI Markdown conversion resolves known hash
destinations to canonical browser URLs after validation, so tool-only notation
is not stored in the human-facing link. The external submission accepts the
advertised Ask fields only; clients cannot submit pre-rendered `answer_html` or
bypass the shared Markdown sanitizer.

Answer directly using plan-free reads, then offer to save the answer. Do not
start a Plan merely to retrieve a task or answer a question. If the user requests
saving (either initially or after the answer), create an Ask Plan and submit the
agreed answer, without an unnecessary second generation. Return `preview_url`
as the saved report link. Saving this report does not modify workspace records.
The same completed Ask plan remains available for permission-bounded reads, and
a later valid submission replaces its saved answer so conversational
clarifications can refine the report. A ready Create proposal is also revisable
for conversational follow-ups, as is a ready Organize proposal.

If the conversation changes from investigation to requested work, the client
creates a separate Create or Organize plan rather than placing mutations in an
Ask response.

### Create

Create is available to every eligible external-agent user. The client inspects existing workspace
structure before proposing new forms, categories, projects, model tasks, pages,
or tasks. It shares action semantics and permissions with internal Create,
while external schema/guidance composition describes client-owned completion.
Reuse sufficient supplied workspace context and schemas; broader inventory or
specialist guidance is needed only for information or rules still missing.
The proposal must contain at least one allowed
action or `needs_review`. Create does not accept plan uploads.

Task-form authoring rules are shared with on-site/email Gemini: a required
checkbox is an affirmative acknowledgement and must be checked for completion.
When No is a valid answer to a required question, use radio or single-select
Yes/No options with distinct non-empty string values; an optional checkbox may
remain unchecked. This is guidance for choosing fields, not a change to existing
form schemas or task-completion validation.

`create_task` is always part of Create and file-backed Organize contracts because
every user has an editable personal Page. The coarse capability projection does
not expose a redundant `can_create_tasks` flag. A Task proposal must still name
an editable target in `data.page`, or use `data.page_action` when an earlier
proposal action creates the target Page. `page_name` is display context only and
does not satisfy this requirement. Use `personal_page.hash` for a request
concerning the authenticated user's own Page. Proposal submission rejects a
Task without an executable Page reference, and the deterministic runner does not
gain permission to write to any other Page.

External `search_entities` uses ranked keyword candidates, with bounded OR fill
when a multiword query has too few strict matches. Exact names and stronger name
matches rank ahead of weak matches. Caller permissions and requested kind/parent
scope apply to both queries. Cached parent, snippet and Task completion context
helps target selection without loading every entity for extra permission flags.
When `kinds` is exactly `["page"]`, `parent_id` may constrain keyword candidates
or explicit exact lookup to one viewable Category. `match_mode: "exact_name"`
retains its case-insensitive full-name equality and permission metadata. Built-in
Gemini, automatic Organize retrieval and website search retain their existing
full-text behavior; trusted API dispatch selects the candidate path.

One-time Task reminders use `due_date` without `schedule`. Repeating schedules
declare their interval/unit or calendar mode and its dependent fields. The
external schema and field-addressed validation expose these requirements while
Gemini retains its provider-compatible schema. For `create_task`, `model` or
`model_action` selects a reusable work type; `task` or `task_action` overrides
an exact completed occurrence and does not represent an open-task dependency.

Optional page rich text is model-facing `document_markdown`. Proposal
validation renders it through the same sanitized Markdown pipeline used by the
frontend document editor and stores legacy executable `document` HTML. This
keeps new internal and external model contracts aligned while preserving the
HTML input expected by the existing browser-approved deterministic runner.

### Organize

Organize is available to every eligible external-agent user and requires at
least one finalized upload. Use
`POST /plans/{id}/uploads` to create resumable Cloud Storage sessions, upload
the declared bytes to each returned `session_url`, and call
`POST /plans/{id}/uploads/finalize` with the exact opaque `upload_batch_id`
returned alongside those sessions. The server binds that identity to every
staged record and rejects a stale identity if another caller replaced the
batch, even when both declarations have identical filenames, MIME types, and
sizes. Plan responses retain the current or most recently finalized identity
so a client can resolve a lost finalization response with one authoritative
read instead of replaying the write. Ordinary MCP Plan results omit this
transport field; terminal `prepare_file_uploads` deliberately returns it in the
upload manifest for the matching `finalize_file_uploads` call. Hosted
`upload_files` handles the batch internally. After an ambiguous MCP finalization
error, read the existing Plan and its current contract/inventory before deciding
whether another upload is needed. Ask and Create reject these endpoints.

Each finalization attempt keeps the stable per-batch File identity but copies
the uploaded bytes to an internal, attempt-unique destination path. The copy is
conditional on the exact temporary source generation and on the destination not
already existing. Immediately after the copy succeeds, the finalizer registers
its destination path and generation on the upload attempt before applying the
content-type metadata patch; that patch is conditional on the same destination
generation. The coordinates are therefore available for cleanup even if the
metadata patch fails, and are committed with the File and Report under the
Plan-operation fence when finalization reaches its checkpoint. A definitely
uncommitted attempt may clean up only the exact destination generation it
created, so it cannot delete a replacement from a winning attempt. An ambiguous
commit outcome retains the copy for reconciliation instead of guessing that it
is safe to delete.

The temporary source remains until the fenced File/Report checkpoint succeeds.
Finalization records the exact verified source generation in that checkpoint;
deletion is conditional on it and treats an already absent object as success. If that cleanup
fails, the report retains the completed upload-manifest entry and finalization
returns an error. A retry recognizes that completed entry and retries only the
idempotent source cleanup instead of copying the file or creating another File.

Before analyzing files, use the complete supplied Organize guidance or call
`get_guidelines` with `task: organize` when it is absent. Settle
structure and file placement first, then use the specialized form bundles and
exact schemas to add final submission values. Fetch the contract after uploads
and immediately before constructing the proposal. Include exactly one
`summarize_file` action per uploaded file with a grounded summary, two distinct
retrieval terms, and normally `search: true`. The server does not call a model
to repair form values or create file summaries.

The contract's `guidance_requirements` makes those bundle decisions
machine-readable. When action rules are not already clear from the current
schema/context, request `task: report_actions` with the unique selected
`actions`; when filling Forms, request `task: form_autofill`
with the unique actual `field_types` from the exact schemas. Identical requests
can reuse complete guidance already supplied for the same arguments. Each
conditional entry's `request` is valid as written
and retrieves the complete bundle. An optional `derived_request_arguments`
descriptor says which actual array values may be added to request a smaller
bundle; it is metadata, never a literal tool argument. Guideline responses report
`content_bytes` and `section_count`; contracts report their major component byte
sizes. Correlated API logs record tool-call sequence number, result bytes, and
elapsed time.

External Organize guidance is selected by the API route, not by a public client
or workflow flag. File-backed on-site/email Gemini retains its separate server-managed
summary, retrieval, structure-planning and form-completion stages. Those
internal planning instructions must not tell an external client to omit final
form values, and external no-server-model instructions must not replace the
built-in pipeline's responsibilities.

For Organize, `upload_inventory` is the authoritative finalized file scope even
when natural-language instructions mention fewer filenames. Its deterministic
fingerprint changes whenever the finalized set changes. `file_checklist` has one
entry per file for full inspection, duplicate checking, destination, action,
attachment, and summary. Shared proposal validation still enforces at least one
attachment and exactly one summary for every listed file and rejects unknown
file references or pending uploads. Inspection and duplicate judgment are model
work rather than server-observable facts, so the contract requires them while
the executable attachment/summary outcomes are enforced directly.

The external checklist's `duplicate_check` requires an evidence comparison,
not one search per filename. Compare the complete batch and already-read
destination/task evidence; one comparison may resolve several related files.
Search when an identity or occurrence question remains unresolved. A similar
filename or topic alone does not establish a duplicate. This clarification does
not change the native pipeline's automatic retrieval or permission checks.

Finalization creates durable report evidence so the draft can be resumed, but
does not publish those Files into ordinary workspace search. Exact references
in the contract and report remain usable for analysis and review. A File enters
search only after browser execution attaches it to a Page or Task; deleting or
undoing that last attachment hides report-only evidence again.

The file-backed external Organize contract remains permission-scoped and adds the
external-only `summarize_file` action without inferring a narrower action set
from the request. Its proposal schema uses standard JSON Schema `$defs` and
`oneOf` references, plus an OpenAPI-compatible `type` discriminator mapping and
explicit reference-group constraints. This is an external serialization
adapter; Gemini's provider-compatible structured-output schema remains
unchanged.

### Publication and browser approval

Fileless API/MCP Organize drafts expose an existing-record update subset:
completion, Form-value patches, document appends, additive schema changes,
rename/move and category/form attachment. `needs_review` handles ambiguous work.
Trusted API/email origin and the absence of uploads select this shared profile;
there is no new UI tool or client-controlled authorization flag. UI Organize
continues to require files (instruction-only UI requests still become Ask).

Start Organize and use the compact action list, then request
`get_plan_contract(actions=["update_form_values", "complete_task"])`
for exact shapes. Use read tools to identify the intended record and inspect its
current schema. Put final field patches before `complete_task`, with the patch's
id in completion's `depends_on`. Failed/skipped required updates prevent completion.
The completion action uses only `data.task` and optional `task_name`; it never
uses name-based matching or historical replacement semantics. Normal required
fields, recurrence, permissions, retry and undo still apply.

The current action vocabulary is deliberately not backward-compatible. Contract
version 7 uses `update_form_values`, `extend_form_schema`, `add_page_category`,
`suggest_page_deletion`, and one `attach_file` action. Recreate old saved proposals
that use retired action names; there are no execution aliases. Schema extension
remains additive, and a deletion suggestion still requires manual cleanup.

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

Uploading files switches back to the file-backed contract, including mandatory
summaries and placements for every file; pending uploads always block submission.
New-record creation belongs in Create when there are no uploaded artifacts.
No upload is necessary just to complete a Task or correct submission details.

Create and Organize submission saves a `ready` report and returns a compact
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
ready Create or Organize proposal, or completed Ask answer, can therefore be
edited and resubmitted directly while the plan remains reusable.

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

Submitting the same normalized result again is idempotent. A later valid Ask
result replaces the saved read-only answer. A ready Create plan also
remains open to permission-bounded reads and a complete replacement proposal so
an interactive chat can incorporate follow-up requests. Ready Organize plans
have the same revision behavior: revise the complete proposal, then submit it
again. Browser execution changes the report out of its reusable state and locks
further API revision. These interactive revision rules do not change the
delayed UI or email workflows.
Pending uploads, unknown or inaccessible references, disallowed actions,
malformed final submissions, and missing Organize file placements fail without
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

## Organize cURL example

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
  -d '{"tool":"organize","instructions":"Organize the uploaded records into pages."}' \
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

Fetch the shared Organize workflow after finalization, use the required read
tools and specialized bundles, then fetch the contract and submit the external
model's final JSON proposal:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"task":"organize"}}' \
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

`submission.json` contains `contract_version` and `proposal`:

```json
{
  "contract_version": 7,
  "proposal": {
    "summary": "Organize the records into a new page.",
    "confidence": 0.94,
    "issues": [],
    "actions": []
  }
}
```

The contract's `required_file_refs` means a real file-bearing proposal cannot
normally use an empty action list; it must place every uploaded file through an
allowed action and include exactly one `summarize_file` action for each file.
The summary action's `data` contains `file`, `summary`, `retrieval_terms` (two
distinct strings), and normally `search: true`. The external schema requires
the two terms and marks them unique; validation also rejects case-only
duplicates.

When `get_file` is called with `include_original: true`, the REST adapter
returns a five-minute `original_file.download_url` when the source is
available. Other transports may provide direct media instead. Extracted text
remains the default so clients do not fetch original bytes unnecessarily. A
metadata-only call reports when the REST download fallback is available but
does not create a signed URL. This remains true when the configured internal
model cannot directly attach that file's MIME type.

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
    json={"tool": "organize", "instructions": "Organize these files."},
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
organize_guidelines = api_json(
    "POST",
    f"{base}/plans/{plan['id']}/tools/get_guidelines",
    json={"arguments": {"task": "organize"}},
)["result"]
contract = api_json("GET", plan["contract_url"])
# Give the model the plan, tools, shared two-phase Organize guidelines, and
# contract. Run requested reads; settle structure first; then apply form_autofill
# and exact schemas to add final values before POSTing to plan["submit_url"].
```
