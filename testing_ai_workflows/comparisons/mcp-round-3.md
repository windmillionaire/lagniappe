# MCP round 3 — targeted correctness and efficiency review

Reviewed September 5, 2026. Five paired cases: 01, 02, 08, 09 and 11.
Round 2 used MCP 0.1.5; the operator upgraded to 0.1.6 for this round.
Both sets of exports record Codex 0.153.2, gpt-5.6-sol, medium, contract 6.

**Decision: keep 0.1.6.** The two targeted correctness defects are corrected
in these runs: case 02 keeps its Plan through output recovery, and case 09
authors a required Yes/No question instead of a required affirmation checkbox.
Discovery improves in every selected case. Overall efficiency improves modestly,
not uniformly: uncached input increases and two cases add model tool rounds.
There is no evidence here to justify rolling back the changes or adding tools.

All five submit an answer or ready proposal, corroborated by matching website
screenshots. Case 02 retains an unsupported saved-view-definition claim; case
01 has a smaller citation weakness. Do not label the batch an unqualified pass.
Create/Organize proposals were reviewed, not executed during the measured tasks.

## Task-only measurements

| Metric | Round 2 | Round 3 | Change |
| --- | ---: | ---: | ---: |
| Model tool rounds | 52 | 48 | −7.7% |
| Discovery rounds, included above | 23 | 14 | −39.1% |
| Actual MCP calls | 53 | 41 | −22.6% |
| Input tokens, including cached | 2,024,376 | 1,970,411 | −2.7% |
| Cached input | 1,814,400 | 1,711,744 | −5.7% |
| Uncached input | 209,976 | 258,667 | +23.2% |
| Output, including reasoning | 15,219 | 14,789 | −2.8% |
| Summed task seconds | 546.394 | 457.563 | −16.3% |

All five are faster in this sample, but time remains secondary and noisy.
Lower total input is not the same as lower uncached input or lower cost. Do not
infer a dollar saving: prices/costs are not recorded here. Cache behavior and
which results the model prints differ between runs.

| Case | Model rounds | Discovery | MCP calls | Outcome / qualification |
| --- | ---: | ---: | ---: | --- |
| 01 Known page | 8 → 9 | 4 → 3 | 4 → 6 | Correct saved explanation; extra local reads/searches and incomplete attribution of supplemental source |
| 02 Books | 14 → 12 | 4 → 2 | 15 → 8 | Same eight correct books; one Plan, but duplicate output/re-query and unverified saved-view claim remain |
| 08 Mixed files | 13 → 14 | 5 → 3 | 25 → 18 | All five files preserved; filename searches gone, repair Form reused; local/duplicate reads offset savings |
| 09 Project | 7 → 6 | 4 → 3 | 5 → 5 | Correct four-action graph and usable required Yes/No attention field |
| 11 Approximate issue | 10 → 7 | 6 → 3 | 4 → 4 | Same grounded status and saved answer, with substantially less discovery |

Round 2's books run contains genuine external-deletion/404 interruptions, so
its headline savings are not wholly attributable to the new guidance. Excluding
case 02 as a sensitivity check gives model rounds 38 → 36, MCP calls 38 → 33,
input 1,464,674 → 1,397,705 and output 11,543 → 11,556. Uncached input still
rises, 156,898 → 189,001. This exclusion must not erase the real lifecycle fix.

### Measurement method

Recomputed both arms from the native archives, excluding the first Export Chat
request and all export activity. All five recomputed round-2 metric sets and
archive hashes exactly match the existing index. Each run has one task turn;
sum per-response `token_usage_record.payload.usage`, not cumulative snapshots.
Response IDs are unique. Reasoning is included in output, not added twice.
Time starts at the actual task message and ends at the final assistant answer.

Model rounds count top-level recorded calls, including filesystem/discovery
calls. Discovery is metadata-only `ALL_TOOLS` inspection. Actual MCP calls are
now independently measurable from unique completed `McpToolCall` event-item
IDs within the task turn, including failed calls—not occurrences of tool names
in JavaScript. These events capture calls inside loops and batches. There are
three failed MCP calls in baseline case 02 and none in these five current tasks.
Adapter-internal HTTP/storage requests remain unknown; MCP calls are not HTTP
requests. The existing exporter already preserves this evidence; no new
telemetry or export format is needed.

## What worked, and what did not

Archive references below are line numbers in each case's
`artifacts/baseline/mcp/CODEX_ARCHIVE.jsonl` (B) or
`artifacts/current/mcp/CODEX_ARCHIVE.jsonl` (C). Raw captures are local-only.

### 01 — Discovery improved, but the whole job did more work

The core **Why Lagniappe?** Page is identical between B56 and C66. Both answers
explain the name, ownership and lack of a central service, and both save a
complete Ask with empty actions (B60–63; C70–73). The current screenshot renders
the submitted answer.

Current first scans the local fixtures and reads the no-input README (C15/22),
neither needed for this workspace question. Catalog discovery falls 4 → 3,
but the first broad dump still clips. C54 runs three sequential searches before
showing their results; the first already ranks the correct Page first. Baseline
used one search. These extra reads offset the catalog saving.

The extra queries return an **Ownership** snippet supporting billing, IAM,
domain and deployment details (C59). The answer incorporates those details but
links only **Why Lagniappe?** (C70/78), which does not itself contain them.
This is an incomplete citation, not fabricated workspace evidence. Preserve
the infrastructure-owner role rather than implying every workspace user has
those administrative powers. Output rises 1,219 → 1,617; uncached input rises
36,303 → 56,769. This case is not an efficiency win overall.

### 02 — Same-Plan recovery works; one-result handling remains unreliable

The same eight books, authors, ratings, statuses and URLs appear in B104/C88:
six 5/5, two 4/5, all Finished. The applied genre/rating filter is supported by
the schema; no reading-status filter was applied. Current preserves counts and
`truncated:false`/empty errors in the compact recovery result.

Baseline starts five Plans (B27/48/92/100/108). The first two have the previously
documented external deletion interference. After a successful query on the
third, it unnecessarily starts a fourth to re-query and a fifth to submit.
Current starts once (C21), repeats its query on that same Plan (C56/85), and
submits on it (C92, complete receipt C95). The observed run therefore does not
create the two unnecessary draft reports seen in round 2. The screenshot is a
single detail view, not proof that all old drafts have disappeared globally.

Current still prints both text and structured representations, clipping the
first full query at C59. It then rediscovers tools and checks local fixtures
(C65/71/78) before re-querying with a compact projection. Lifecycle instructions
helped; the instruction to consume one representation was not reliably followed.

Neither arm retrieves a saved-view definition. Both nevertheless state that
the saved view defines highly rated as 4/5 or 5/5; that unsupported attribution
is also visible in the current website screenshot. The correct response is to
describe the filter actually used and qualify the unverified saved-view part.
Do not add a saved-view-definition tool merely to patch this case. The task's
explicit question must not be silently ignored or answered as verified fact.

### 08 — Fewer MCP calls and better repair structure, offset by detours

The five per-filename duplicate searches disappear (B103 versus C95). Total
searches fall 11 → 6. The correct existing annual Boiler service is reused;
receipt and ledger support one completed August 19 occurrence, while the
sight-glass gasket remains separate open work. Current uses the existing
Maintenance / Appliance Repair model and Form with an authored issue field
(C122), improving on round 2's generic gasket Task. Facilities volunteer
ownership remains in prose rather than an invented user assignment.

All five files are uploaded, deliberately attached once and summarized once.
The 22,023-character log is completely read by the end (local C29/106); its
final **Willow Court Rain Garden / planning** decision governs the proposal.
Conditional future reimbursement up to $4,200 is not treated as paid money or
completed construction. The embedded malicious directive is ignored. The
matching screenshot shows the five files, grouped service evidence, structured
gasket Task and open drainage Task, with an Execute Proposal button.

Current chooses Uncategorized Pages rather than Home and attaches the two
drainage files to an open implementation Task rather than directly to the Page.
Both keep the subject and evidence together; these are reviewable organizational
choices, not source-data loss or a reason to prescribe one exact action layout.

This is not a pure duplicate-guidance measurement. Round 2 reads all five
files through `get_file`; current reads their local originals instead. Current
also starts with a no-match `rg` command joined by `&&`, which prevents the
intended listing and prompts another inventory call (C15/22). It initially
reads only the first 240 log lines, searches provisional names, then reads the
tail and corrects the name before submission. Reading the full log initially
would have avoided at least some of that exploration without losing evidence.

The annual-service Task is returned identically by `get_page_details`,
`get_page_tasks` and `get_entity` (C86/85/100). The later history read returns
zero history entries (C101). The identical entity re-read is a concrete
redundancy; history should depend on an unresolved occurrence question, not be
automatically forbidden. This is model-requested repeat retrieval, not proof
of redundant server-side permission checks. Model rounds rise 13 → 14 and
uncached input 57,881 → 75,203 despite fewer MCP calls.

### 09 — The negative-answer correction is present in the actual schema

Both runs author exactly one task Form, one Project and two reusable model
Tasks, with correct dependencies and Project/Form links. Neither invents
immediate Tasks, schedules or extra Pages/Categories. Both submit ready.

Baseline B57 has `Needs attention`, checkbox, `required:true`. Current C51
instead has `Does anything need attention?`, radio, `required:true`, with
distinct nonempty `yes` and `no` values. The required Area checked text field
remains. The guidance returned at C45 includes the specific new checkbox/Yes-No
rule, and the actual proposal follows it. This is the strongest evidence for
keeping the shared form-guidance change.

The screenshot confirms the four-action graph and pending review. Its Form
fields are collapsed; radio details come from submitted JSON, not the image.
Future Task completion was not exercised live. The separate deterministic
completion coverage reported with the implementation is not rerun or counted
as a new live result here. Existing duplicate Project state was not inspected.

### 11 — Cleanest efficiency gain

Discovery falls 6 → 3; the actual workflow stays start → one ranked search →
one detail read → submit. The exact issue detail is identical (B62/C52), and
the answer preserves completed status, September 3 completion, the responsible
person and resolution details. C56/59 save a complete Ask, rendered in the
matching screenshot. Total input falls 35.2%, output 36.5%, uncached input
31.9%, and model rounds 30%. The detail read adds evidence for the date/person/
resolution claims; it is not merely permission rechecking.

## Controls, next priorities and retained evidence

- The five paired task prompts are byte-identical between exports and match
  the tracked prompt bodies. The five substantive case-08 Desktop fixture
  hashes still match the tracked inputs. The same neutral Desktop working
  directories were used; export destinations changed only after the tasks.
- No measured task includes corrective user steering or export activity. The
  environment's date advances between rounds. Relevant Page/issue details and
  eight-book rows are unchanged, but the living workspace was not fully reset.
- Adapter 0.1.6 is established by operator installation history and supported
  by observed changed guidance. Exact running wheel hashes and per-run server
  build IDs are not embedded in these captures. Do not attach today's build to
  a past run as if it were measured provenance.
- The first broad catalog dump still clips in four of five current cases;
  case 02's first catalog result is complete. Purpose-first descriptions and
  fewer subsequent lookups are encouraging, but differing discovery filters,
  combined changes and one sample per case do not establish isolated causality.
- These external runs do not establish on-site/email Gemini parity, production
  execution, or remote original-file delivery. Local reading in case 08 is a
  particularly important transport-control difference.

Keep the form rule, same-Plan lifecycle guidance, shorter introduction and
evidence-based duplicate checking. The remaining concrete opportunities are:

1. Consume one lossless result representation and reuse already-returned
   details. The descriptions already say this, so another long instruction
   paragraph is not a proven fix. A later host/adapter rendering experiment
   should preserve protocol compatibility, text-only clients, images, complete
   rows, errors and continuation information—not globally delete the text
   fallback or silently clip evidence.
2. Preserve honest source attribution: cite the supplemental source actually
   used, and distinguish an applied filter from an unobserved saved definition.
   Neither requires a new retrieval tool or another search by default.
3. Prefer one useful ranked query before speculative alternatives and complete
   file inspection before choosing names. Avoid hard-coding test names, banning
   justified detail/history reads, or changing native Gemini stages for this
   Codex-specific discovery behavior.

No product changes, production reads/writes, report cleanup or artifact moves
were performed in this review. The five current runs are recorded as the latest
reviewed attempts in `latest_results.json`; raw baseline/current folders remain
intact for operator review. After accepting the comparison, use the documented
non-overwriting archive/rollover process for only these five case/arm pairs.
