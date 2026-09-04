# External Agent API

Lagniappe exposes a versioned, REST-first API that lets a user run the same
permission-bounded read tools as the built-in AI workflows. An external client
chooses `ask`, `create`, or `organize` for each durable plan. Ask publishes a
read-only answer; Create and Organize publish proposals for browser review and
leave approval and application to the existing authenticated website controls.
External plans never call Lagniappe's configured model, and the external API
has no operation that applies a proposal to the workspace.

The API is part of the application rather than a deployment-wide optional
feature. Every authenticated non-public user may manage a key and use Ask,
Create, and Organize, regardless of the user's site AI-access setting. That
setting controls Lagniappe-funded model-provider calls; an external client uses
its own model and tokens. Revoking the user's API key is the external-agent
operational shutoff.

## Security model

- A user can have one active API key. Generating another key immediately
  invalidates the old one.
- Keys expire after 30 days and can be revoked from the user's own Settings
  panel. The full secret is shown only when generated; Datastore stores only a
  SHA-256 digest.
- `/api` and `/api/v1` accept `Authorization: Bearer ...` only. A browser login
  cookie is not an authentication fallback, and the API blueprints are
  CSRF-exempt for that reason.
- API calls run as the key's user. Existing read-tool handlers enforce that
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
- Limits are 60 general requests per minute per user/IP, 10 new plans per hour,
  100 tool calls per plan, and 100 proposal actions. Organize additionally
  allows 20 files per plan, 30 MiB per file, and 50 MiB total.

## MCP evaluation adapter

The optional `lagniappe-mcp` process is a user-local stdio adapter over this
REST API. It is not imported or executed by the site. Its public manifest is at
`/mcp/manifest.json`; that no-store response identifies the application build,
one current supported adapter release, its content-addressed wheel, Python
range, proven platform, exact dependency-wheel graph, and API/contract range.
Wheel URLs remain immutable for their declared support window and require no
cookie, bearer key, signed URL, or OAuth exchange.

The `serve` command and its REST mapping are client-neutral: a conforming local
stdio MCP harness can launch the same adapter. Automatic client-configuration
mutation and the current interoperability evidence are specific to the pinned
Codex trial client. Other CLI, IDE, desktop, or GUI clients remain unvalidated
integrations until their own interoperability smokes pass; protocol
compatibility alone is not an advertised support claim.

During the trial, setup instructions appear inside a signed-in user's existing
**External agent API** Settings panel only when both the site evaluation flag
and that user's explicit actor allowlist entry are present. The browser first
requires its current origin to match configured `APP_URL`, `CUSTOM_DOMAIN`, or
the explicit version-targeted evaluation origin. It then fetches the manifest
with a literal same-origin path, omitted credentials, no-store cache mode, and
redirect refusal. The service worker does not intercept `/mcp/`.

The initial supported tuple is Linux x86_64 with glibc 2.17 or newer and
CPython 3.14. The panel shows
the validated pipx 1.17.2 path, forcing pip and binary-only dependencies:

```bash
pipx install --python python3.14 --backend pip --pip-args='--only-binary=:all: --no-cache-dir' \
  "https://example.test/mcp/releases/0.1.0/<sha256>/lagniappe_mcp-0.1.0-py3-none-any.whl#sha256=<sha256>"
lagniappe-mcp configure codex --url "https://example.test" \
  --profile personal --allowed-root "/path/the-user-approves"
lagniappe-mcp check --profile personal
```

Run `pipx ensurepath` when needed, open a fresh shell, and restart Codex. The
explicit `--python python3.14` prevents pipx from choosing the interpreter that
runs pipx when that interpreter cannot satisfy the adapter's Python 3.14 range.
The wheel hash fragment and URL path bind the same release digest. A `uv tool`
command is deliberately not shown: the pinned uv trial proved its direct-wheel
URL fragment did not fail closed on a wrong digest. Public-index access remains
necessary for the wheel's exact dependencies; the adapter lock controls only
repository builds/tests, not this direct-wheel installation. Run the diagnostic
after entering the key and before relying on the client registration.

Reinstall the exact same content-addressed release by repeating the advertised
command with `--force`:

```bash
pipx install --force --python python3.14 --backend pip --pip-args='--only-binary=:all: --no-cache-dir' \
  "https://example.test/mcp/releases/<version>/<sha256>/lagniappe_mcp-<version>-py3-none-any.whl#sha256=<sha256>"
```

When the site manifest advertises another compatible release, the same closed
command shape performs either an upgrade or an intentional downgrade by naming
that release's exact version, path, and digest:

```bash
pipx install --upgrade --python python3.14 --backend pip --pip-args='--only-binary=:all: --no-cache-dir' \
  "https://example.test/mcp/releases/<selected-version>/<selected-sha256>/lagniappe_mcp-<selected-version>-py3-none-any.whl#sha256=<selected-sha256>"
lagniappe-mcp check --profile personal
```

The initial public ledger contains only `0.1.0`, so no public downgrade is
currently available. Never install an unadvertised predecessor or a release
whose API/contract or platform metadata does not match the current site.

Generate or rotate the shown-once API key only after installing. `configure`
prompts without echo and stores it in the owner-only local profile; generated
Codex configuration contains the absolute adapter executable and profile name,
never the bearer. In `--profile personal`, `personal` is only the local profile
name; the URL and key are read from that protected profile rather than placed in
the MCP registration. Uninstall in this order: revoke the site key, run
`configure codex --remove --profile personal`, then `credentials remove
--profile personal`, `profile remove --profile personal`, and finally uninstall
the isolated pipx tool.

The owner-only profile is a credential-placement boundary, not a sandbox around
the AI client. Codex, the adapter, and other processes running as the same OS
user may have permission to read it; a client with unrestricted local shell or
file access can therefore obtain the saved key. The profile keeps the bearer out
of client configuration, MCP arguments/results, and model-authored HTTP, but it
does not isolate that bearer from the local user account.

For a secondary nonpersistent Codex registration, keep the URL and key in the
Codex parent process environment and allowlist their names instead of writing a
literal secret into `config.toml`. Replace the command and root placeholders
with absolute paths:

```toml
[mcp_servers.lagniappe-env]
command = "/absolute/path/to/lagniappe-mcp"
args = ["serve", "--from-env", "--allowed-root", "/path/the-user-approves"]
env_vars = ["LAGNIAPPE_URL", "LAGNIAPPE_API_KEY"]
startup_timeout_sec = 30
tool_timeout_sec = 300
required = false
default_tools_approval_mode = "writes"
```

This form persists only the variable names. Set `LAGNIAPPE_URL` and
`LAGNIAPPE_API_KEY` in the environment that launches Codex; do not paste the
key into the TOML file or a shell-history-bearing command. Environment
forwarding is not general shell isolation either: the client process and other
same-user processes may be able to inspect the ambient value. OAuth would
replace this bearer with another local credential, such as a refresh token, but
would not remove the same-user host trust boundary.

For the manual evaluation, the REST Skill baseline and MCP candidate both use
this same `/api/v1` contract. Freeze one application build and build marker,
actor/key, permissions, workspace state, and client/model settings. Run the two
arms in separate fresh sessions and configurations—Skill-only for the baseline,
MCP-only for the candidate—and do not deploy, reinstall, upgrade, downgrade, or
retune either environment between measured arms.

Before freezing the isolated candidate configuration, rerun its configuration
with the trial-only mandatory-server setting (and the same URL/profile; omitted
roots retain the saved roots):

```bash
lagniappe-mcp configure codex --url "https://example.test" \
  --profile personal --trial-required
```

This regenerates the owned fingerprinted block with `required = true`, so a
startup failure cannot silently turn a candidate arm into a non-MCP run. The
ordinary Settings command deliberately omits this flag and writes
`required = false`. Do not hand-edit the TOML value: `required` participates in
the entry ownership fingerprint.

## Workflow

All working endpoints are under `/api/v1` and require the bearer key, including
the API index and OpenAPI document. `GET /api` identifies the current version;
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
5. `POST /plans` creates a provider-free draft with `tool` set to `ask`,
   `create`, or `organize`. The returned Plan includes canonical `contract_url`,
   `submit_url`, and `status_url` links so callers do not construct paths.
6. Run permitted reads with `POST /plans/{id}/tools/{tool_name}` while the plan
   is a draft. Reads remain available after a saved Ask answer and while a
   Create or Organize proposal remains ready for browser review.
7. `GET /plans/{id}/contract` returns the selected tool's authoritative output
   schema, submission wrapper, machine-readable guidance requirements, workflow
   and reference rules, permissions, payload sizes, limits, actor timezone,
   personal Page reference, timezone-aware `current_date`, and top-level
   `contract_version`. Its `submission_format` gives the exact `POST` method,
   URL, and wrapper body shape. Organize also returns the authoritative
   finalized-upload inventory and per-file checklist.
8. `POST /plans/{id}/submit` validates and publishes the final result. It returns
   a compact receipt containing status, review URLs, and the normalized proposal
   fingerprint rather than echoing the proposal. It never calls a provider or
   applies workspace actions. Repeating this call with a valid complete result
   replaces the prior result while the report remains reusable; `status_url`
   retrieves the detailed Plan resource.

Contract version 6 is an intentional breaking cutover: the contract uses only
top-level `contract_version`, and primary read-tool subjects use only `id`.
There are no legacy aliases. Clients must refresh discovery, OpenAPI, the tool
catalog, and the current Plan contract rather than replaying a version 5 shape.
Absolute API and review links use the installation's validated configured
origin; an incoming HTTP `Host` header never selects their destination.

### Minimal client skill

The authenticated discovery response includes `client_skill_url`. Its Markdown
response is the canonical short bootstrap for clients that support local
skills. For Pi, install or refresh it with:

```bash
mkdir -p ~/.pi/agent/skills/lagniappe
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  https://lagniappe.site/api/v1/client-skill.md \
  -o ~/.pi/agent/skills/lagniappe/SKILL.md
```

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

When an Ask answer is ready, the client fetches the latest contract and submits
it without asking for separate save permission, then returns the answer and
`preview_url` to the user. Saving this report does not modify workspace records.
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
or tasks. It uses the same permission-filtered action schema and on-demand
guidelines as internal Create. The proposal must contain at least one allowed
action or `needs_review`. Create does not accept plan uploads.

`create_task` is always part of the Create and Organize action contracts because
every user has an editable personal Page. The coarse capability projection does
not expose a redundant `can_create_tasks` flag. A Task proposal must still name
an editable target in `data.page`, or use `data.page_action` when an earlier
proposal action creates the target Page. `page_name` is display context only and
does not satisfy this requirement. Use `personal_page.hash` for a request
concerning the authenticated user's own Page. Proposal submission rejects a
Task without an executable Page reference, and the deterministic runner does not
gain permission to write to any other Page.

Ordinary `search_entities` calls retain the main full-text cache query used by
the application. `match_mode: "exact_name"` selects a separate bounded cache
lookup with a final case-insensitive full-name check. When `kinds` is exactly
`["page"]`, `parent_id` may constrain that exact lookup to one viewable Category.
Exact results include view/edit/create permissions so a verified target need not
be loaded again solely to check editability. This addition does not change the
main search query, ranking, snippets, or website search behavior.

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
read instead of replaying the write. The MCP adapter validates this transport
field privately and removes it from MCP results. Ask and Create reject these
endpoints.

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

Before analyzing files, call `get_guidelines` with `task: organize`. Settle
structure and file placement first, then use the specialized form bundles and
exact schemas to add final submission values. Fetch the contract after uploads
and immediately before constructing the proposal. Include exactly one
`summarize_file` action per uploaded file with a grounded summary, two distinct
retrieval terms, and normally `search: true`. The server does not call a model
to repair form values or create file summaries.

The contract's `guidance_requirements` makes those bundle decisions
machine-readable. After selecting actions, request `task: report_actions` with
the unique selected `actions`; when filling Forms, request `task: form_autofill`
with the unique actual `field_types` from the exact schemas. Identical requests
are fetched once per run. Each conditional entry's `request` is valid as written
and retrieves the complete bundle. An optional `derived_request_arguments`
descriptor says which actual array values may be added to request a smaller
bundle; it is metadata, never a literal tool argument. Guideline responses report
`content_bytes` and `section_count`; contracts report their major component byte
sizes. Correlated API logs record tool-call sequence number, result bytes, and
elapsed time.

For Organize, `upload_inventory` is the authoritative finalized file scope even
when natural-language instructions mention fewer filenames. Its deterministic
fingerprint changes whenever the finalized set changes. `file_checklist` has one
entry per file for full inspection, duplicate checking, destination, action,
attachment, and summary. Shared proposal validation still enforces at least one
attachment and exactly one summary for every listed file and rejects unknown
file references or pending uploads. Inspection and duplicate judgment are model
work rather than server-observable facts, so the contract requires them while
the executable attachment/summary outcomes are enforced directly.

Finalization creates durable report evidence so the draft can be resumed, but
does not publish those Files into ordinary workspace search. Exact references
in the contract and report remain usable for analysis and review. A File enters
search only after browser execution attaches it to a Page or Task; deleting or
undoing that last attachment hides report-only evidence again.

The external Organize contract remains permission-scoped and adds the
external-only `summarize_file` action without inferring a narrower action set
from the request. Its proposal schema uses standard JSON Schema `$defs` and
`oneOf` references, plus an OpenAPI-compatible `type` discriminator mapping and
explicit reference-group constraints. This is an external serialization
adapter; Gemini's provider-compatible structured-output schema remains
unchanged.

### Publication and browser approval

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

Keep the key in an environment variable rather than putting it directly in
shell history:

```bash
export LAGNIAPPE_API_KEY='lgn_...'
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

curl --fail-with-body --silent --show-error \
  -X PUT -H 'Content-Type: application/pdf' \
  --upload-file records.pdf "$UPLOAD_SESSION_URL"

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
  "contract_version": 6,
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

plan = session.post(
    f"{base}/plans",
    json={"tool": "organize", "instructions": "Organize these files."},
).json()

path = Path("records.pdf")
upload_batch = session.post(
    f"{base}/plans/{plan['id']}/uploads",
    json={"files": [{
        "filename": path.name,
        "content_type": "application/pdf",
        "size": path.stat().st_size,
    }]},
).json()
upload = upload_batch["uploads"][0]

with path.open("rb") as source:
    requests.put(
        upload["session_url"],
        data=source,
        headers={"Content-Type": "application/pdf"},
    ).raise_for_status()

session.post(
    f"{base}/plans/{plan['id']}/uploads/finalize",
    json={"upload_batch_id": upload_batch["upload_batch_id"]},
).raise_for_status()
# Reuse this catalog for the rest of the run. Do not persist it as an HTTP cache.
tools = session.get(f"{base}/tools").json()
organize_guidelines = session.post(
    f"{base}/plans/{plan['id']}/tools/get_guidelines",
    json={"arguments": {"task": "organize"}},
).json()["result"]
contract = session.get(plan["contract_url"]).json()
# Give the model the plan, tools, shared two-phase Organize guidelines, and
# contract. Run requested reads; settle structure first; then apply form_autofill
# and exact schemas to add final values before POSTing to plan["submit_url"].
```
