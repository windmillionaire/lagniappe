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

Task completion creates immutable `TaskHistory` snapshots. A history row keeps
the task/form schema, submission, attachments, relationships, name,
description, and completion metadata from that event. Its `modified` value is
fixed at creation, so its entity fingerprint remains stable even if the live
Form later changes.

## Defaults and reopening

`default_submission` stores selected values that should repeat when a task is
reopened. `SubmitterMixin.save_default_field()` writes one field through a
root-only property mask. A later submit keeps unchanged defaults and removes
values that changed or disappeared.

Todo fields never repeat as defaults. History retains the completed checklist;
the reopened Task starts with no todo items. Assignment remains in place across
completion and reopening.

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
