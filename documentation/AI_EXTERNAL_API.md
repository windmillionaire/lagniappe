# External Agent API

Lagniappe exposes a versioned, REST-first API that lets a user run the same
permission-bounded read tools as the built-in AI workflows and submit an
Organize proposal for browser review. If the user's request explicitly includes
execution, the client can use a second, plan-scoped capability to run that exact
validated proposal through the normal deterministic report runner. External
clients do not call Lagniappe's configured model.

The feature is included and enabled in generated deployment settings through
`EXTERNAL_AGENT_API_ENABLED: true`. An operator can set it to `false` as an
emergency or policy shutoff. Eligible users need `CREATE` AI access and must
not be public users.

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
- Successful proposal submission returns a one-hour execution key exactly in
  that response. Only its SHA-256 digest is stored. The key is bound to the
  plan, proposal fingerprint, creator, and current bearer-key generation, and
  is consumed when execution is first requested. Submitting the identical
  proposal again rotates the execution key.
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
  100 tool calls per plan, 20 files per plan, 30 MiB per file, 50 MiB total,
  and 100 proposal actions.

## Workflow

All endpoints are under `/api/v1` and require the bearer key, including the
OpenAPI document. The OpenAPI `info.description` and operation descriptions
carry this lifecycle, request preconditions, and the boundary between proposal
submission and explicitly requested execution so a generic client does not
need separate prompt instructions. Every plan response
returns its opaque identifier as the top-level `id`; it is not nested inside
the proposal schema.

1. `GET /me` verifies the actor and capability.
2. `POST /plans` creates a durable, provider-free Organize draft.
3. `POST /plans/{id}/uploads` creates resumable Cloud Storage sessions.
4. Upload bytes to each returned `session_url`, then call
   `POST /plans/{id}/uploads/finalize`.
5. `GET /tools` returns plain JSON Schema tool definitions. Before analyzing
   files, call `get_guidelines` with `task: organize`. Its first phase uses the
   same structural planning policy as the internal Gemini Organize prompt; do
   not submit that intermediate structure. Run tools with
   `POST /plans/{id}/tools/{tool_name}` and an `arguments` object.
6. Call other read tools and the specialized guideline bundles required by the
   shared workflow while the plan remains a draft. In the second phase, use
   `form_autofill` and each exact form schema to add final submissions or
   updates to the structural actions. API drafts do not receive the internal
   prompt's optional prefetched `workspace_searches`; use
   `list_workspace_resources` when those candidates are absent, then fetch only
   the specialized bundles required by the actions being proposed.
7. `GET /plans/{id}/contract` returns the final proposal schema, workflow and
   reference rules, allowed actions, permission context, file references,
   limits, and the actor-timezone `current_date`. Fetch it after uploads and
   immediately before constructing the proposal.
8. Include one `summarize_file` action for each uploaded file, using the same
   source understanding the client already used to organize it. Each action
   carries a concise grounded summary, exactly two broad retrieval terms, and
   `search: true`; reading a local upload source again through `get_file` is not
   required. Internal Organize creates the equivalent summary in its provider
   prepass, so this action is advertised only to external plans.
9. `POST /plans/{id}/submit` validates and saves the proposal as a ready report.
   The response includes the full `review_url`, a shorter creator-session
   `preview_url`, and a shown-once `execution_key`. Submission itself never
   executes the proposal.
10. Stop for review unless the user's request explicitly includes execution.
    When it does, send the plan-scoped key to
    `POST /plans/{id}/execute`. This invokes the existing deterministic deferred
    runner without a model call. Poll the returned `status_url` or
    `GET /plans/{id}` for bounded operation state and action counts.

Submitting the same normalized proposal again is accepted and leaves that
proposal unchanged, but rotates the shown-once execution key so a client can
recover from a lost or expired response. A different proposal cannot replace
an already-ready report. Pending uploads,
unknown/inaccessible references, disallowed actions, missing required
submission objects, and files that are not placed by the plan all fail
proposal validation without model repair. Exact form fields are validated and
normalized by the same `SubmitterMixin` path used by ordinary deterministic
report execution after browser review; `/submit` does not create temporary
entities merely to duplicate that validation. At least one finalized uploaded
file is required before submission; the plan contract repeats that precondition
in `workflow_rules`. The external client must complete both planning phases:
the server does not call a model to fill or repair form values before review or
execution. It also does not invoke a model to create external file summaries.
The proposed summaries and retrieval terms become durable, searchable file
metadata only if the reviewed plan is executed; a rejected or unexecuted
proposal does not change the files. Execution is capability-bounded, but it
still performs the proposal's workspace mutations, so clients must not infer
consent from successful validation or possession of the key. A completed-task
date later than the
submitting user's current date is rejected deterministically; future work must
remain open.

The browser review projects proposed submission values beneath each action,
using the referenced form's human field, option, and table-column labels when
available. Submission previews start on their own line. This projection makes
the stored proposal reviewable but does not normalize or change it; the
deterministic execution path remains authoritative.

Failures under `/api/v1`, including routing-level `404` and `405` responses,
use the same JSON error envelope and request ID. A `405` preserves the HTTP
`Allow` header.

## cURL example

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

The submit response carries `execution_key` and `execution_key_expires_at`.
Only if the user's request explicitly includes execution, make the distinct
write call and then poll the top-level plan state:

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
  "contract_version": 1,
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

## REST versus MCP

REST is the canonical interface because it is easy to inspect, automate, test,
and use from any language. MCP would not replace this authorization or domain
logic; it would advertise the tool catalog and adapt MCP tool calls to these
same operations. An MCP adapter becomes useful when a client already speaks
MCP and can discover tools automatically, but it is optional interoperability,
not a more capable backend. An adapter must preserve the explicit-consent rule
for the execution write; merely exposing the write as an MCP tool must not make
submission trigger it automatically.
