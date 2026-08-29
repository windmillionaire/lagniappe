# AI Context and Model Calls

`lagniappe/core/tools/ai/` builds model requests from application-owned policy,
permission-filtered context, files, and optional function declarations. The
provider may choose which available read tools to call; application validation
owns the safety of the final result.

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
through SDK retries, tool turns, and a structured-final call. Separate
Organize stages and later durable attempts are separate generations and may
resolve different saved settings.

Foreground calls use the normal SDK retry profile. Deferred jobs use at most
two SDK attempts so durable job backoff owns longer outages. See
[BACKEND_JOBS.md](BACKEND_JOBS.md).

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

## Structured output

When JSON, tools, and a provider response schema are enabled together, the
initial and tool turns omit the JSON MIME type and response schema so the model
can request functions. After discovery, the application issues a separate
structured-final request over the accumulated transcript. Ask, Create, and
Organize then validate against their application contracts and may run one
repair pass.

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
the contract.

## Files

Initial attachments and tool-returned files use the `FileConsumer` boundary.
Autofill receives readable files directly attached to its target. It prefers
saved summaries, may request extracted text for an unresolved field, and may
request an original file only when text is insufficient. Organize planning
uses saved summaries and bounded retrieval candidates; its final form
completion stage does not reread original files.

## Validation and cleanup

`reporting/contracts/` defines action-specific schemas and ordering.
`reporting/proposals/` normalizes and validates. Narrow deterministic repairs
handle values such as stable field IDs and one unambiguous reference. Unsafe
actions become visible review items; an unusable plan becomes a review-only
proposal rather than executable partial work.

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
