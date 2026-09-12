# Backend Task Entities

Task behavior spans `entities/task.py`, `properties/task_*`, and
`tools/tasks/`. Read this guide before changing completion, recurrence,
history, task moves, or task combination.

## Scheduling

The `Schedule` process property selects one of three stored schedule sections:

| Type | Contract |
| --- | --- |
| Recurring | Numeric interval plus day/week/month/year unit. |
| Scheduled | Daily, selected weekdays, or a structured monthly/yearly calendar rule. |
| Periodic | Structured interval generated from a free-form description. |

`properties/task_scheduling.py` owns the stored section shape;
`tools/tasks/scheduling.py` owns recurrence and postponement calculations.
Reviewed AI report actions validate and write the same structured schedule
without invoking the scheduling model during execution.

Dates are stored in UTC and projected in the user's timezone. `Completed`,
`CompletedOn`, and `DueDate` remain separate values so a recurring task can
stay active while temporarily completed.

The reviewed Organize action `set_task_due_date` sets or clears only the due
date of an editable, incomplete Task. Calendar dates use the Task editor's
current-local-time behavior and retain recurrence and postponement metadata.
Its execution ledger records date/scheduling state for retry and guarded undo;
it never reopens a task or replaces the schedule.

Calendar schedules select valid calendar positions rather than clamping dates.
A monthly schedule for day 31 skips months without a 31st, and a yearly
February 29 schedule advances to the next leap year. Recurring and periodic
month/year intervals instead retain interval semantics, including end-of-month
clamping. Daily, weekly, and monthly calendar occurrences retain the prior due
date's local wall-clock time; yearly calendar occurrences use local midnight.

## Completion and scheduled uncompletion

Completing a scheduled task:

1. computes the next due date;
2. stores `scheduled_uncomplete_token` and an absolute
   `scheduled_uncomplete_at` in the completion mutation;
3. creates a deterministic Cloud Task as a post-commit effect; and
4. keeps the Task active with `completed=True` until a matching token clears
   completion state.

Duplicate or stale deliveries are successful no-ops. Manual uncompletion and
schedule clearing remove the durable marker. Backup/restore regenerates only
Cloud Tasks represented by these durable markers.

Completing a Task stores one `completed_submission` JSON envelope containing
the original `submission`, integer Form `generation`, and `form_key`, including
when completion does not post new answers. The flat Task submission and generation
remain the current values. Ordinary Task views, tables, filters, and AI projections
use that current submission with the current Form, even while the Task is
completed. Completion does not create a FormHistory record or copy Form assets.

`tools/form_definitions.py` separates current reads from explicitly requested
originals. **Show original submission** is offered only when a completed Task's
current submission has advanced beyond the envelope's generation and its values differ.
A changed Form version or generation alone does not establish a converted Task.
The explicit view reads the envelope and uses the current Form when the recorded
generation matches, resolving FormHistory only for a different or missing Form.
Labels, HTML and other presentation changes within
one generation remain visible in original views. Old `schema_version` hashes
do not select history; legacy rows without a generation start at zero.

Manual reopening defaults to archiving the current modified submission. Opening
the original view reveals a radio choice, initially original; the chosen source
is sent as `completion_submission` when the existing completion checkbox is
clicked. Automatic/scheduled reopening always uses the original envelope.
`Task.uncomplete(submission_source=...)` keeps that automatic default; manual
routes explicitly supply their modified/original choice. Both paths archive the
chosen raw values and matching Form generation into flat TaskHistory, preserving
attachments, relationships, name, description and completion metadata. Reopening
removes the envelope and clears all submission values. TaskHistory has no completion envelope, and
its `modified` value is fixed at creation. History readers use each record's
generation and batch distinct older-definition lookups.

Ordinary answer/default edits and Form reassignment still require reopening a
completed Task. A later transfer workflow may update flat current values on
completed Tasks; it must preserve their envelopes and TaskHistory originals.
That transfer engine is outside Step 1. Task construction and ordinary reads
do not capture or clone rows. Completion, reopening and guarded writes fetch
the persisted state at their mutation boundary and compare the protected
completion fields to reject stale or direct changes to original answers.

Missing archived definitions or historical static content produce an explicit unavailable
state, retaining raw original answers for review. Historical images are authorized
through the Task/TaskHistory that references them. After
a live Form is deleted, its restriction clause no longer applies. Tasks, Pages,
and retained completion/history content use the remaining live permission
sources. Loading a stale Form key resolves it to `None` without requiring a
record re-save; a relation that was never loaded still raises an unloaded-relation
error. Reads do not silently rewrite stored relationship keys.

## Fresh submissions and reopening

Every uncompletion opens a fresh submission. The attached Form, Page/Project,
assignment and other task settings remain in place; answer fields and completed
Todo items do not repeat. Legacy `default_submission` data is discarded on
uncompletion and ordinary submission saves.

**Fill from latest history** is an explicit, local form action. It restores one
field for the current submission, which is persisted through the normal Update
or completion flow. It creates no repeating defaults.

History fill checks exact field/option/column identities and compatible
representations before copying values. Labels and added choices/columns are safe;
missing definitions, removed identities or changed types require review. Failed
checks retain the original history and current answers. Reopening stages
source-asset cleanup after the guarded durable archive/reset commit.

## Move and combine

Task move and combine are dedicated services and routes, separate from ordinary
Task settings. That separation permits the actions on completed Tasks while
their settings and submission remain readonly.

Combine accepts Tasks from the same Page. Selected Tasks must have the same
model-task key; Tasks without a model can combine only with other unmodeled
Tasks. The caller needs delete permission for every selected Task.

The survivor is chosen deterministically:

1. newest `completed_on` when any selected Task has a completion timestamp;
2. otherwise newest `modified`;
3. entity key as the final tie-break.

Before deleting peers, the service writes their current state and existing
history beneath the survivor. Stable destination history keys make retry
idempotent. The browser receives one task-list delta containing the survivor,
deleted keys, and authoritative Page order.

## Ordering and indexes

`tools/tasks/ordering.py` owns canonical Page task ordering and Page-root
discovery. `TaskIndex` combines two ordered Datastore streams: due-dated Tasks
ascending by due date, followed by undated Tasks descending by modification.
`Entities.fetch()` preserves query-key order; do not sort a page again after
hydration.

## Change checklist

- Keep dates UTC at rest and timezone conversion at the presentation boundary.
- Make scheduled delivery token-checked and idempotent.
- Preserve immutable TaskHistory snapshots.
- Update mutation contracts when a relation or cascade changes.
- Cover duplicate delivery, retry, completion/reopening, and history behavior
  in focused unit tests.
