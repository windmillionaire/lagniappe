# 07 — Existing issue update from a screenshot

Operator-only. Stress image grounding, target disambiguation, and preserving
unrelated fields while updating a completed or renamed existing issue.

## Preconditions and expected result

- The actor can edit the operator-confirmed existing issue about report status
  lagging a ready notification. The round-2 issue was completed and lived under
  AI Reports; the older assumed personal-Page/open seed was obsolete. Record
  its current title/parent/status and reproduction notes before the run.
- Inspect the PNG. It supports simultaneous **Analyzing files...** and
  **Organize report is ready.** It does not establish a cause, duration, or the
  full reproduction sequence on its own.
- Preserve existing reproduction notes and add the user-supplied sequence:
  start an Organize report with a file, open its report page while processing,
  then open notifications and observe the mismatch.
- Update only that issue's reproduction field, retaining unrelated fields and
  completion state. Attach the PNG once with a grounded summary. Do not create
  a replacement Task just because the correct existing issue is completed.
- Submit a reviewable report/link without executing it or claiming it applied.

## Evidence and controls

Prompt and synthetic PNG are unchanged from Desktop case 07. Both previous MCP
runs used the local PNG, so their correct result does **not** demonstrate
finalized MCP original-image delivery. Local inspection is sufficient for this
semantic case; a transport-specific image probe must be labeled separately.
Round 2 passed but continued searching after finding the right target. One
matching screenshot was saved under Desktop case 08. See
[review](../../comparisons/mcp-round-2.md).
