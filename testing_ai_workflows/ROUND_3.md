# Targeted MCP round 3

Completed and reviewed September 5, 2026: [comparison](comparisons/mcp-round-3.md).
All five current captures are present; the preparation/operator notes below are
retained as provenance, not instructions to rerun or overwrite this batch.

Baseline: preserved round-2 MCP captures (0.1.5, Sol medium). Candidate: the
next deployed server and **lagniappe-mcp 0.1.6**. The candidate is prepared
locally; deployment and installed-client upgrade are operator steps.

## Run only these five

| Case | Look for | Preserve / possible downside |
| --- | --- | --- |
| 01 | Less clipped/broad tool discovery and quicker selection of the relevant tools | Same grounded explanation, source link and saved Ask answer |
| 02 | One surviving Plan through query/output handling and submission | All eight rows, accurate counts/fields, honest saved-view attribution; no draft duplicates |
| 08 | Duplicate checks reuse already-returned evidence instead of one filename search per file | Complete long-file evidence, grouped completed service, separate open work, all attachments/summaries |
| 09 | Form can record both attention-needed and no-attention answers | Correct Project, reusable work types, task Form; no extra immediate Tasks |
| 11 | Direct Lagniappe tool discovery plus useful approximate search | Correct issue/status, supporting source and persisted Ask answer |

Baseline case 02 includes two earlier website deletions and two later
unnecessary drafts; case 09 contains the defective required checkbox. Keep
those first captures. Do not hide their failures when comparing the candidate.

## Operator steps

1. Commit/deploy the prepared changes through the normal release process.
2. Use the site's newly advertised pipx command for 0.1.6, check the existing
   profile, and restart Codex. No new profile/API key is required.
3. Use the same Sol/medium setting and intended Lagniappe profile. Start each
   fresh session in its **original Desktop trial `fixtures/` directory** and
   paste the unchanged prompt. Those inputs match the tracked cases. Do not
   launch inside the code checkout: that would add repository instructions
   that were absent from the baseline.
4. Review the website result, then export to the corresponding new repository
   destination below. Provide that path only after the measured task finishes.
5. Ask for the round-3 comparison. Do not move baseline/current or delete
   reports until the capture and analysis are complete.

No extra telemetry command. Do not paste this document or the rubric into the
measured session. Record any changed workspace facts or operator steering.
The tracked library preserves prompt and substantive fixture bytes. Keeping the
existing neutral Desktop working directories also preserves instruction context;
only the post-task export destination changes.

Launch under `/home/swifty/Desktop/lagniappe-mcp-trial/<case>/fixtures/`.
When finished, ask “Export this chat to …” with the appropriate destination:

```text
/home/swifty/lagniappe/testing_ai_workflows/cases/01-ask-known-page/artifacts/current/mcp
/home/swifty/lagniappe/testing_ai_workflows/cases/02-ask-books-filter/artifacts/current/mcp
/home/swifty/lagniappe/testing_ai_workflows/cases/08-organize-mixed-files/artifacts/current/mcp
/home/swifty/lagniappe/testing_ai_workflows/cases/09-create-project/artifacts/current/mcp
/home/swifty/lagniappe/testing_ai_workflows/cases/11-ask-approximate-issue/artifacts/current/mcp
```

The existing installed Export Chat skill is unchanged. A reusable copy, including
its helper, is now tracked in [skills/export-chat/](skills/export-chat/SKILL.md);
see the [export instructions](README.md#export-skill) if it is not installed.

Case 09's live boundary is still the reviewable proposal. Inspect the form's
negative-answer semantics; do not execute a production proposal just to score
it. A focused deterministic completion regression supplements this check.

The shared form rule also applies to on-site/email Gemini, but native workflows
retain their own planning/completion stages. A separate native Project smoke is
useful if desired; these five MCP runs do not claim live three-entry-point parity.

Keep fewer rounds and tokens when quality is maintained. Treat time as a noisy
secondary observation, not a hard gate. This is a practical combined-change
comparison, not five experiments isolating individual instructions.

## Prepared candidate checks

Local verification: 134 adapter tests, 21 standalone file tests, 82 affected
backend unit cases, and 50 tooling/package/library checks passed (287 distinct
cases; repeated focused runs are not added twice). Changed-source traceability
has no errors or warnings; focused Ruff and whitespace checks pass. Input and
all thirteen imported raw archive hashes match their preserved sources.

MCP 0.1.6 was built twice with identical bytes and promoted to the local immutable
release ledger. Wheel SHA-256:
`6850562a8289ca3479e4a3dbaf169d62e0eb763bed649780b3302cfacd170cf2`.
After committing the source, new wheel/ledger and library, run
`venv/bin/python run.py mcp-artifact check` before the normal deploy.
The Git-aware check is deliberately post-commit. No production deployment,
installed-profile change, live model run or full hosted/E2E suite was performed
for that preparation. The subsequent operator runs and review are recorded in
the comparison linked above.
