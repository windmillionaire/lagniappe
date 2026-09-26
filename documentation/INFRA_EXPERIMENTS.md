# Experiments installation

Create a separate normal installation from a fresh checkout and a dedicated
project with `./setup.sh --experiments`. Select `lagniappe-experiments` when
setup asks for the project. The flag applies to initial installation, not to
subcommands or conversion of another installation. Interrupted setup retains
its experiments intent. Later updates use `./setup.sh update` without repeating
the flag. Use the normal production runtime and a dedicated Redis database.

Setup configures normal Google sign-in, enables AI/external AI and MCP, and
prepares the Python, Node, managed MCP, and Playwright tools. Normal application
startup creates the Owner and an **Administrator agent**, including their
personal Pages, through the existing User mutation lifecycle. Stable account
keys and guarded writes prevent duplicate creation across concurrent workers.
The bootstrap marker preserves subsequent permission changes and deletions;
startup never restores a deliberately removed role or account. Initial setup
verifies the saved accounts before reporting deployment completion.

The Owner signs in with Google. The agent uses `/users/agent-login` and the
existing protected `AGENT_ACCESS_CODE` in
`config/files/lagniappe_settings.yaml`. Authorize the normal remote MCP OAuth
connection while signed in as that agent. Verify both browser and MCP actors.
Application accounts do not create Google accounts. Keep credentials and browser
session files out of attachments and source control.

## Saved startup settings

`config/experiments.py` supplies disabled defaults on ordinary installations.
These settings survive update, repair, and recovery in the protected application
settings file. Deploy changes with the ordinary update command.

| Setting | Experiments preset | Meaning |
| --- | --- | --- |
| `EXPERIMENTS_ENABLED` | `true` | Enable this installation's experiments features. |
| `EXPERIMENTS_PROJECT` | selected GCP project | Must exactly match `GOOGLE_CLOUD_PROJECT`. |
| `EXPERIMENTS_EXECUTION_ENABLED` | `true` | Admit the designated admin agent through verified remote MCP. |
| `EXPERIMENTS_DIAGNOSTICS` | `summary` | `off`, aggregate `summary`, or bounded operation `trace`. |
| `EXPERIMENTS_SOURCE_ID` | generated on deploy | SHA-256 of authored runtime/build inputs, including uncommitted files. |

Execution additionally requires AI/external AI, agent access, and the designated
user's current Administrator role. Disabling those policies remains a valid
configuration and removes execution authority. For a complete experiments
shutdown set execution false and diagnostics off before setting enabled false.

## Execution and durable records

The single additional MCP tool is `execute_plan`. It applies an already submitted
proposal through the same service as browser **Run** and the existing deferred
execution ledger. It accepts `plan_id`, the `proposal_fingerprint` from
`submit_plan`, and a stable `operation_id` (1–128 ASCII letters, digits, dots,
underscores, or hyphens). Repeat those exact values after an uncertain response;
poll `get_plan` for outcomes. Reusing an operation for another proposal fails.
The submitted fingerprint remains the retry identity after execution; Markdown
preparation operates on a copy of the proposal. An existing operation is matched
against the original submission and full job request before returning its receipt.
After a terminal recoverable failure, inspect the ledger and use a new operation
ID to resume that same plan; never recreate already successful actions.

Ordinary API keys and other actors cannot use execution. The HTTP boundary
checks the authenticated remote MCP envelope on every call, even if a client
cached an older tool list. Workers recheck the experiments policy and current
admin role at execution boundaries. Role removal stops subsequent boundaries;
it does not undo committed changes. OAuth revocation blocks new requests;
accepted work follows the ordinary job lifecycle. Configuration switches take
effect when the updated app version serves the work. Browser logout, login-code
rotation, API-key revocation, and MCP grant revocation remain distinct operations.

The app is the notebook. Create a Category per experiment, with Setup, Results,
fixture Pages/resources, and dated Run Pages. Attach the scripts, source patches
and new files, samples, sanitized logs, profiles, screenshots and conclusions.
Finalize uploads and execute the attachment proposal, then verify retrieval and
checksums. Cloud logs and local files are collection sources, not the permanent
record. Respect the live upload contract and split large captures as needed.

A File has one owning Page or Task. Attaching it to another destination moves
it; repeated attachment actions do not create shared copies. Give each artifact
one home and put its ordinary app File link on other Results/Run Pages that need
it. Verify the destination's file list as well as the original-byte checksum.
Keep original evidence when correcting a measurement, append a dated correction
to Results, and update misleading file descriptions through the normal File
Info form or an MCP Plan's `update_file` action. Existing-file metadata edits
require no upload or `file_usage` classification.

## Measurements and their limits

Summary/trace requests emit one structured stdout log with
`event = lagniappe.experiments.request` and a matching
`X-Lagniappe-Request-ID` response header. `Server-Timing` reports `lagniappe`;
`X-Lagniappe-Source-ID` identifies the deployed source. The log includes the
route pattern (never a concrete URL or query), status, available request/response
content lengths, source/version/instance, and operation aggregates.
App Engine's static-file responses bypass Flask and have no app summary;
capture their timing and sizes in the browser.

A service worker can return a cached response with an older request ID. Check
the matching log timestamp against the browser request before attributing that
server work to the current attempt. Page-level network captures may omit the
worker's background revalidation requests.

Collection starts before CSRF/authentication. The response hook runs after
other Flask response hooks. Duration excludes process startup, session-cookie
serialization, streaming body production, and network delivery; use browser
timings for user-visible latency. A missing byte count is unknown, not zero.

| Collector | Meaning and limits |
| --- | --- |
| Entity/auth/template | Inclusive fetch, mutation, browser auth-context and template-render spans; overlapping durations must not be added as total latency. API authorization is inside request time but not the browser auth-context span. |
| Datastore | SDK RPC invocations, query pages/returned rows, requested keys, submitted writes/deletes, allocation/transaction calls, errors and duration. SDK-internal transport retries and billable reads are not measured. |
| Redis | Executed single commands, immediate WATCH commands and pipeline batches/queued command counts. Hit/miss classification covers GET/HGET/JSON.GET only. Byte counts cover returned byte strings, not complete protocol traffic. |
| Storage | App-side HTTP methods, duration, HTTP errors, known in-memory request-body bytes and declared response lengths. Does not consume streams or measure browser-to-Storage transfers. Authentication refresh/retry inside the transport is not a separate count. |
| Jobs | Existing opaque telemetry IDs link the accepting request with worker-request summaries. Queue/lifetime/attempt/status evidence comes from existing deferred-job diagnostics. No new job state or diagnostics API. |

Trace mode adds at most 128 timed operation entries per request and reports
discarded entries. It is an operation timeline, not a Python stack profile.
Neither mode records provider arguments, Redis keys, entity IDs, document text,
cookies, credentials, signed URLs, or bodies. Export only the structured
experiments payload when archiving cloud evidence; provider request envelopes
and browser traces may contain other sensitive fields.

For example, collect recent summaries locally, then attach the reviewed JSON:

```bash
gcloud logging read 'resource.type="gae_app" AND jsonPayload.event="lagniappe.experiments.request"' --project=lagniappe-experiments --freshness=1h --limit=200 --format=json
```

Use explicit project and time bounds, retain request IDs, and record missing or
truncated coverage. Compare diagnostics off/summary overhead separately. Keep
instrumentation mode, browser conditions, region, instance class and workers
consistent across baseline/candidate samples.

For the P5-01 read-batching comparison, authenticated requests to
`GET /pages/<key>/tasks` may send `X-Lagniappe-Experiments-Task-List: batched`
or `unbatched`. Both use the same permissions, validators and render path;
the control reads revisions separately instead of with the initial auth roots.
The selector is ignored outside experiments installations; ordinary requests
use batching. With diagnostics enabled, `X-Lagniappe-Experiment` confirms the
selection and the summary adds `experiment` and worker `process` identifiers.
Alternate request order and verify version/instance (and worker distribution)
from joined logs; a shared hostname alone does not prove a shared instance.
This selector changes no content or HTTP cache semantics.

## Local measurement libraries

The development dependencies include
[web-vitals](https://github.com/GoogleChrome/web-vitals) and
[Pyinstrument](https://pyinstrument.readthedocs.io/en/latest/guide.html), alongside
the existing Playwright browser tools. They are installed by experiments setup;
neither adds automatic collection to the normal site's frontend or backend.

For browser experiments, inject the locally installed Web Vitals IIFE using
Playwright's `browser_context.add_init_script(path=...)`, followed by a small
collector, before opening the target. The installed package's
`dist/web-vitals.iife.js` exposes `webVitals.onLCP`, `onINP`, `onCLS`, `onFCP`, and
`onTTFB`. Record bounded numeric metrics locally; finalize lifecycle metrics by
changing page visibility or closing the measured page as the library documents.
Avoid CDN fetches and network analytics during the measured action. Retain the
library version and exact collector with the run. These page-lifecycle metrics
supplement the experiment's explicit readiness and save/persistence checks.
Define those boundaries using stable labels or state attributes. For example,
the TaskForm save button's label span becomes `Updated` while a separate success
icon remains briefly; comparing the whole button text incorrectly includes the
icon's disappearance delay. Verify stored values by reloading separately.

For a local backend reproduction, use the normal interpreter and a standalone
experiment script, for example:

```bash
venv/bin/python -m pyinstrument -r html -o /tmp/experiment-profile.html /tmp/experiment.py
```

This profiles Python executing locally; it cannot inspect the deployed server
by profiling an HTTP client. Remote stack/CPU profiling can use the existing
optional Sentry integration and its saved trace/profile sample-rate settings,
with a separate labelled diagnostic run and exported evidence. The request
collectors themselves require no Sentry account. Add another remote profiler
only when a specific experiment needs that evidence; memory/CPU profiles are
not included in the default summary. OpenTelemetry's Flask/Redis integrations
were considered; the initial request summaries avoid adding a collector/exporter
service alongside the existing logging and Sentry paths.

## Installation acceptance and first experiments

1. Through MCP, create **Experiment Installation**, its **Setup** and **Results**
   Pages, upload this guide and the installation's creation documents,
   and attach them through `execute_plan`. The original creation documents for
   `lagniappe-experiments` are archived on its Setup Page; ongoing plans and
   experiment records live on the app. Read back the Pages and file originals,
   verify checksums, and replay the same operation to check for duplicates.
2. Create a small Task Form containing two static HTML sections and one text
   field, plus one Task. Record exact fixture references and a readiness check
   that sees both sections and a usable field. Measure full navigation separately
   from opening the Task. Start with two warmups and ten recorded samples per
   condition; distinguish fresh-browser and warm runs. Join browser requests to
   backend logs and explain request fan-out, rendering and storage work.
3. In a separate experiment Category, change the one field, observe save
   completion, reload and verify the stored value. Record reset values and
   accumulated history. There is no required percentage speed improvement.

Setup/Results/fixtures/evidence must be retrievable from the app before calling
these pilots complete. Installation and live acceptance are separate steps.

## Sandbox updates

### Agent notebook

The `lagniappe-experiments` installation has an
[Agent Notebook](https://lagniappe-experiments.uc.r.appspot.com/categories/ahVsYWduaWFwcGUtZXhwZXJpbWVudHNyEwsSBm1vZGVscxiAgICE7IGICgw)
Category and [Agent Follow-up](https://lagniappe-experiments.uc.r.appspot.com/projects/ahVsYWduaWFwcGUtZXhwZXJpbWVudHNyEwsSBm1vZGVscxiAgID4wr2ECgw)
Project for incidental findings during other work. The app owns the notebook's
Pages, model tasks, forms, notes, and decisions. Changes to that structure or
content do not require repository edits or commits.

The user has authorized low-friction capture during other work; it does not
expand the active task into unrelated implementation. The
[Notebook Guide](https://lagniappe-experiments.uc.r.appspot.com/pages/ahVsYWduaWFwcGUtZXhwZXJpbWVudHNyFgsSCWluc3RhbmNlcxiAgICYpf6fCgw)
holds the current workflow, and the repository's `AGENTS.md` points future agents
to it. Keep each installation's notes in its own authorized workspace.

### Updating and retaining candidates

`./setup.sh update` preserves local source edits and rebuilds stale production
frontend assets on an experiments installation. It retains the normal project,
credentials, configuration and deployment checks. Local deployment authority is
separate from the agent's app Administrator role; `execute_plan` is not a shell
or deployment tool.

After the pilots are satisfactory, commit the reusable infrastructure. For later
experiments, attach the base commit, source digest, full patch/new files, relevant
non-secret settings and exact procedure before reverting a candidate. Reverting
source does not revert app data and takes effect remotely only after redeploying.
