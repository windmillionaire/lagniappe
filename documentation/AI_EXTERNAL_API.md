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
- API responses are `no-store`; no CORS policy is added. Original-file URLs,
  when explicitly requested through `get_file`, are signed for five minutes.
- Limits are 60 general requests per minute per user/IP, 10 new plans per hour,
  100 tool calls per plan, and 100 proposal actions. Organize additionally
  allows 20 files per plan, 30 MiB per file, and 50 MiB total.

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
changes.

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
   `list_workspace_resources` includes the personal Page alongside the
   permission-filtered workspace inventory.
5. `POST /plans` creates a provider-free draft with `tool` set to `ask`,
   `create`, or `organize`.
6. Run permitted reads with `POST /plans/{id}/tools/{tool_name}` while the plan
   is a draft. Reads remain available after a saved Ask answer and while a
   Create or Organize proposal remains ready for browser review.
7. `GET /plans/{id}/contract` returns the selected tool's authoritative output
   schema, submission wrapper, workflow rules, reference rules, permissions,
   limits, actor timezone, personal Page reference, and timezone-aware
   `current_date`.
8. `POST /plans/{id}/submit` validates and publishes the final result. It never
   calls a provider or applies workspace actions. Repeating this call with a
   valid complete result replaces the prior result while the report remains
   reusable.

### Minimal client skill

The authenticated discovery response includes `client_skill_url`. Its Markdown
response is the canonical short bootstrap for clients that support local
skills. For Pi, install or refresh it with:

```bash
mkdir -p ~/.pi/agent/skills/lagniappe
curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  https://lagniappe.site/api/v1/client-skill.md \
  -o ~/.pi/agent/skills/lagniappe/SKILL.md
```

The skill deliberately contains no action schemas, permission lists, or
mode-specific proposal instructions. Those remain live in discovery, OpenAPI,
and each plan contract so installed copies stay useful as the API evolves.

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
an editable target; use `personal_page.hash` for a request concerning the
authenticated user's own Page. Proposals and the deterministic runner do not
gain permission to write to any other Page.

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
`POST /plans/{id}/uploads/finalize`. Ask and Create reject these endpoints.

Before analyzing files, call `get_guidelines` with `task: organize`. Settle
structure and file placement first, then use the specialized form bundles and
exact schemas to add final submission values. Fetch the contract after uploads
and immediately before constructing the proposal. Include exactly one
`summarize_file` action per uploaded file with a grounded summary, two distinct
retrieval terms, and normally `search: true`. The server does not call a model
to repair form values or create file summaries.

### Publication and browser approval

Create and Organize submission saves a `ready` report and returns the full
`review_url` and shorter creator-session `preview_url`. Present the preview and
direct the user to review and approve it on the authenticated website. The
external API deliberately has no `/execute` operation. The existing browser
Execute control starts the normal deterministic runner and applies the exact
validated proposal without a model call.

Opening, changing, executing, retrying, undoing, or deleting a saved report is
provider-free and therefore does not require site AI access. Those browser
operations still require the report owner's authenticated session, CSRF where
applicable, a valid report state, and current permission for every affected
resource. Internal report revision is different: it calls Lagniappe's configured
provider and still requires the corresponding site AI-access level. External
reports cannot invoke that provider-backed revision route.

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

The browser review projects proposed submission values beneath each action,
using the referenced form's human field, option, and table-column labels when
available. Submission previews start on their own line. This projection makes
the stored proposal reviewable but does not normalize or change it; the
deterministic execution path remains authoritative.

Failures under `/api/v1`, including routing-level `404` and `405` responses,
use the same JSON error envelope and request ID. A `405` preserves the HTTP
`Allow` header.

## Organize cURL example

Keep the key in an environment variable rather than putting it directly in
shell history:

```bash
export LAGNIAPPE_API_KEY='lgn_...'
export LAGNIAPPE_URL='https://your-app.example'

curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  "$LAGNIAPPE_URL/api/v1/me"

curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"tool":"organize","instructions":"Organize the uploaded records into pages."}' \
  "$LAGNIAPPE_URL/api/v1/plans"
```

Use the returned plan `id` to start an upload:

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"files":[{"filename":"records.pdf","content_type":"application/pdf","size":12345}]}' \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/uploads"

curl --fail --silent --show-error \
  -X PUT -H 'Content-Type: application/pdf' \
  --upload-file records.pdf "$UPLOAD_SESSION_URL"

curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' -d '{}' \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/uploads/finalize"
```

Fetch the shared Organize workflow after finalization, use the required read
tools and specialized bundles, then fetch the contract and submit the external
model's final JSON proposal:

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"task":"organize"}}' \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/tools/get_guidelines"

curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/contract"

curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @submission.json \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/submit"
```

Present the returned `preview_url` and direct the user to the authenticated
website to review and approve the proposal there. The API performs no further
write step. A client may fetch the plan later to observe its top-level state:

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID"
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
  "contract_version": 4,
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
distinct strings), and normally `search: true`.

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
upload = session.post(
    f"{base}/plans/{plan['id']}/uploads",
    json={"files": [{
        "filename": path.name,
        "content_type": "application/pdf",
        "size": path.stat().st_size,
    }]},
).json()["uploads"][0]

with path.open("rb") as source:
    requests.put(
        upload["session_url"],
        data=source,
        headers={"Content-Type": "application/pdf"},
    ).raise_for_status()

session.post(f"{base}/plans/{plan['id']}/uploads/finalize", json={}).raise_for_status()
tools = session.get(f"{base}/tools").json()
organize_guidelines = session.post(
    f"{base}/plans/{plan['id']}/tools/get_guidelines",
    json={"arguments": {"task": "organize"}},
).json()["result"]
contract = session.get(f"{base}/plans/{plan['id']}/contract").json()
# Give the model the plan, tools, shared two-phase Organize guidelines, and
# contract. Run requested reads; settle structure first; then apply form_autofill
# and exact schemas to add final values before POSTing to /submit.
```
