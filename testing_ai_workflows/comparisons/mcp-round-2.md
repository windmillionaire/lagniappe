# MCP round 2 — imported comparison and next baseline

Reviewed September 4, 2026 locally (runs September 5 UTC). Eleven practical MCP
pairs, Codex 0.153.2, gpt-5.6-sol, medium. Candidate installation record: MCP
0.1.5; all round-2 Plan-start request logs name server `20260904t190016`.
Exact running wheel hashes are not independently embedded in the exports.

**Decision: keep the efficiency changes.** Fewer rounds and tokens with useful
results are a win; the variable summed time is not a rollback criterion.
Correct the specific lifecycle/form defects and target discovery next.

| Task-only metric | Previous MCP | Round 2 | Change |
| --- | ---: | ---: | ---: |
| Model tool rounds | 133 | 100 | −24.8% |
| Discovery rounds, included above | 40 | 38 | −5.0% |
| Summed task seconds | 935.030 | 995.658 | +6.5% |
| Input tokens, including cached | 5,314,163 | 3,848,025 | −27.6% |
| Cached input | 4,848,384 | 3,406,848 | −29.7% |
| Uncached input | 465,779 | 441,177 | −5.3% |
| Output, including reasoning | 33,144 | 27,261 | −17.7% |

These are cumulative task-turn measurements, not a context-window size or HTTP
count. Exclude Export Chat; sum per-response usage. Reasoning is included in
output. Time includes in-turn retries and waits, but excludes between-turn
idle gaps. No monetary cost is inferred. Each pair is one model sample on a
living workspace with combined changes; attribution is directional.

## Per-case latest results

| Case | Rounds before → after | Seconds before → after | Round-2 outcome / qualification |
| --- | ---: | ---: | --- |
| 01 | 14 → 8 | 98.550 → 87.349 | Correct explanation, target first in one query, saved Ask; four discovery rounds |
| 02 | 10 → 14 | 70.239 → 127.550 | Correct eight-book list, but two unnecessary drafts; unobserved saved-view definition asserted |
| 03 | 9 → 3 | 47.959 → 24.079 | Correct one-time personal reminder; invalid schedule repair gone |
| 04 | 10 → 12 | 74.581 → 140.790 | Correct linked records and task; three 429 starts/waits inflate measurement |
| 05 | 11 → 5 | 97.089 → 47.825 | Same-Plan due-date revision, unrelated work retained; initial prompt needed “in lagniappe” steering |
| 06 | 14 → 10 | 98.163 → 92.209 | Contact evidence, file and follow-up preserved; WORK address in prose rather than Home Address field |
| 07 | 18 → 15 | 108.004 → 116.494 | Correct existing issue, steps preserved and screenshot attached; exact/search detours remain |
| 08 | 17 → 13 | 145.791 → 201.085 | All five complete files understood; more retrievals in fewer batches; generic open gasket Task |
| 09 | 9 → 7 | 67.711 → 55.310 | Correct Project graph, but required “Needs attention” checkbox blocks a future negative-answer completion |
| 10 | 14 → 3 | 80.886 → 27.867 | Correct initial date and three-week after-completion recurrence |
| 11 | 7 → 10 | 46.057 → 75.100 | Eleven searches → one; now saves Ask, but six discovery rounds make total longer |

All eleven round-2 runs submit an answer or ready proposal. This is not proof
that Create/Organize actions were executed; no live execution is part of this
comparison. Nine practical outcomes are satisfactory, with the qualifications
above. Cases 02 and 09 need correction.

The [latest-results index](../latest_results.json) retains each run's tokens,
archive hash, known environment, outcome and caveats. Local raw baseline
captures were copied from the Desktop trial without changing their bytes.

## Evidence behind the targeted corrections

### Discovery and context

No round-2 case separately calls `get_plan_contract`; ten baseline cases do.
This and corrected scheduling/reference advice are the clearest improvements.
All 24 tools remain. Full-file inspection is preserved, including the 22,023
character decision log and ignored malicious footer in case 08.

Discovery barely improves, 40 → 38 rounds, and every first broad `ALL_TOOLS`
dump clips. Those dumps contain unrelated tools too. In case 01, short
180-character descriptions expose the same host-prepended server introduction
for every Lagniappe tool rather than their purpose. Shortening the global
introduction/localizing rules is an evidence-backed next experiment, not a
claim all discovery is removable.

### Case 02: do not lose the active Plan

Five Plans were started. Matching website DELETE requests explain genuine
full-ID 404s for the first two; the logs do not establish deletion actor/intent.
The third Plan's filter succeeds with eight rows and `truncated: false`.
Printing both MCP representations clips host output. A fourth Plan is started
only to repeat/compact the query; a fifth only to submit the assembled answer.
The latter two unnecessary starts leave the visible draft duplicates.

Both arms return the correct eight books (six 5/5, two 4/5, all Finished) but
neither reads the saved-view definition. Explain the filter actually applied
without attributing an unobserved persisted definition; no new saved-view
tool is required. Keep complete rows/counts/partial errors during recovery.

### Case 08: evidence checks are not a filename-search checklist

Both runs group the one completed BHH-26904 service correctly, separate open
gasket work, honor the final Willow Court Rain Garden/planning decision and
avoid treating conditional funding as paid/completed work. All files are
inspected, summarized and attached. Round 2 adds service-identifier and five
filename searches, so fewer model rounds do not mean fewer MCP retrievals.
The generic gasket Task loses some baseline work-type/Form structure; this is
a reviewable tradeoff, not source-data loss. Case 06's WORK/Home address mapping
is a separate ambiguity and should not be forced merely to fill more fields.

### Case 09: acceptance is not downstream usability

Round 2's task Form contains `Needs attention`, `type: checkbox`,
`required: true`. Current Task completion treats a false required checkbox as
incomplete, so a normal no-attention check cannot complete without a false
affirmation. A required Yes/No choice (or appropriate optional checkbox) allows
negative answers. Required acknowledgements remain legitimate. This was
verified against submitted schema/current source, not by executing a live Plan.

### Case 11: correct retrieval and saved answer, not a clean speed comparison

The approximate query returns the correct completed issue first, then details
support the answer. The baseline used eleven searches but never submitted;
round 2 submits correctly. Six discovery rounds, including unrelated-tool
exploration, offset the search gain. Measure through the saved answer, not just
the search; the baseline did less required work.

## Controls and coverage gaps

- Case 02's early deletions and case 04's 429s remain in raw metrics. Excluding
  both gives 113 → 74 rounds and 790.210 → 727.318 seconds, but also removes a
  real lifecycle failure, so it is only a sensitivity check.
- The 10 → 100 starts/hour patch was authorized during the batch but stayed
  local: no observed server-build transition affected these runs.
- Case 05 includes its requested revision; the initial round-2 message omitted
  “in Lagniappe” and received an in-turn correction. All other prompts match
  after whitespace normalization. Canonical case-05 prompt retains the phrase.
- Case 07 inspected the local PNG in both arms; finalized MCP original-image
  delivery was not exercised. Neither late-file test withheld inputs in stages.
- Required-checkbox completion and future recurrence were not exercised live;
  targeted deterministic tests supplement proposal inspection.
- No live on-site/email parity conclusion follows from these external runs.
- Two screenshots belong to the preceding case: case 06's `194631` image is
  case 05; case 08's `195239` image is case 07. Their correctly attributed
  companion screenshots are `195133` and `195625`. Original exports stay intact.

## Additional historical cases retained

These Pi/REST runs use moonshotai/kimi-k3 through OpenRouter, high thinking,
server `20260903t114028`. They are not current MCP baselines; the canonical
prompts remove old absolute paths, and case 13 now explicitly names Lagniappe.

| Canonical case | Historical outcome | Pi tool calls | Seconds | Input / cached / output tokens |
| --- | --- | ---: | ---: | --- |
| 12 Cider press | One Page, all three files, unchecked setup checklist; wrong-tree but byte-identical fixtures | 23 | 186.650 | 222,315 / 161,792 / 7,817 |
| 13 Winterization | Failed: four Tasks instead of one, no uploaded/attached note | 24 | 123.667 | 282,436 / 260,608 / 8,771 |

Reported costs were $0.347 and $0.275 respectively, per historical session
records. Old file-backed Create routing, stale skills and MIME issues are
historical context, not present-day pass/fail requirements. Keep the semantic
counterexamples, and capture their first MCP baseline when they become relevant.

Next action: [targeted round 3](../ROUND_3.md), cases 01/02/08/09/11 after the
new deploy/client upgrade. Preserve these raw baselines until that comparison
has been reviewed, then roll over only the selected cases.
