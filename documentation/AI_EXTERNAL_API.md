# External Agent API

Lagniappe exposes a versioned, REST-first API that lets a user run the same
permission-bounded read tools as the built-in AI workflows. An external client
chooses `ask`, `create`, or `organize` for each durable plan. Ask publishes a
read-only answer; Create and Organize publish proposals for browser review and
can execute that exact validated proposal only after an explicit user request.
External plans never call Lagniappe's configured model.

The feature is included and enabled in generated deployment settings through
`EXTERNAL_AGENT_API_ENABLED: true`. An operator can set it to `false` as an
emergency or policy shutoff. Eligible users need at least `ASK` AI access and
must not be public users. `CREATE` AI access is additionally required for
Create, Organize, and deterministic execution.

## Security model

- A user can have one active API key. Generating another key immediately
  invalidates the old one.
- Keys expire after 30 days and can be revoked from the user's own Settings
  panel. The full secret is shown only when generated; Datastore stores only a
  SHA-256 digest.
- `/api/v1` accepts `Authorization: Bearer ...` only. A browser login cookie is
  not an authentication fallback, and the API blueprint is CSRF-exempt for
  that reason.
- API calls run as the key's user. Existing read-tool handlers enforce that
  user's normal entity permissions. Plan access is also bound to its creator.
- Successful Create or Organize submission returns a one-hour execution key
  exactly in that response. Only its SHA-256 digest is stored. The key is bound
  to the plan, proposal fingerprint, creator, and current bearer-key
  generation, and is consumed when execution is first requested. Submitting
  the identical proposal again rotates the execution key. Ask is read-only and
  never issues an execution key.
- Proposal validation and key issuance do not authorize execution. An agent
  may call the distinct `/execute` operation only when the user's request
  explicitly includes it. Lagniappe cannot prove what a user said to an
  external client, so the OpenAPI contract makes this client obligation
  explicit while the server limits the capability to the reviewed proposal.
- Existing entities are represented as `hash:<12-character-hash>` references.
  URL-safe Datastore keys are rejected in submitted proposals.
- API responses are `no-store`; no CORS policy is added. Original-file URLs,
  when explicitly requested through `get_file`, are signed for five minutes.
- Limits are 60 general requests per minute per user/IP, 10 new plans per hour,
  100 tool calls per plan, and 100 proposal actions. Organize additionally
  allows 20 files per plan, 30 MiB per file, and 50 MiB total.

## Workflow

All endpoints are under `/api/v1` and require the bearer key, including the
OpenAPI document. The OpenAPI `info.description` and operation descriptions
carry the tool-selection rules, lifecycle, and boundary between submission and
explicit execution. Every plan response returns its opaque identifier as the
top-level `id`. A plan's tool is immutable for auditability, but a conversational
client may create another plan with a different tool whenever the user's intent
changes.

1. `GET /me` verifies the actor and reports separate Ask, Create, Organize, and
   execution capabilities.
2. `GET /tools` returns permission-bounded read tools as plain JSON Schema.
3. `POST /plans` creates a provider-free draft with `tool` set to `ask`,
   `create`, or `organize`.
4. Run permitted reads with `POST /plans/{id}/tools/{tool_name}` while the plan
   remains a draft.
5. `GET /plans/{id}/contract` returns the selected tool's authoritative output
   schema, workflow rules, reference rules, permissions, limits, and the
   actor-timezone `current_date`.
6. `POST /plans/{id}/submit` validates and publishes the final result. It never
   calls a provider or executes workspace actions.

### Ask

Ask requires `ASK` access and is read-only. The client answers the specific
question from permitted workspace tools and outside research when useful. Its
final object contains a direct plain-text `summary`, optional
`answer_markdown`, a confidence value, and an empty `actions` array. Trusted
application code renders `answer_markdown` through the shared sanitized,
editor-compatible Markdown pipeline and stores the resulting `answer_html` for
the report view. Submission moves the report directly to `complete`; it returns
preview and review URLs but no execution key. Ask rejects uploads and execution.
Internal hash tokens remain tool-call references and may not appear as visible
answer text. When a read tool returns a URL containing such a token, clients may
use that exact URL as a Markdown link destination with the entity's human name
as its link label. The external submission accepts the advertised Ask fields
only; clients cannot submit pre-rendered `answer_html` or bypass the shared
Markdown sanitizer.

If the conversation changes from investigation to requested work, the client
creates a separate Create or Organize plan rather than placing mutations in an
Ask response.

### Create

Create requires `CREATE` access. The client inspects existing workspace
structure before proposing new forms, categories, projects, model tasks, pages,
or tasks. It uses the same permission-filtered action schema and on-demand
guidelines as internal Create. The proposal must contain at least one allowed
action or `needs_review`. Create does not accept plan uploads.

Optional page rich text is model-facing `document_markdown`. Proposal
validation renders it through the same sanitized Markdown pipeline used by the
frontend document editor and stores legacy executable `document` HTML. This
keeps new internal and external model contracts aligned while allowing already
ready HTML proposals to execute unchanged.

### Organize

Organize requires `CREATE` access and at least one finalized upload. Use
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

### Publication and execution

Create and Organize submission saves a `ready` report and returns the full
`review_url`, shorter creator-session `preview_url`, and a shown-once one-hour
`execution_key`. Stop unless the user's request explicitly includes execution.
When it does, send that key to `POST /plans/{id}/execute`; the existing deferred
runner applies the exact validated proposal without a model call. Poll
`status_url` or `GET /plans/{id}` for bounded progress and result counts.

Submitting the same normalized result again is idempotent. For Create and
Organize it rotates the execution key; a different result cannot replace an
already published report. Pending uploads, unknown or inaccessible references,
disallowed actions, malformed final submissions, and missing Organize file
placements fail without model repair. Exact form fields remain authoritative at
the normal `SubmitterMixin` execution boundary. A completed-task date later
than the submitting user's current date is rejected; future work remains open.

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

The Create and Organize submit response carries `execution_key` and
`execution_key_expires_at`. Only if the user's request explicitly includes
execution, make the distinct write call and then poll the top-level plan state:

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer $LAGNIAPPE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"execution_key\":\"$EXECUTION_KEY\"}" \
  "$LAGNIAPPE_URL/api/v1/plans/$PLAN_ID/execute"

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
  "contract_version": 2,
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
