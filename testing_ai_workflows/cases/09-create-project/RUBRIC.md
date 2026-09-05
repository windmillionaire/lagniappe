# 09 — Reusable project and meaningful negative answers

Operator-only. Stress Project/work-type composition and the usability of an
authored form, not only whether its schema passes submission validation.

## Preconditions and expected result

- The actor can create Projects, task Forms, and model Tasks. Record any
  previously executed Community Garden Care setup; do not hide duplicate seed
  state or silently reset it. No attachments are needed.
- Propose **Community Garden Care** with reusable **Irrigation Check** and
  **Tool Repair** work types, correctly linked to the Project.
- Irrigation checks record the checked area and whether anything needs
  attention. Both **yes** and **no** must be meaningful valid answers. A
  required Yes/No choice is suitable; an optional checkbox can represent no by
  being unchecked. A required “Needs attention” checkbox is not suitable: it
  requires yes, making a no-attention check impossible to complete honestly.
- Forms and model Tasks have valid references/dependencies. Sensible shared
  forms or equivalent labels are fine. No immediate checks, repairs, recurring
  schedules, Category, or unrelated Page is requested.
- Submit a ready proposal and usable review link without execution.

## Targeted round 3 observation

Inspect the actual field type/requiredness, not the assistant's reassuring
prose. Separately verify the no-attention completion boundary with deterministic
coverage or explicitly authorized disposable execution. A ready proposal alone
does not prove future task completion. Do not prohibit required acknowledgement
checkboxes generally; they mean something different.

## Evidence and controls

Prompt unchanged from Desktop case 09. Round 2's graph was correct, but its
required checkbox had the code-confirmed downstream no-answer defect; no live
completion was attempted. Shared domain guidance matters to native/email as
well as MCP, but an external run does not establish live Gemini parity. See
[review](../../comparisons/mcp-round-2.md).
