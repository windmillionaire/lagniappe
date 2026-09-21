# AI Context and Model Calls

`lagniappe/core/tools/ai/` builds model requests from application-owned policy,
permission-filtered context, files, and optional function declarations. The
provider may choose which available read tools to call; application validation
owns the safety of the final result.

## Import boundaries

The `tools.ai` package exposes only the explicit `initialize()` startup entry
point. That call loads `core.ai_model` and initializes the same shared provider
client used by generation modules. Importing the package itself does not load
generation, report, upload, or provider-client workflows.

Import feature operations from their owning modules: `autofill`, `dates`,
`images`, `text`, `category`, `project`, `schema`, and `summarize` own their
respective prompts and generation. `planner` owns report generation;
`reporting/completion/files.py` owns input summaries, `reporting/uploads.py`
owns upload manifests, `reporting/proposals/selection.py` owns action selection,
and `reporting/execution/{ledger,runner}.py` own execution state and execution.
Use module-qualified calls when a shared operation needs a replaceable test
boundary, and patch that owner in tests. These operations are no longer
re-exported from `tools.ai`.

Shared policy and contract modules can now be imported without entering those
workflows. This does not make every AI submodule independent: generation still
loads its declared tool registry and entity dependencies, and Python still
initializes the parent `lagniappe` configuration package. Preserve deliberate
lazy imports and the single `core.ai_model` instance.

## Prompt contract

`Prompt` contains more than the string returned by `build()`:

- system instruction;
- context and instruction blocks;
- output format and optional response schema;
- examples;
- inline bytes and provider-hosted files;
- Google Search and function declarations;
- primary/utility model choice, thinking budget, and service tier;
- tool-round and per-turn file limits; and
- stable-instructions-before-context ordering.

`preview()` shows the system instruction and rendered prompt text. It does not
show provider configuration, function schemas, response schema, file parts,
future tool calls/results, or the structured-final request. The UI calls it
**Initial Prompt** for that reason. On direct-upload forms, preparing a preview
may upload or reuse selected files before rendering the prompt.

## Model selection

`GenAI` reads the live `site/ai` settings at the start of a top-level
generation and falls back to deployed configuration. It pins the chosen model
through SDK retries, tool turns, and a structured-final call. File summary
prepasses and later durable attempts are separate generations and may
resolve different saved settings.

Report planning owns an asynchronous client and event loop for each generation,
uses no SDK retries, and permits one durable transient retry of the current request.
Retrieval stops at 16 rounds or three minutes remaining in the bounded attempt.

Foreground calls use the normal SDK retry profile. Other deferred jobs use at most
two SDK attempts so durable job backoff owns longer outages. See
[BACKEND_JOBS.md](BACKEND_JOBS.md).

`provider_policy.py` owns shared retry options, provider error details/messages,
and quota/transient classification. `GenAI` and `ProviderSession` use that
policy directly. The session manages request lifecycle and uses execution
control's deadline and durable retry budget. Existing helper imports from
`core.py` remain available as aliases.

## Function-tool loop

Workflows explicitly select the declarations available to Gemini. When the
model returns function calls, the application:

1. normalizes reference arguments;
2. executes each handler in deterministic order;
3. enforces the requesting User's permissions in the handler;
4. caches the exact `(tool, normalized arguments)` result for this generation;
5. appends calls, responses, and allowed file parts to the transcript; and
6. sends the growing transcript back to Gemini.

Gemini can request several independent functions in one turn. The dispatcher
executes that list serially to keep Flask/entity context and failure order
deterministic.

Function tools are retrieval only. Application mutation is performed by
validated Autofill handlers or the reviewed report executor after the model
conversation has ended.

The external-agent REST API publishes ordinary JSON Schema definitions for
this same registry and invokes the same handlers as the bearer key's user. It
does not maintain a separate privileged data-access path.

Every catalog definition includes a provider-neutral input schema, output
schema, and result-path descriptor. Provider-native calls receive the successful
direct handler value; REST preserves its `{result: ...}` success envelope. External
catalog selection can return exact definitions or names only, but it never
creates a second handler registry.

On-site and external `search_entities` share the same tool description and
select bounded candidate discovery through registered tool dispatch:
sparse multiword queries may receive ranked OR matches in the same tool result,
with cached parent/snippet and Task completion context. This does not load every
candidate again to attach edit/create permissions. Explicit `exact_name` and
Category `parent_id` scopes remain available. There is no automatic report
retrieval prepass; the planner requests the discovery it needs.

## Structured output

When JSON, tools, and a provider response schema are enabled together, the
initial and tool turns omit the JSON MIME type and response schema so the model
can request functions. After discovery, the application issues a separate
structured-final request over the accumulated transcript. The unified report
planner validates the complete candidate and returns errors to this same
conversation for up to two corrections.

Autofill does not attach a provider response schema. Its keys are dynamic form
field IDs; the prompt names the exact expected fields and normal form validation
removes unknown keys and normalizes values. If `get_file` is available, the
terminal JSON from the tool conversation is accepted directly.

## Context growth

Tool results and file parts remain in subsequent transcript turns. Exact-call
caching avoids repeated handler work but does not remove the returned content
from later requests. Keep handlers bounded by count and projection depth.

Large-result risks include complete workspace inventories, Pages with all
Tasks/Files, rich entity projections, and full extracted text. When adding a
tool, declare:

- its permission check;
- result limit and ordering;
- whether it can return file parts;
- the projection fields the workflow actually needs; and
- how a caller obtains more detail without loading the entire domain.

`get_guidelines` defers specialized form, schema, page, project, scheduling,
image, and output policy until relevant. Treat its result as model guidance,
not proof that a required rule was followed; the application validator remains
the contract. External plan contracts publish required/conditional bundle
arguments. The guideline tool can restrict Form value rules to actual schema
field types and action rules to selected action types; filtered and full calls
remain different arguments in the normal exact-call cache.

For an existing-submission patch, the same tool accepts `task="form_autofill"`
with `actions=["update_task"]` or `["update_page"]` and actual `field_types`; this returns
patch-specific guidance in both native and external flows, without the blank-only
Autofill/file-reading workflow. `get_schema(include_values=true)` joins current
AI-readable values to exact schema ids in one read. Neither option adds a tool
name or a required model round. Shared submission projections also preserve
Table rows with exact column IDs, Todo `items` envelopes, numeric zero, and JSON
booleans in entity, task-list, and history reads. Human field labels remain the
outer keys in entity projections; use `get_schema` for exact outer field IDs.
These are actor-aware projections, not raw storage exports.

`get_task_history(include_original=true)` adds the completed Task's original
answers keyed by field ID, its recorded schema and generation. It requires edit
access, matching the website's Original answers view. Ordinary history reads
retain their existing view permission. Open Tasks return `original_completion:
null`; an unavailable historical schema is explicit and omits unsafe raw values.
The option is shared by native reports and external clients.

Prefer projections and reuse over splitting one
natural read into several dependent calls: each extra Gemini round sends another
provider request and replays prior tool output. Tool count alone is not the useful
measure; observe rounds, cumulative tokens, latency and provider errors.

`get_guidelines(task="report_actions", actions=[...])` shares general proposal
rules and the selected action schemas across built-in Gemini and external
clients. `get_guidelines(task="filing")` supplies specialized organization rules
only when filing uploads or reorganizing existing workspace files. Evidence-only
questions do not need it. The initial report prompt never embeds the full filing
bundle; upload classification instructions appear only when input files exist.
Without uploads, native prompts and external contracts explicitly require
`file_usage=[]`, even when the request concerns existing workspace files.

The current contract selects the allowed actions and file responsibilities.
Native jobs prepare summaries/retrieval terms
before generation; external clients author `summarize_file` actions when their
contract allows them. Both author final form values and requested task/document
updates themselves. Native validation feeds precise errors back into the same
conversation with its tool results/cache intact, for at most two corrections.
It does not rewrite a valid proposal in a separate structured-final model call.
The response schema remains visible in the conversation while local validation
enforces executable shapes. MCP lifecycle names and REST submission instructions
do not belong in built-in provider prompts. The external schedule schema adds
conditional requirements without changing Gemini's provider-compatible schema.
The external `form_autofill` bundle permits grounded corrections and emits only
selected field updates; built-in Autofill retains its blank-only completion
policy and preserves non-empty partial values.

Summary-writing policy comes with the selected `summarize_file` action or the
`file_summary` bundle, not with general filing guidance. The native planner
reuses server-prepared summaries. General proposal completeness, target reuse,
and final-value requirements belong to `report_actions`, so requests without
files receive them without loading filing policy. Answer-only provider access
omits the planner's mutation and filing instructions.

`get_category_pages` returns at most ten Pages per call. Its response separates
the caller's `requested_limit`, the enforced `effective_limit`, and
`returned_count`; `page_count` remains as a compatibility alias for the returned
count. When `has_more` is true, pass the opaque `next_cursor` back with the same
Category/Form filter rather than treating the first page as a complete count.
The declared range is one through ten; the handler clamps older out-of-range
integer calls and exposes that choice through `effective_limit`.

## Files

Initial attachments and tool-returned files use the `FileConsumer` boundary.
Autofill receives readable files directly attached to its target. It prefers
saved summaries, may request extracted text for an unresolved field, and may
request an original file only when text is insufficient. The report planner starts
from saved summaries and file metadata, then reads further evidence
as needed in the same conversation that authors the complete proposal.

## Validation and cleanup

`reporting/contracts/` defines action-specific schemas and ordering.
`reporting/proposals/` normalizes and validates. Narrow deterministic repairs
handle values such as stable field IDs and one unambiguous reference. Native
report planning returns remaining errors to the same conversation for bounded
correction; exhausted correction fails generation. No separate report repair
or form-completion model call remains.

`GenAI.cleanup()` removes citation-shaped numeric markers while preserving
ordinary bracketed text. Add only exact provider syntax to cleanup rules.

## Observability

When `AI_OBSERVABILITY` is enabled, every text generation writes a bounded
summary keyed by an opaque correlation ID. Allowed fields include prompt
contract identity, model/location/tier, call and token counts, tool names and
counts, cache/file/result sizes, validation outcome, duration, and deferred job
type/attempt.

The summary excludes prompts, model text, tool arguments/results, files,
errors, and User/entity/report/job identifiers. Persistence is best effort and
cannot change the generation result. Owner analytics queries at most the latest
1,000 summaries for the selected period; activity-driven retention removes
records older than 30 days in bounded batches.

Use actual provider usage for production measurement. Token-count preflight is
appropriate for diagnostics, evaluation budgets, or requests known to be
large—not as an unconditional extra provider call.

## Evaluation

Evaluate changes by workflow and stage. Track queue time, provider calls, tool
rounds, token classes, tool-result size, structured-final frequency, repair and
fallback rates, retry class, stage resume, target drift, and terminal browser
reconciliation. An optimization must preserve permission filtering,
application validation, deterministic apply, and privacy-bounded telemetry.

Provider behavior changes independently of this repository. Recheck the
official Gemini function-calling, token-counting, context-caching, and service
tier documentation before changing provider-specific behavior.

The unified planner starts with a compact envelope and a permission-bounded
catalog of actions. `get_guidelines(task="report_actions", actions=[...])`
requires a nonempty selection and returns exact selected schemas as well as
rules. No router or full action-schema union is included in the initial prompt.
The output's file_usage classifies each upload as evidence or organize; only
the latter creates filing obligations. See [AI_WORKFLOWS.md](AI_WORKFLOWS.md).

The model-facing permission context contains `allowed_actions` and action rules,
without a second capability map. The action catalog derives its choices from
internal create/update/delete hints; attachments, document appends, moves,
renames, and submission changes use the ordinary edit permission model. These
hints are computed on demand and are not stored in the Flask session. They do
not grant access to an individual record: discovery, proposal preparation, and
execution check the exact targets, including both sides of a move. Page editing
also supplies the Task editing hint, matching Task permission inheritance.
