# Reusable AI workflow cases

Small, real user jobs for comparing Lagniappe's skill/API, MCP, on-site and
email flows. Judge useful, grounded results first, then tool rounds and tokens.
Time is recorded but is noisy; a modest increase does not cancel a clear
round/token improvement. This is a case library, not a new harness.

## Layout

```text
testing_ai_workflows/
  README.md
  ROUND_3.md
  latest_results.json          # latest reviewed attempt for each case/arm
  comparisons/                # small, tracked comparison/decision notes
  cases/
    01-ask-known-page/
      PROMPT.md
      RUBRIC.md
      fixtures/
      artifacts/              # local only; never committed or deployed
        baseline/mcp/
        current/mcp/
```

Prompts, inspected fixtures, rubrics, metrics and comparison notes are tracked.
Raw exports stay ignored: they can contain private records or credentials.
The entire library is excluded from App Engine uploads; Cloud Build contexts
also exclude raw artifacts. Do not force-add transcripts or signed URLs.

## Run a case

1. Read its rubric yourself, checking that the required workspace records still
   exist and dates are sensible. Do not paste the rubric into the model chat.
2. Start a fresh client in a **neutral working copy of the case's fixtures**,
   outside the application checkout, with the intended profile/model/reasoning.
   The checkout's ancestor `AGENTS.md` would otherwise add application-coding
   instructions that were absent from the Desktop baselines. For round 3, the
   existing Desktop fixture directories are already suitable and byte-identical.
   Paste the natural request from `PROMPT.md`.
   Case 05 has a second message after the first proposal is ready.
3. Review the answer/proposal in the website. Stop at review unless execution
   is separately intended. Do not clean up active reports during the run.
4. After the task finishes, use the existing export skill to save into this
   library's `cases/<case>/artifacts/current/mcp/`, using its absolute path.
   [Round 3](ROUND_3.md) lists ready-to-copy destinations. Keep the repository
   path out of the task prompt; it is export metadata, not task evidence.
   No new telemetry environment variable or export skill is required.
5. Ask for analysis of current versus baseline. Failed or imperfect attempts
   count; do not overwrite them with a prettier run.

For Pi/REST, native on-site or email, use a different arm directory such as
`current/pi-rest`, `current/native`, or `current/email`. Compare each with its
own baseline. The same semantic job can have different transport/stage rules.
Do not copy MCP lifecycle instructions into native Gemini prompts.

Folders are prepared for the current local round. On a fresh checkout, export
can create the current directory; create it first if your exporter requires it.
Ignored historical captures are not distributed with Git, but their hashes,
measured results, provenance and limitations are retained in the tracked index.

For later runs, use real fixture copies in a neutral directory, not symlinks
that may resolve back into the code checkout. Keep the same working-directory
instruction context on both sides of a comparison and verify input hashes.
The tracked case is the authoritative input; the neutral directory is only its
working copy. A changed directory/instruction context is a recorded control gap.

## Comparison and baseline rollover

`latest_results.json` means the **latest reviewed attempt**, not the latest
success. Keep the case/arm separate: a Pi run must not overwrite an MCP result.

After reviewing a batch:

- Save a concise `comparisons/<run-id>.md` with the selected cases, before/after
  results, intervention/control gaps, and keep/change decision.
- Update only the selected case/arm records in `latest_results.json`. Retain
  failures and mark unknown measurements unknown. Record the prompt/fixture
  hashes associated with the actual run, not merely today's files.
- Once the comparison is saved, move the previous baseline to an ignored
  `artifacts/archive/<old-run-id>/<arm>/` directory, move the reviewed current
  capture into `artifacts/baseline/<arm>/`, and create an empty current folder.
  Do not overwrite an existing archive or discard an unreviewed run.
- Git retains old compact summaries. Local raw archives can be pruned later
  with explicit approval; there is no automatic deletion or production cleanup.

This keeps the normal view at baseline/current without clearing the baseline
before its replacement has been reviewed. A materially revised prompt or
fixture needs a new baseline; record an old run as historical evidence rather
than presenting it as a controlled pair.

## What to record

The JSON index is a small review record, not a pass/fail evaluator. Each run
records its identity/arm, source and hash, known client/model/reasoning/build,
outcome and caveats, and available task-only measurements:

- model tool rounds (one top-level tool call; an `exec` can batch MCP calls);
- discovery rounds, included in that count;
- input, cached input, uncached input, output and reasoning tokens where known;
- prompt-to-final seconds, summed across task turns, excluding between-turn gaps;
- optional reported cost, never a guessed price;
- separate MCP/API counts only if actually observed.

Exclude the export request and export activity. Preserve in-turn waits/retries
in raw time and describe them. Reasoning tokens are a subset of output, not an
additional charge to add again. Native provider output and Pi tool counts keep
their own definitions. The existing exports are enough; an analyst can compute
metrics afterward without another operator logging step.

For Codex, use per-response `token_usage_record` events, task boundaries and
the final answer timestamp. Do not sum cumulative token snapshots or count
literal nested call names as actual request totals when code contains loops.
Interrupted/incomplete tasks remain explicitly incomplete, not zero-cost passes.

## Case selection

| Case | Main stress | Current evidence |
| --- | --- | --- |
| [01 Grounded explanation](cases/01-ask-known-page/PROMPT.md) | Approximate discovery, source grounding, saved answer | MCP round 2 |
| [02 Books/filter](cases/02-ask-books-filter/PROMPT.md) | Complete lists, filter interpretation, clipping, one report | MCP round 2, known lifecycle failure |
| [03 One-time reminder](cases/03-create-personal-task/PROMPT.md) | Personal Page, timezone, no accidental recurrence | MCP round 2 |
| [04 Related records](cases/04-create-related-records/PROMPT.md) | Form/Category/Page/Task references and dates | MCP round 2, rate-limit interruption |
| [05 Revision](cases/05-revise-ready-create-plan/PROMPT.md) | Same report, targeted change, unaffected work retained | MCP round 2, prompt intervention |
| [06 Contact](cases/06-organize-vcard/PROMPT.md) | Full file, grounded fields, reasonable follow-up/mapping | MCP round 2 |
| [07 Screenshot](cases/07-organize-bug-screenshot/PROMPT.md) | Correct existing issue and preserved update content | MCP round 2, local image inspection |
| [08 Mixed files](cases/08-organize-mixed-files/PROMPT.md) | Duplicate service, open work, late evidence, embedded instructions | MCP round 2 |
| [09 Project](cases/09-create-project/PROMPT.md) | Reusable work types and usable negative-answer form | MCP round 2, known checkbox defect |
| [10 Recurring reminder](cases/10-create-recurring-reminder/PROMPT.md) | Three weeks after completion, not calendar repetition | MCP round 2 |
| [11 Approximate issue](cases/11-ask-approximate-issue/PROMPT.md) | Ranked recall, status evidence, persisted answer | MCP round 2 |
| 12 Several documents, one subject | One Page with complete attachments; checklist is not completed work | Historical Pi/REST reference; first MCP baseline needed |
| 13 One task, several subjects | Respect requested task count and retain supporting file | Historical Pi/REST failure; first MCP baseline needed |

Use a small relevant selection, not all thirteen for every edit. A scheduling
change merits 03 + 10; filing changes merit 06/08/12/13; Project/Form changes
merit 09. [Round 3](ROUND_3.md) selects five specific cases. Rubrics name both
expected results and acceptable variance; they do not prescribe a tool sequence.

The operator's living demo workspace is not automatically seeded or reset.
Case rubrics describe prerequisites. Missing/renamed/completed records, prior
proposal execution and accumulated uploads are comparison caveats, not an
invitation for the evaluator to repair production fixtures silently.

The fuller process and entry-point boundaries are in
[TESTING_AI_PROCESS.md](../documentation/TESTING_AI_PROCESS.md).
