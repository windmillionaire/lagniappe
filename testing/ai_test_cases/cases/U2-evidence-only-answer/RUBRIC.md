# U2 — Save an answer with uploaded evidence and no mutations

Operator-only. This complements U1: uploads must not force filing actions.
Case 01 answers a workspace question without an upload or an external save
request; it does not test evidence retention on a saved answer.

## Preconditions

- Upload only `fixtures/coverage-summary.md`, byte-for-byte unchanged.
- The actor can save a Plan and read its evidence. No destination Page, Task,
  payment record or preexisting policy is required.
- Use `PROMPT.md` for MCP or `PROMPT_ON_SITE.md` for the panel. Start a fresh
  conversation/report and keep the rubric out of its context.

## Expected result

- A saved answer gives the annual premium **$720**, deductible **$500 per
  claim**, and coverage **December 1, 2026 through November 30, 2027**.
- Payment status stays unknown. A premium or coverage period is not evidence
  that a payment happened.
- The Plan retains exactly the supplied file as **evidence**, with empty
  proposal actions. No Page/Task, attachment, file-move, summarize-file or
  placeholder skip action is needed. The report's own retained evidence is
  intentional persistence explicitly requested by the user.
- Return the saved-answer link; no workspace mutation or Execute step.

## Efficiency observation

Inspect the actual transcript, without coaching the model's tool order. An
empty action selection should return a valid compact saved-answer schema.
Evidence-only uploads should not require filing guidance or a dummy action
schema. MCP submission refreshes the current contract itself.

The September 16 MCP baseline is a successful first attempt that included these
avoidable detours; retain that cost. The native baseline passed directly. Compare
fresh initial runs, preserving any errors/retries and model-setting differences.
