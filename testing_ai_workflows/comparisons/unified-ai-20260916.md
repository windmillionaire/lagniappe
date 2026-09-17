# Unified AI verification — September 16, 2026

Reviewed all ten initial captures across MCP and the on-site panel, plus the
native 03 revision. The unified workflow handles the main jobs and fixes two
previous capability gaps: U1 creates Tasks and moves existing files without
uploads; U2 saves an answer with uploaded evidence and no filing actions.
Workspace mutation proposals were reviewed but not executed.

## Baseline rollover

At the operator's request, 01/03/08/U1/U2 now have these newer results in their
flat `artifacts/baseline` folders. `mcp__` and `on-site__` prefixes distinguish
arms. Their `artifacts/current` folders are empty. Other cases are unchanged.
`latest_results.json` retains metrics, hashes, deployment identity and caveats.
U1 and U2 now include reusable prompts, synthetic fixtures/setup and rubrics.

All 119 files from `~/Desktop/unified-ai-baselines` were copied and SHA-256
verified under `reports/unified-ai-verification-20260916/desktop-capture`.
That ignored archive preserves the pre-unification U1/U2 baselines, all unified
captures, readbacks, screenshots, revision, and operator notes. Replaced library
captures and the previous result index are preserved alongside it. The copy and
rollover manifests record hashes. Raw captures remain local-only and must not
be force-added; compact comparison notes, fixtures and metrics are tracked.

The copied Desktop pack can be deleted without losing this evidence. Keep a
neutral fixture copy for subsequent MCP runs; do not run measured chats from
inside the application checkout.

## Current baselines

| Case | MCP tokens | MCP calls / rounds | On-site tokens | On-site calls / rounds |
| --- | ---: | ---: | ---: | ---: |
| 01 | 139,020 | 3 / 4 | 41,369 | 4 / 2 |
| 03 initial | 188,796 | 3 / 5 | 540,981 | 24 / 17 |
| 08 | 985,124 | 23 / 16 | 419,004 | 30 / 8 |
| U1 | 274,517 | 10 / 7 | 89,796 | 12 / 4 |
| U2 | 462,751 | 7 / 12 | 17,099 | 1 / 1 |

MCP uses Codex task-turn token usage, excluding exports; reasoning is already
included in output. Its rounds count top-level model tool calls, including
orchestration. Native totals include planning and file summaries once; thought
tokens are separate from output. Native rounds count provider tool rounds.
These round definitions and the two models are not interchangeable.

The initial unified deployment was app `20260916t152433`, MCP revision
`lagniappe-mcp-00023-fl5`. MCP used `gpt-6-astra`/xhigh; native planning used
`gemini-3.8-flash`. Historical MCP 01/03/08 used sol/medium and different live
workspace context, so their changes are rough comparisons, not isolated savings.
U1/U2 have same-setting MCP before/after captures; native 01/03/08 have no
matching older native baselines.

## Outcomes and limits

- **01:** Both answers are grounded. External MCP correctly avoids creating a
  Plan without a save request. Its relative source link was not click-tested.
- **03:** MCP chose the personal Page and exact due timestamp. Native chose a
  relevant emergency guide, retained October 15 and 5 PM, and produced a usable
  proposal. The prompt did not demand the personal Page. Date-only storage plus
  time in the description is less precise, and “I have set up” was premature.
  Revising the same native Plan moved it to the personal Page and corrected the
  wording: 18,094 tokens, two calls, one round, 21 seconds. That is revision
  evidence, not a replacement for the 540,981-token initial-run baseline.
- **08:** Both retained all five files, the final Rain Garden name, planning
  status, separate open gasket work, and future-only grant funding. Native used
  `complete_task`, which would date completion at execution instead of August
  19; the proposal needs correction before execution. MCP imported the dated
  occurrence correctly. Generic placement differences were acceptable.
- **U1:** Both now propose all six requested changes in one Plan. Older native
  Organize refused Task creation/moves; the older external route needed split
  plans and still could not place the files.
- **U2:** Both save the requested answer and evidence with no mutations. MCP
  encountered an empty-action schema rejection, then fetched irrelevant filing
  guidance and a skip schema. Its initial cost remains in the baseline.

U1 MCP total tokens fell from 536,595 to 274,517 while doing more complete work.
U2 native fell from 267,088 to 17,099 while avoiding unwanted filing. U2 MCP rose
from 181,923 to 462,751 while gaining the formerly unsupported evidence save;
uncached input changed only from 31,537 to 33,579. Token totals alone conceal
both capability differences and cache behavior.

A separate older on-site Organize example used 954,685 planning input tokens,
17 provider requests, 16 rounds and 26 calls for one file. Unified 08 used
385,240 planning input, nine requests, eight rounds and 30 calls for five files,
with similar tool-result text volume. That supports investigating round and
transcript costs, but different jobs prevent attributing a 60% saving to this
change. The older job was also faster (157 versus 228 seconds).

## Cleanup and next checks

Local follow-up changes supply native personal-Page/scheduling guidance, clarify
source-dated completion actions, allow an empty selected-action schema, make
filing guidance conditional on organizing, and remove contradictory MCP final
contract-refresh advice. These baselines predate that cleanup.

After deploying both app and MCP, run fresh native 03, fresh native 08 with the
same five files, and fresh MCP U2. Save the first attempts under `current`, with
arm prefixes; retain plan IDs, proposals and job telemetry for native runs, and
task-only archives for MCP. Use the same model settings if comparing efficiency,
or record a change to sol/medium explicitly. Keep neutral prompts separate from
these operator notes. Review results before any proposal execution.

Merge into `next/2.2.0` after the live review, then perform the complete E2E run
after the operator's possible additional change. That merge and full run have
not been performed by this cleanup.

## Cleanup live checks — September 16 evening (September 17 UTC)

The newer reviewed attempts are retained in `artifacts/current` and indexed as
latest results; their September 16 initial baselines remain intact.

| Run | Previous tokens | New tokens | Previous calls / rounds | New calls / rounds | Previous / new seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| MCP U2 | 462,751 | 455,700 | 7 / 12 | 7 / 13 | 138.217 / 117.283 |
| Native 03 | 540,981 | 237,817 | 24 / 17 | 17 / 8 | 163 / 225 |
| Native 08, all attempts | 419,004 | 404,855 | 30 / 8 | 53 / 9 | 228 / 843 |

MCP U2 still uses astra/xhigh and the identical prompt/fixture. Readback confirms
the correct saved answer, exactly one unchanged evidence file, and no mutation
actions. It made no filing/action-guidance call. However, the remote workload
identity transport rejected explicit empty `actions=` queries with
`incompatible_url: Unexpected contract query`. Start context recovery and two
failed contract reads forced the agent to fetch the full schema. This is a real
remote-path bug missed by the earlier direct REST/adapter boundary check, not
an unsuccessful answer. Uncached input rose from 33,579 to 36,578 tokens.

The local URL guard now permits the exact empty selection while continuing to
reject malformed lists, duplicate query keys and foreign destinations. All 14
remote-server tests passed, including authenticated envelope requests with empty
actions in every view. After redeploying MCP, verify a compact empty-action read
on this existing saved Plan; another full measured U2 conversation is unnecessary
unless a clean efficiency measurement is wanted. The fix is not yet deployed.

Native 03 again selected Power-Outage Kit Guide, which the operator accepts.
It explicitly offered the personal Page as an alternative and correctly said
the task was planned. The personal context was therefore available, even though
the full provider prompt is not stored in telemetry. The requested date and
5 PM description were retained. Its claim that due dates only support calendar
dates overstates the storage limitation: the ordinary editor is date-only, but
creation supports an ISO timestamp. Keep that as an accepted caveat; do not
force a new destination policy. The run succeeded in one attempt, with 56% fewer
total tokens and fewer rounds, but higher elapsed time.

Native 08 **succeeded on the automatic second attempt**, and the historical-date
fix worked. Its proposal reuses the existing annual boiler service Task with
`create_task`, `completed=true`, and `completed_on=2026-08-19`; it no longer uses
an execution-time `complete_task` action. The receipt and accounting export both
attach to that Task. Gasket replacement stays open with the maintenance Form,
and both drainage files share the final Willow Court Rain Garden Page. The long
log's final planning state and the grant's conditional future reimbursement are
preserved. All five files have distinct attachment actions and valid dependency
references. The screenshot and saved proposal agree; execution was not tested.

The remaining wording caveat is unchanged: the answer describes filing as already
applied, although the summary correctly calls these filing proposals. Native
summaries run before planning; no `summarize_file` proposal action is expected.
Three summary generations appear once in telemetry. Persisted summaries and
retrieval terms were not separately read back, so their contents are not newly
verified by this capture.

Observed usage comprises **130,681** tokens for the failed planning attempt,
**265,284** for successful planning, and **8,890** for the one-time summaries:
**404,855 total**, 3.4% below the initial unified baseline. The successful planner
used 30 calls over five rounds; including the failed attempt gives 53 calls over
nine rounds and 843 seconds (14:03) overall. The first attempt's 504 and automatic
retry are retained as reliability evidence, without treating provider contention
alone as a workflow regression. Full usage for the timed-out provider request
is unavailable, so these are observed totals, not a billing reconciliation.

Successful planning input fell from 385,240 to 222,962 tokens (42%); all-attempt
uncached input instead rose from 176,321 to 282,320. The retry reports `priority`
service tier, while the first attempt and initial baseline report `standard`.
These differences and the mutable workspace prevent a clean cost or latency
claim. No further full model rerun is required for the targeted date fix.

All three cleanup live cases are now reviewed. Remaining live check: redeploy
the MCP URL-guard fix and read the existing U2 Plan's empty-action schema. The
merge and complete E2E run remain outstanding, with the operator's possible
additional change before E2E.

To close the wording caveat, the local native planner instruction now explicitly
requires proposed/awaiting-execution wording in both `summary` and
`answer_markdown`, with an attachment example and a distinction between an
already-completed real service and its still-proposed record update. This
replaces the existing generic prohibition. Deploy it with the MCP fix, then
revise only the existing 08 answer/summary and compare the action data with the
saved proposal. That focused check has not yet been run; it does not require
another full five-file submission.

### Post-deployment check

The operator deployed the fixes. A live `lagniappe-mcp.get_plan_contract` read
of the existing U2 Plan with `actions=[]`, `view="schema"` now succeeds and
returns contract version 9 with `actions: {type: "array", maxItems: 0}`. The
remote URL-guard issue is verified resolved. Capture:
`reports/unified-ai-verification-20260916/U2_POSTDEPLOY_EMPTY_ACTIONS.json`.
Native 08's wording revision also passes. Read-only Datastore retrieval of the
same report confirms only `answer_html` and `summary` changed. All nine action
objects are exactly equal to the prior capture, including their order, IDs,
dependencies, dates, field values and file destinations. Their canonical SHA-256
is `9a1fa53a510f0654bbca3f302cfeb651148c3992ae7936ac1277cdc35c07c5af` both before
and after. The answer and summary clearly distinguish completed real-world
service from workspace edits awaiting approval. The report remains `ready`;
execution was not tested. Revision telemetry was not captured or added to the
initial run's measurements. Screenshots and readback are preserved separately
under case 08's `artifacts/current/on-site__wording_revision*` and
`reports/unified-ai-verification-20260916/08_WORDING_REVISION_REVIEW.json`.
