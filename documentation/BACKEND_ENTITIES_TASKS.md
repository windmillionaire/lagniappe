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

Task completion pins an exact Form content version, including when completion
does not post form answers. Trusted current content versions need no snapshot
lookup or write during completion; publication retains the immutable FormHistory
definition for later reads. Legacy Forms are captured at completion when needed.
The completion initially remains on the live Task. Reopening first archives it
as TaskHistory, preserving the recorded schema version, raw answers, attachments,
relationships, name, description and completion metadata. History `modified` is
fixed at creation. Ordinary answer/default edits and Form reassignment cannot
mutate a completed Task or TaskHistory; guarded writes also reject changes made
through a stale or directly modified root object.

`tools/form_definitions.py` owns the effective submission definition boundary.
Active Tasks and Pages use current Form metadata. Completing a Task stores one
`completed_submission` JSON envelope containing the exact `submission`,
`schema_version`, and original `form_key`. Completed readers use that envelope;
legacy Tasks and existing TaskHistory rows continue reading their flat fields.
Matching trusted current Form versions serve completed reads directly. Only a
changed or missing Form requires a historical definition lookup; collection loads
batch those unique mismatches. Reopening archives the envelope into the existing
flat TaskHistory format before removing it and restoring compatible active values.
Task construction does not hydrate or clone the database row. First actual raw
access retains only serialized completion fields for mutation checks; guarded
writes compare those protected fields so whole saves cannot overwrite a newer
completion or reopen. Missing legacy definitions or static content produce an
explicit unavailable state without substituting current labels or modifying the
saved answers. Snapshot
images are authorized through the Task/TaskHistory that references them. After
a live Form is deleted, its current access policy is unavailable: only admins
can read retained completion/history content, subject to the existing page access
check. Ordinary users fail closed; no ACL tombstone or permission version is stored.

## Defaults and reopening

`default_submission` stores selected values that should repeat when a task is
reopened. `SubmitterMixin.save_default_field()` writes one field through a
root-only property mask. A later submit keeps unchanged defaults and removes
values that changed or disappeared.

Todo fields never repeat as defaults. History retains the completed checklist;
the reopened Task starts with no todo items. Assignment remains in place across
completion and reopening.

Reopening and history fill check exact field/option/column identities and compatible
representations before copying values. Labels and added choices/columns are safe;
missing definitions, removed identities or changed types require review. Failed
checks retain the original completion and defaults. Reopening stages source-asset
cleanup after the guarded durable archive/reset commit.

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
