---
title: Converting and Deleting Form Elements
category: pages_and_forms
keywords:
  - convert field
  - replace with
  - delete element
  - form update
  - form migration
  - existing answers
  - retry form update
  - before and after
related:
  - form_builder
  - form_settings
  - task_history
---
Replace With and Delete stage schema changes inside your Form Builder draft and apply them to existing pages or tasks once you save.

Builder **Undo** reverses draft changes before saving; once you save a form update and data migration runs, Undo cannot roll back converted or cleared answers.

## Converting field values

- Select an element in the builder, open **Replace With**, pick a compatible component type, and choose **Convert**.
- **Deterministic conversions** use predictable rules (for example, `"42"` converts cleanly into a number, while `"unknown"` does not; values that cannot convert cleanly are cleared).
- **AI-assisted conversions** require **Create** AI access and edit access on every affected page or task. Add any conversion guidance before clicking **Save**.
- When converting to **Table** or **Select**, configure final destination columns, options, and **Multiple** settings before saving—conversion uses the saved target configuration. Components without a valid replacement offer **Delete** only.

## Deleting elements and monitoring updates

- **Delete** removes the component from the form and, upon **Save**, clears its current values from active submissions (completed task history preserves original recorded answers and form generations).
- Affected submissions stay locked while the migration runs; the builder reports **Form update finished.** or **Form update needs attention** (with error details and **Retry**). Updated submissions may display a before-and-after change notice until the next save, completion, or reopen.
