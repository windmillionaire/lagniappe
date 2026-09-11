# Reusable AI workflow cases

Small, real user jobs for comparing Lagniappe's skill/API, MCP, on-site and
email flows. Judge useful, grounded results first, then tool rounds and tokens.
Time is recorded but is noisy; a modest increase does not cancel a clear
round/token improvement. This is a case library, not a new harness.

Latest review: [Remote MCP pilot, September 5](comparisons/remote-mcp-pilot-20260905.md),
all thirteen cases. The operator returned `cases/` from Desktop; each case now
has reviewed current evidence alongside its preserved baseline. Remote is a
practical continuation of the pilot, with broadly comparable total time and
working ordinary local-file uploads. Cases 02/08/13 retain recorded evidence
gaps; the operator deferred 02 and accepted 08/13 as broadly useful pilot results
without requiring further model rules or reruns. See the review for details. No baseline
rollover has been performed. Earlier [MCP round 3](comparisons/mcp-round-3.md)
supplies baselines 01/02/08/09/11; the other local baselines are round 2.

## Layout

```text
testing_ai_workflows/
  README.md
  ROUND_3.md
  latest_results.json          # latest reviewed attempt for each case/arm
  comparisons/                # small, tracked comparison/decision notes
  skills/export-chat/         # existing Codex exporter, including its helper
  cases/
    01-ask-known-page/
      PROMPT.md
      RUBRIC.md
      fixtures/
      artifacts/              # local only; never committed or deployed
        baseline/
        current/
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
   instructions that were absent from the Desktop baselines. The September 5
   remote captures used `/home/swifty/Desktop/cases/<case>/fixtures/`; the
   operator returned those cases to this library after the runs. Prepare a
   neutral copy again for a later trial rather than running inside this repo.
   Paste the natural request from `PROMPT.md`.
   Case 05 has a second message after the first proposal is ready.
   Current MCP prompts include an explicit `mcp:` routing cue (both messages
   in case 05). Keep it in the capture. Case 02 now asks directly for ratings
   4 or 5 and no longer requests a saved-view definition. Its September 5
   capture still used the old question; the revised request awaits a run.
3. Review the answer/proposal in the website. Stop at review unless execution
   is separately intended. Do not clean up active reports during the run.
4. After the task finishes, use the existing export skill to save into this
   library's `cases/<case>/artifacts/current/`, using its absolute path.
   Keep the repository
   path out of the task prompt; it is export metadata, not task evidence.
   No new telemetry environment variable or export skill is required.
5. Ask for analysis of current versus baseline. Failed or imperfect attempts
   count; do not overwrite them with a prettier run.

Each case has one baseline and one current run, with files directly inside
those folders. Record the client/transport in the result index and comparison
notes, without adding arm or run subfolders. The same semantic job can have
different transport/stage rules. Do not copy MCP lifecycle instructions into
native Gemini prompts. Cases 12/13 still have historical Pi/REST baselines;
their first remote MCP run is a cross-client comparison, not local MCP parity.

Current folders contain the reviewed pilot captures. On a fresh checkout, export
can create the current directory; create it first if your exporter requires it.
Ignored historical captures are not distributed with Git, but their hashes,
measured results, provenance and limitations are retained in the tracked index.

For later runs, use real fixture copies in a neutral directory, not symlinks
that may resolve back into the code checkout. Keep the same working-directory
instruction context on both sides of a comparison and verify input hashes.
The tracked case is the authoritative input; the neutral directory is only its
working copy. A changed directory/instruction context is a recorded control gap.

## Export skill

[skills/export-chat/SKILL.md](skills/export-chat/SKILL.md) bundles the existing
local Codex export skill, its Python helper and UI metadata, copied unchanged
on 2026-09-05. It produces `CODEX_ARCHIVE.jsonl` and `CODEX_SESSION.txt`; it does
not add telemetry or change the capture format. The helper uses only Python's
standard library and requires a local Codex transcript, not an API key.

Your installed Export Chat skill still works; no change is needed for the pilot.
The tracked copy is not automatically installed. To use it directly, ask the
agent **after the measured task finishes**:

> Use the export skill at /absolute/path/to/lagniappe/testing_ai_workflows/skills/export-chat/SKILL.md to export this chat to /absolute/path/to/lagniappe/testing_ai_workflows/cases/<case>/artifacts/current.

Keep the session in its neutral fixtures directory and supply the destination
explicitly. The helper otherwise defaults to the working directory and replaces
its two export files. Review and record the first attempt before any retry;
do not silently overwrite it. Do not export private captures into tracked folders.

The readable summary covers the whole captured session. Comparison metrics
still come from the native JSONL with export activity excluded. This is the
Codex exporter; keep using Pi's own archive skill for Pi sessions.

## Comparison and baseline rollover

`latest_results.json` means the **latest reviewed attempt**, not the latest
success. Keep the case/arm separate: a Pi run must not overwrite an MCP result.
The September 5 `codex-remote` arm preserves the local `mcp` and historical
`pi-rest` records. Its per-case transport and route counts distinguish direct
remote MCP from the imported ChatGPT app used in some early captures.

After reviewing a batch:

- Save a concise `comparisons/<run-id>.md` with the selected cases, before/after
  results, intervention/control gaps, and keep/change decision.
- Update only the selected case/arm records in `latest_results.json`. Retain
  failures and mark unknown measurements unknown. Record the prompt/fixture
  hashes associated with the actual run, not merely today's files.
- Once the comparison is saved and rollover is requested, replace the baseline
  with the reviewed current capture, then leave `artifacts/current/` empty.
  Keep exactly these two artifact folders; do not add arm or archive subfolders.
- Git retains old compact summaries. During the September 5 rollover, all
  replaced raw baselines were verified byte-for-byte against their preserved
  Desktop trial originals. Future rollover should establish how to retain or
  discard older raw evidence before replacing the only copy.

This keeps the normal view at baseline/current without clearing the baseline
before its replacement has been reviewed. A materially revised prompt or
fixture needs a new baseline; record an old run as historical evidence rather
than presenting it as a controlled pair.
The remote pilot adds `mcp:` to all prompts and changes case 02's job; the index
records new input hashes while preserving each historical run's original input
snapshot and measurements. Exact prompt equality is therefore false for those
historical captures; the routing cue alone leaves other cases' job text intact.

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
When present, unique completed `McpToolCall` event-item IDs provide actual MCP
call counts, including failed calls inside batches. Count each once within the
measured task turn, separately from model rounds and unknown upstream requests.
Interrupted/incomplete tasks remain explicitly incomplete, not zero-cost passes.

## Case selection

| Case | Main stress | Current evidence |
| --- | --- | --- |
| [01 Grounded explanation](cases/01-ask-known-page/PROMPT.md) | Approximate discovery, source grounding, saved answer | Remote: grounded; saved-report link omitted in final reply |
| [02 Books/filter](cases/02-ask-books-filter/PROMPT.md) | Complete 4/5-rated mystery/thriller list, authors/statuses, clipping, one report | Remote: correct list; old saved-view question/unsupported claim; revised prompt untested |
| [03 One-time reminder](cases/03-create-personal-task/PROMPT.md) | Personal Page, timezone, no accidental recurrence | Remote: correct proposal |
| [04 Related records](cases/04-create-related-records/PROMPT.md) | Form/Category/Page/Task references and dates | Remote: correct proposal through imported app, not direct MCP |
| [05 Revision](cases/05-revise-ready-create-plan/PROMPT.md) | Same report, targeted change, unaffected work retained | Remote: same Plan, correct revision |
| [06 Contact](cases/06-organize-vcard/PROMPT.md) | Full file, grounded fields, reasonable follow-up/mapping | Remote: direct vCard upload, attachment/summary and follow-up |
| [07 Screenshot](cases/07-organize-bug-screenshot/PROMPT.md) | Correct existing issue and preserved update content | Remote: correct target after steering and submission repair |
| [08 Mixed files](cases/08-organize-mixed-files/PROMPT.md) | Duplicate service, open work, late evidence, embedded instructions | Remote: all uploads recovered; unread log tail loses final Page name |
| [09 Project](cases/09-create-project/PROMPT.md) | Reusable work types and usable negative-answer form | Remote: Yes/No correction retained; app detour |
| [10 Recurring reminder](cases/10-create-recurring-reminder/PROMPT.md) | Three weeks after completion, not calendar repetition | Remote: correct completion-relative proposal; app detour |
| [11 Approximate issue](cases/11-ask-approximate-issue/PROMPT.md) | Ranked recall, status evidence, persisted answer | Remote: correct after steering/interruption |
| [12 Several documents, one subject](cases/12-create-page-from-documents/PROMPT.md) | One Page with complete attachments; checklist is not completed work | Remote: one Page, all three sources; historical Pi baseline only |
| [13 One task, several subjects](cases/13-create-one-task-from-note/PROMPT.md) | Respect requested task count and retain supporting file | Remote: one correct Task; source note still omitted; historical Pi baseline only |

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
