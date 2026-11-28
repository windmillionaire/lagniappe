---
title: Task Completion and History
category: tasks_and_collaboration
keywords:
  - task history
  - completion
  - undo
  - uncomplete
  - reopen
  - reopening
  - view original submission
  - archived form
  - fill from latest history
  - fresh submission
related:
  - tasks
  - task_scheduling
  - form_element_changes
---
Task history keeps an audit trail of every completed submission whenever a task is completed or reopened, preserving answers, form generation, timestamps, attachments, and context.

Even if a task form changes later, historical completions stay faithful to how the task was actually answered at the time.

## Original submissions and archived forms

- Completing a task preserves the **original submission**. Later form element conversions may alter how current values display without rewriting stored original history.
- Editors can click **View Original Submission** whenever converted answers differ from the original completion. If the live form was later deleted, an **archived form** view may still be available (or Lagniappe reports clearly when an archived definition is unavailable). Inspecting an original or archived view does not save changes.

## Reopening and reusing previous answers

- Manual reopening defaults to archiving current modified values (or offers archiving the original submission instead when available); automatic schedule-driven reopening always preserves the original completion submission.
- Reopening clears answer fields and checklist items for a fresh submission while retaining the task's form, assignee, schedule, and page/project links—earlier answers do not automatically prefill new runs.
- Use **Fill from latest history** to pull an available earlier value into a specific field, inspect it, and save or complete as usual (incompatible field changes are reported cleanly without losing history).
