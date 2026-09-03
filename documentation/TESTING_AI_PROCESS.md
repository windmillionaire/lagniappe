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

The deployed build should be the only intended changed variable. If the
workspace cannot be reset exactly, use unique fixture names, record the drift,
and distinguish it from the product result. Do not coach or repair a run unless
the prompt explicitly calls for that interaction.

## Evaluation folders

Keep the working evidence outside the repository unless it is intended to be a
durable fixture. A paired run should use parallel trees:

```text
evaluation-name-before/
  README.md
  RUN_RECORD.md
  01-case-name/
    PROMPT.md
    RESULTS.md
    SESSION.txt
    transcript.jsonl
    transcript.html
    artifacts/

evaluation-name-after/
  README.md
  RUN_RECORD.md
  COMPARISON.md
  01-case-name/
    ...
```

Create both trees from the same source before the baseline. Do not edit the
after prompts in response to baseline behavior.

### Required evidence

| Artifact | Purpose |
| --- | --- |
| `PROMPT.md` | Exact input and case-specific checks. |
| `transcript.jsonl` | Machine-readable event, timing, usage, and tool-call record. |
| `transcript.html` | Convenient human audit of the same session. |
| `SESSION.txt` | Session ID, client/model/provider settings, tokens, and reported cost. |
| `RESULTS.md` | Scored checks, IDs, raw failures, outcome, and control deviations. |
| `RUN_RECORD.md` | Phase-wide environment and one summary row per case. |
| `COMPARISON.md` | Aggregate before/after findings, caveats, and decision. |
| `artifacts/` | Relevant contracts, request bodies, receipts, GET projections, and response bodies. |

Record the exact deployed application version or build, not only its release
number. Preserve request IDs for errors and Plan/report identifiers for later
diagnosis. Temporary upload-session URLs are not useful durable evidence; keep
the finalized file references and responses instead.

## Mechanical run sequence

1. Add deterministic regression coverage for every server behavior that can be
   asserted without a model.
2. Seed or verify the starting workspace and record a manifest of the relevant
   entities, permissions, and fixture hashes.
3. Create identical before and after folders, prompts, and blank result sheets.
4. Run every baseline case in a fresh session without intervention.
5. Export both transcript formats and session details immediately. Preserve
   response bodies that the transcript alone would make awkward to compare.
6. Score the run as it happened. Record model mistakes and invalid controls;
   do not rerun merely to obtain a prettier baseline.
7. Delete only test-owned reports and uploads through the ordinary product
   path once their evidence is exported. Preserve workspace fixtures needed by
   both phases.
8. Deploy once, record the exact build, and verify the intended version is
   serving.
9. Run the unchanged after cases, again in fresh sessions, and capture the same
   evidence.
10. Compare semantic outcomes first, then reliability and efficiency. File any
    newly discovered issue separately from the change being evaluated.

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
- client tool calls and API HTTP requests separately;
- timeouts, retries, and corrective validation cycles;
- contract and guideline response sizes where relevant;
- total, cached, uncached, and output tokens when available; and
- reported model cost.

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

- copy and hash prompts and fixtures into both phases;
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
