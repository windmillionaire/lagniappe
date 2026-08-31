# External Agent API

Lagniappe exposes a versioned, REST-first API that lets a user run the same
permission-bounded read tools as the built-in AI workflows and submit an
Organize proposal for browser review. External clients do not call Lagniappe's
configured model, and the API never executes a submitted plan.

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
carry this lifecycle, request preconditions, and the no-execution boundary so a
generic client does not need separate prompt instructions.

1. `GET /me` verifies the actor and capability.
2. `POST /plans` creates a durable, provider-free Organize draft.
3. `POST /plans/{id}/uploads` creates resumable Cloud Storage sessions.
4. Upload bytes to each returned `session_url`, then call
   `POST /plans/{id}/uploads/finalize`.
5. `GET /tools` returns plain JSON Schema tool definitions. Before analyzing
   files, call `get_guidelines` with `task: organize`; this returns the same
   end-to-end Organize workflow used by the internal Gemini prompt. Run tools
   with `POST /plans/{id}/tools/{tool_name}` and an `arguments` object.
6. Call other read tools and the specialized guideline bundles required by the
   shared Organize workflow while the plan remains a draft.
7. `GET /plans/{id}/contract` returns the final proposal schema, workflow and
   reference rules, allowed actions, permission context, file references, and
   limits. Fetch it after uploads and immediately before constructing the
   proposal.
8. `POST /plans/{id}/submit` validates and saves the proposal as a ready report.
   The response's `review_url` opens the normal deterministic report workflow.

Submission is idempotent when the same normalized proposal is sent again. A
different proposal cannot replace an already-ready report. Pending uploads,
unknown/inaccessible references, disallowed actions, incomplete form values,
and files that are not placed by the plan all fail validation without model
repair. At least one finalized uploaded file is required before submission;
the plan contract repeats that precondition in `workflow_rules`.

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
allowed action.

When `get_file` is called with `include_original: true`, the REST adapter
returns a five-minute `original_file.download_url` when the source is
available. Other transports may provide direct media instead. Extracted text
remains the default so clients do not fetch original bytes unnecessarily.

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
# Give the model the plan, tools, shared Organize guidelines, and contract; run
# requested reads and specialized guideline calls, then POST to /submit.
```

## REST versus MCP

REST is the canonical interface because it is easy to inspect, automate, test,
and use from any language. MCP would not replace this authorization or domain
logic; it would advertise the tool catalog and adapt MCP tool calls to these
same operations. An MCP adapter becomes useful when a client already speaks
MCP and can discover tools automatically, but it is optional interoperability,
not a more capable backend.
