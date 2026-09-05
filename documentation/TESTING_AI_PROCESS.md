# AI Workflow Evaluation Process

This guide covers model-in-the-loop evaluation of Lagniappe's Ask, Create, and
Organize workflows. Use it when a change can affect model behavior, external
tool use, proposal quality, or the equivalence of the external API, on-site,
and email entry points.

These evaluations complement deterministic unit and E2E tests. They answer a
different question: can a real client and model reach a correct, reviewable
result through the deployed product, and how much avoidable work does that
take?

## Evaluation priorities

Score the user-visible result first:

1. Was the result correct, grounded in the available evidence, and complete?
2. Did it preserve the review and execution boundary?
3. Could the result be revised or resumed through public contracts?
4. Did the client use the protocol reliably and without avoidable work?

Reading an extra file or making an unnecessary read call is secondary when the
user still receives a clean result. It becomes important when it changes the
answer, defeats the intended test control, causes repeated failures, exposes
unrelated state, or materially increases latency and cost.

With equivalent useful outcomes, prioritize fewer model/tool rounds and fewer
tokens. Wall time is a noisy secondary observation; a modest time increase in
one run does not negate a clear reduction in rounds and tokens.

## Choose the smallest faithful layer

| Layer | Use it for |
| --- | --- |
| Unit or ordinary E2E | Deterministic schemas, validation, permissions, serialization, proposal normalization, execution, and cleanup. |
| Recorded live case | Model interpretation, tool selection, multi-step recovery, evidence use, and provider/client behavior. |
| Paired before/after evaluation | A deploy whose effect on correctness or interaction cost cannot be established from deterministic tests alone. |
| Three-entry-point parity | A shared workflow or proposal change that must behave equivalently through external API, on-site, and email starts. |

Do not make a live provider run prove mechanics that a deterministic test can
prove more cheaply and precisely. Keep a small live case to prove that the
pieces compose in practice.

## Design the cases

Use three or four narrow cases for an ordinary release evaluation. Each case
should have one main hypothesis and enough complications to reveal realistic
failure modes without becoming a general product tour.

Define before running it:

- the exact prompt and fixtures;
- the required starting workspace records and permissions;
- user-facing correctness checks;
- protocol checks, including any deliberate invalid request;
- prohibited actions, especially execution;
- expected report-only state and cleanup;
- measurements to record; and
- conditions that would make the test control inconclusive.

Separate outcome checks from protocol-fidelity checks. A model that reads late
fixtures too early may still produce an excellent proposal, but that run does
not prove that a finalized upload inventory overrides stale instructions. Mark
that as a control gap rather than rewriting history or silently rerunning it.

### Keep the pair controlled

For a before/after comparison, keep these constant:

- prompt and fixture bytes;
- workspace seed or captured starting-state manifest;
- user, permissions, base URL, and relevant feature settings;
- client, client version, model, provider, and model settings;
- external skill or instruction source and its content hash; and
- one fresh model session per case.

The server/client changes under evaluation should be the only intended changed
variables; record both when an MCP release accompanies a server deployment. If the
workspace cannot be reset exactly, use unique fixture names, record the drift,
and distinguish it from the product result. Do not coach or repair a run unless
the prompt explicitly calls for that interaction.

## Evaluation folders

The tracked reusable library is
[`testing_ai_workflows/`](../testing_ai_workflows/README.md). Keep one shared
prompt/fixture set per case, a concise rubric, and local-only raw captures:

```text
testing_ai_workflows/
  latest_results.json
  comparisons/
  cases/
    01-case-name/
      PROMPT.md
      RUBRIC.md
      fixtures/
      artifacts/              # ignored, not deployed
        baseline/
        current/
```

Track inspected/synthetic fixtures and reviewed result summaries, not raw chats,
credentials, signed URLs or private screenshots. Preserve previous exports and
keep prompts/fixtures unchanged between paired runs. The initial library copies
the existing Desktop inputs/captures without moving or deleting their originals.
Historical cases with a revised natural prompt are reference evidence until
they get a current matching baseline.

The library also tracks the existing Codex
[Export Chat skill and helper](../testing_ai_workflows/skills/export-chat/SKILL.md).
It preserves the native JSONL/session-summary format; existing installations
need no update. Load it only for the post-task export, not as part of the measured
request. Pi sessions continue to use their own archive skill.

Keep exactly one baseline and one current run per case, with files directly
inside those folders. Identify MCP, Pi/REST, native and email arms in the result
index and comparison notes. After comparison and requested rollover, update the
selected case/arm summaries (including failures), establish retention or disposal
of the older evidence, and replace the baseline with the reviewed current run.
Leave current empty for the next run; do not add arm or archive subfolders.
Never silently replace an unreviewed failure with a retry or require ignored
local transcripts to exist in a fresh checkout/CI.

Give the model only the natural request from `PROMPT.md`, not the rubric or
change-observation notes. Launch in a neutral working copy of `fixtures/`
outside the application checkout: repository `AGENTS.md` would introduce coding
instructions and a comparison confound. The existing Desktop fixture directories
are retained for round 3; export back to the tracked library only after the
task finishes. Use real copies rather than symlinks resolving into the checkout.
The remote MCP pilot prefixes requests with `mcp:` to make transport selection
explicit. Preserve that cue in the transcript and comparison controls; omit it
for non-MCP arms and record the difference. Case 02 now specifies ratings 4 or
5 directly instead of asking about a saved view unavailable through the MCP.
Targeted notes should name a hoped-for improvement,
a plausible regression, and an inconclusive/control-limited outcome. When
several changes ship together, these observations help attribute results but
do not establish single-change causality.

### Required evidence

| Artifact | Purpose |
| --- | --- |
| `PROMPT.md` | Exact natural user input; no scoring or prescribed tool sequence. |
| `RUBRIC.md` | Operator-only outcome checks, prerequisites and focused change observations. |
| Native JSONL export | Machine-readable event, timing, usage, and tool-call record; keep the existing export skill's filename. |
| Existing readable export/session summary | Convenient human audit/settings/cost where the client already supplies them; no new export format requirement. |
| `latest_results.json` | Latest reviewed attempt per case/arm, input/archive hashes, known settings/build, metrics, outcome and control deviations. |
| `comparisons/<run-id>.md` | Selected before/after findings, caveats and decision. |
| Local `artifacts/` | Native exports and any screenshots/receipts needed beyond their contents. |

Record the exact deployed application version or build, not only its release
number. Preserve request IDs for errors and Plan/report identifiers for later
diagnosis. Temporary upload-session URLs are not useful durable evidence; keep
the finalized file references and responses instead.

## Mechanical run sequence

1. Add deterministic regression coverage for every server behavior that can be
   asserted without a model.
2. Verify the rubric's starting workspace facts and record relevant drift.
   Seed or reset only when separately authorized; a mandatory reset rig is not
   required for practical comparisons.
3. Keep one shared prompt/fixture set; prepare current artifact folders. Reuse
   a preserved baseline where inputs and relevant state still match.
4. Run any missing baseline in a fresh session without intervention.
5. Use the existing client export skill immediately. Preserve
   response bodies that the transcript alone would make awkward to compare.
6. Score the run as it happened. Record model mistakes and invalid controls;
   do not rerun merely to obtain a prettier baseline.
7. If cleanup is requested, delete only exact test-owned reports/uploads through
   the ordinary product path after export. Never clean up active reports during
   a run. Preserve workspace fixtures needed by both phases.
8. Deploy once, record the exact build, and verify the intended version is
   serving.
9. Run the unchanged after cases, again in fresh sessions, and capture the same
   evidence.
10. Compare semantic outcomes first, then reliability and efficiency. File any
    newly discovered issue separately from the change being evaluated.
11. Save the comparison and promote reviewed captures using the library's
    baseline/current rollover; leave unselected case/arm results untouched.

Do not execute Create or Organize proposals unless execution is the behavior
under test. A successful `ready` receipt is not a workspace mutation. Ask may
save a completed read-only report, while Create and Organize leave reviewable
reports and may leave report-owned uploads.

Deleting a test report should delete its otherwise unattached report-only
Files. A File already attached somewhere else must survive. After cleanup,
verify that test-only uploads are no longer discoverable when file discovery is
relevant to later cases.

## Score each case

Use four separate dimensions:

### Outcome correctness

- exact destinations, entity types, and permissions;
- complete evidence inspection and grounded summaries;
- correct duplicate grouping and completion state;
- meaningful negative answers in authored Forms: a required Yes/No question
  must accept No, whereas a required checkbox is a mandatory affirmation;
- no invented dates or claims unsupported by content;
- all required files attached and summarized; and
- correct public review state, with no claim that ready actions were executed.

### Contract and lifecycle correctness

- documented result paths and error envelopes worked;
- validation errors were safe and addressable;
- public references remained public and round-trippable;
- the compact receipt was treated as authoritative;
- proposal revision preserved action semantics; and
- no unapproved execution occurred.

### Protocol fidelity

- the intended discovery path and staged-input sequence were actually tested;
- deliberate invalid calls are distinguished from accidental corrections;
- duplicate or unnecessary calls are identified; and
- the client respected tool, upload, and submission limits.

### Reliability and efficiency

Record at least:

- prompt-to-final duration;
- model tool rounds, individual MCP calls and API HTTP requests separately;
- timeouts, retries, and corrective validation cycles;
- contract and guideline response sizes where relevant;
- total, cached, uncached, and output tokens when available; and
- reported model cost when available, otherwise unknown.

Exclude export activity. For multi-turn jobs, sum task-turn durations and keep
between-turn gaps separate; retain in-turn waits/retries in the raw time. One
Codex `exec` can perform several MCP calls, and adapter context bundling moves
some reads inside that operation. Do not infer fewer HTTP requests from fewer
model rounds. Sum per-response usage, not repeated cumulative snapshots;
uncached input is input minus cached, and reasoning is a subset of output.

Define a retry as a repeated intent following an error, bad request shape, or
result-parsing mistake. Do not count a deliberate invalid submission as a
retry. Describe local/client, provider, and server failures separately.

Use one of these outcome labels:

- **Passed**: the user-facing result and the intended control both passed.
- **Passed with control gap**: the result passed, but the run did not isolate
  one intended behavior.
- **Failed**: a required user-facing or contract outcome failed.

## Compare and interpret

Compare actions and evidence use, not superficial prose. Normalize volatile
Plan IDs, public hashes, action IDs, timestamps, and equivalent ordering before
machine comparison.

A single run on each build is regression evidence, not a latency benchmark.
Report time, tokens, and cost descriptively; do not attribute small differences
to the deployment when provider and model variance could explain them. Repeated
runs are warranted only when performance itself is the release decision.

When a failure is ambiguous, use its request ID and session time to inspect
bounded server logs. Attribute the problem to the narrowest demonstrated
layer: application/API, client integration, provider transport, model choice,
or test control.

The comparison should state:

- which original regressions were reproduced and fixed;
- whether semantic quality improved, regressed, or stayed equivalent;
- meaningful changes in calls, latency, tokens, and cost;
- provider/client mistakes that the API successfully bounded;
- contamination or other control limitations;
- new actionable findings; and
- what was not tested.

## Three-entry-point parity

The external API may use more reads, corrections, and conversational revision
than the deferred on-site or email workflow. That is useful, not a parity
failure. The invariant is the reviewable result and deterministic application
boundary.

For a shared workflow change, compare the three starts on:

- selected existing destinations and Forms;
- normalized action types and substantive field values;
- completion state, dates, and evidence provenance;
- file-to-target assignments and summaries;
- validation and permission outcomes;
- public `ready` or `complete` state; and
- the same browser approval and deterministic execution behavior.

Exercise each entry-specific transport at least once when it changed. Shared
unit tests should cover normalization, validation, persistence, execution, and
cleanup beneath all three entry points. Record an external-only paired run as
such; it does not by itself establish live email/on-site behavioral parity.

## Automation boundary

The evidence format is intentionally amenable to a small capture/comparison
tool, but judgment should remain visible.

Good automation candidates:

- hash the shared prompts/fixtures and associate those bytes with each run;
- validate the run manifest and deployment identifiers;
- export session metadata and transcripts;
- calculate duration, tool calls, token use, cost, and aggregate deltas;
- extract HTTP statuses, request IDs, validation paths, and response sizes;
- compare JSON after removing declared volatile fields;
- verify that only an allowed field changed during a round-trip; and
- generate blank per-case and aggregate result tables.

Keep these manual:

- semantic quality and evidence grounding;
- duplicate and completion judgments;
- whether the final language matches visible state;
- whether extra calls were harmless, useful exploration, or a product problem;
- whether a protocol deviation invalidated the intended control; and
- causal attribution when live model/provider behavior is involved.
