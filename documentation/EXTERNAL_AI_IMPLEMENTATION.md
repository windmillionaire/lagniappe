# External AI implementation overview

This is a broad account of how Lagniappe's external-agent support developed,
through the September 2026 integration into `next/1.3.0`. The current result is
one REST API, an optional skill for direct API clients, and one optional remote
MCP service. The local MCP experiment informed the design but is no longer
maintained or distributed.

For current contracts and commands, use [AI_EXTERNAL_API.md](AI_EXTERNAL_API.md),
[Authentication](AUTHENTICATION.md#remote-mcp), and
[Deployment](INFRA_DEPLOYMENT.md#remote-mcp-service). Evaluation procedure lives
in [TESTING_AI_PROCESS.md](TESTING_AI_PROCESS.md); individual results remain in
the [workflow case library](../testing_ai_workflows/README.md).

## Start with the application API

The first step exposed Lagniappe's existing permission-bounded reads and
Ask/Create/Organize workflows to an external model. The application remained
responsible for identity, permissions, validation, persistence and execution.
External clients supplied their own model and tokens rather than invoking the
site's configured provider.

The central decision was to preserve the existing review boundary. Ask saves a
read-only answer. Create and Organize save a proposal which the user reviews
and executes on the authenticated website. There is no external execute tool.
Uploads become durable report evidence before review, but do not thereby become
filed workspace content. A model can revise a ready proposal without starting
the work again; browser execution closes that revision window.

The REST API made those rules discoverable through an authenticated index,
OpenAPI document, tool schemas and a current contract for each Plan. Public
references, field-addressed validation errors, compact submission receipts and
recoverable upload batches made it possible for clients to correct mistakes
through the public interface. Existing application logic remained authoritative
instead of duplicating an execution engine for external agents.

The September usability pass separated conversation from persistence. An agent
can now retrieve and answer without a Plan; `answer_question` supplies context
and instructions, not another model invocation. Ask remains the explicit-save
workflow. Create/Organize still require browser review, but their report title
and current brief can evolve while the original brief is retained. Permission-
checked execution receipts identify the resulting records after browser execution.
Compact starter contracts, selected action schemas, scoped inventories and
name-only Page browsing reduce response size without introducing an exact-name
search prerequisite or weakening full submission validation. The current API
reference describes the additional schema-fetch tradeoff and fallback.

## Add a small skill, then trial local MCP

The skill gave an agent a short way into that API: where to connect, how to use
the user's bearer key, which workflow to start, and where to fetch the live
rules. Client-side HTTP scripts helped with mechanics, but schemas and business
rules belonged on the server. The canonical downloadable skill remains a
small Markdown bootstrap; installing it does not install an executable.

The local MCP trial then wrapped the same REST interface in named, typed tools.
It ran on the user's machine over stdio and needed a local package, credentials,
configuration and release/install machinery. This improved tool discovery and
made routine protocol work the adapter's responsibility. It also supplied a
convenient local-file path. The question was whether those benefits justified
maintaining another installable component.

Trials exposed avoidable model work: rediscovering schemas, fetching context in
separate rounds, repeating searches, printing duplicate result representations,
and starting replacement Plans after output confusion. Improvements included
useful context in starter/upload responses, fresh contract checks inside
submission, shorter tool introductions, clearer same-Plan recovery, and ranked
permission-filtered candidate search for external clients.

Other changes addressed meaning rather than transport: clearer scheduling and
reference rules, required Yes/No questions that permit a negative answer, and
duplicate checking based on evidence rather than a ritual search for every
filename. Shared domain rules were kept separate from entry-specific
instructions: built-in AI still has server-managed planning and form-completion
stages, whereas external clients must author the complete proposal themselves.

## Move the adapter to Cloud Run

The remote service reused the adapter behind Streamable HTTP on Cloud Run. OAuth
authorization stayed in the main Lagniappe application. Requests carry both
the service's Google workload identity and the consenting user's token back
to the API. The runtime does not need direct database access, a user's API key,
or a service-account key file.

Remote client testing began with ChatGPT web and then added a separate Codex client grant.
Connections belong to the consenting Lagniappe account, independently of a
browser login session. ChatGPT and Codex can be connected and revoked
separately. This made remote access usable across more client environments
without changing workspace permissions or the browser approval boundary.

File handling was the main practical adjustment. Hosted clients supply
attachment objects; the service retrieves and uploads their bytes through the
existing application pipeline. A terminal cannot give Cloud Run a path on its
laptop. An initial local upload helper proved awkward to discover and install,
so it was removed. The terminal now requests a scoped Storage upload manifest,
sends the selected file with an ordinary HTTP client, and finalizes the exact
batch through MCP. Users need neither this repository nor a local MCP package.

Real use also improved the product around the transport: connection pages
adopted the site's login styling and pending-button feedback, grants became
independent per client, and upload recovery preserved the existing Plan after
an uncertain response. A category editor's partial Undo exposed a shared
mutation-coalescing bug that could save a shallow Page and lose its permission
context. Fixing the authoritative save instance restored the existing
permission behavior; it did not require broader delete privileges.

## Test outcomes, not identical model behavior

Deterministic tests covered contracts, permissions, lifecycle transitions,
upload fencing and cleanup, OAuth, and browser execution/undo. Real model runs
tested whether those pieces produced useful results through actual clients.
The evaluation grew into thirteen reusable cases spanning grounded questions,
schedules, related records, revision, contacts, images, mixed files and source
retention. Natural prompts and fixtures were kept separate from operator
rubrics. Raw exports stayed private; reviewed metrics and findings were tracked.

The [second local round](../testing_ai_workflows/comparisons/mcp-round-2.md)
reduced model tool rounds from 133 to 100 across eleven jobs, while total time
rose slightly. The [targeted third round](../testing_ai_workflows/comparisons/mcp-round-3.md)
confirmed same-Plan recovery and usable negative-answer Forms, with less
discovery overhead. These were useful observations from combined changes and
variable model runs, not isolated performance experiments.

The [remote comparison](../testing_ai_workflows/comparisons/remote-mcp-pilot-20260905.md)
saved a report in all thirteen cases and demonstrated ordinary terminal uploads
without the helper. Across the eleven cases with local MCP baselines, total
task time was about fifteen minutes on each side. Some remote cases were slower
and others faster; client changes, permissions, connector confusion, retries
and model behavior prevent a clean claim that the extra hop improved speed.
The two historical Pi/REST cases were kept outside those timing aggregates.

An accepted report was not treated as proof of complete evidence use. Case 02
still used an old saved-view question and was deferred. Case 08 missed late
text despite uploading the complete file; case 13 produced the requested Task
but omitted the source attachment. The operator accepted 08/13 as broadly useful
results with recorded limitations. No growing set of case-specific instructions
was added to chase perfect determinism. Manual execution feedback was retained
separately from trials that intentionally stopped at proposal review.

## Retain one MCP service and integrate normal setup

The remote result was useful enough to retire stdio serving, local profiles,
the client installer, public wheel distribution and its release bookkeeping.
The retained `mcp/` directory owns the service, adapter, file handling and locked
container dependencies. Its tests live in the normal repository suites; the
runner selects the isolated service environment when required. Tests are not
deployed with the service. The skill/direct REST option remains independent.

The subsequent integration made MCP an ordinary optional installation component.
Setup can disable AI entirely or enable built-in AI while keeping external
API/skill and MCP access disabled. Default models are informational during
setup and editable in Admin. Normal deployment prepares a selected MCP service,
publishes matching application settings, then activates and verifies Cloud Run.
An unchanged service skips rebuilding and creating a new revision. The desired
source fingerprint is recorded as `MCP_VERSION`; actual ready cloud state is
checked separately. Retry, diagnostics, recovery and installer-to-owner handoff
follow the existing setup conventions.

That integration passed focused configuration, provider-fake provisioning,
auth/API, browser, upload and shared-template regression checks, together with
build, template-contract and traceability checks. At the time of this overview,
the earlier remote-service testing had live deployment evidence, but the new managed
installation lifecycle had not yet had a clean installation or real-cloud
upgrade trial. Android/desktop behavior, refresh over time, cold starts and
operating effort likewise need actual use. Those are release acceptance checks,
not outcomes implied by the automated suite or earlier client testing.
