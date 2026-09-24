# Form and Offline Synchronization

Ordinary forms do not send field patches or register collaborative presence.
They use durable entity revisions for external-edit detection and explicit
IndexedDB commands for opted-in offline submissions.

## Committed form edits

`EditWatcher` discovers `lp-edited-marker` forms and records a baseline from
their nearest fingerprinted entity anchor. It subscribes only active visible
forms; a root form reuses the root entity subscription.

When a fingerprint changes, the watcher loads the form's focused replacement
route and delegates normalized comparison to `EditReconciler`:

- equivalent values acknowledge automatically unless the comparison omits
  incompatible fields from an unsaved or queued draft;
- schema change projects stable local field IDs into the current schema;
- renderer-backed value drift offers per-field saved/local choices;
- dirty simple forms offer reset;
- queued simple forms offer queued or saved whole-form state; and
- unsafe or unavailable replacements require a page reload.

Inactive forms retain their baseline and catch up when activated. Overlapping
probes are serialized by marker and revision. See
[FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md#watched-forms).

## OfflineQueue

Only a create/update form with `lp-offline` and a widget
`offline(context)` implementation may queue. IndexedDB stores:

- method, route, submitter role, and destination;
- entity fingerprint/modified precondition;
- structured FormRenderer values and ordinary fields;
- selected Files; and
- enough optimistic UI state to restore the queued record.

Local drafts are not durable until the User submits them.

Every IndexedDB helper resolves only after both its requested operation has
finished and the containing transaction emits `complete`. Request-level
success is not a durability acknowledgement. Transaction errors, aborts,
executor failures, and unexpected database closure reject once with the first
useful error and close the database connection. Read-only helpers use the same
boundary so callers always observe results from a completed transaction.

Reconnect replays commands in order. A revision mismatch retains the command
and opens the same reconciliation path used for an external edit. If current
schema/state can safely rebase the queued submission, the queue saves the new
precondition and retries within the same ordered pass. A conflict needing User
choice remains queued and blocks later commands. After a reload, comparison and
review use the persisted command's values, not the newly rendered saved form.
If the form mounts after replay found the conflict, it receives the retained
conflict when it initializes.

After acceptance, the queue removes the IndexedDB record and live lookup before
requesting an immediate entity poll. That ordering prevents the watcher from
mistaking accepted work for a pending local mutation.

## Startup and reconnect

Forms render authoritative server HTML without inspecting IndexedDB. Initial
replay waits for view publication and remains background work. Reconnect resumes
polling, document sync, EditWatcher, and visible refresh without waiting for
queue hydration or replay.

Code that needs to create a record calls `ensureOfflineQueue()`. `replayReady`
is an observation boundary for the current reconnect pass, not a rendering
prerequisite.

## Deferred form locks

Autofill's durable `DeferredJobLock` reserves one AI operation for the target;
it does not block ordinary editing or saving. Page/Task HTML bootstraps operation
status and review candidates. Focused form and task-list ETags include operation
revisions, and `form-lock` polling detects subsequent starts in other tabs.
Schema migration retains its real writer fence (`blocks_edit=true`).

The shared bar above Submit combines running autofill (Cancel), completed
autofill (Review), schema changes (Review), and another editor's saved changes.
Completion does not replace an actively viewed or dirty form. The review modal
compares current, saved, AI-proposed and pre-migration typed values. Incompatible
old values remain visible but cannot be selected. Acceptance changes the open
form only; ordinary Update persists it. Prompt-only AI refinement produces a
private candidate for the requesting editor, not an immediate saved answer.

Online Page/Task form writes carry `form-revision` as well as generation. The
server checks that baseline and fences the eventual commit with the loaded row;
a mismatch returns typed conflict state and leaves the draft untouched. Missing
baselines require review, including pre-upgrade cached clients. Duplicate AI
starts likewise do not acknowledge or clear the submitted draft.

A pending deterministic Form change also pauses every attached Page/Task. Its
Form-owned marker remains authoritative after job failure or expiry, so an old
terminal autofill descriptor cannot unlock partially converted submissions.
Builder recovery finishes or cancels the Form change through its dedicated route.

Submission forms and quick-edit requests carry their rendered generation. The
server rejects old representations after publication. Reconciliation checks field
type, cardinality, option identities and table columns before carrying local
values forward. Removed or incompatible local fields remain visible in the
saved/local review, but cannot be selected into a schema that cannot represent
them. A dirty or queued form requires explicit review before discarding those
values. Compatible local fields can still be retained.

Check schema compatibility before accepting matching projected values. Projection
omits incompatible local fields, so equality with the saved submission does not
mean the original draft is safe to discard. Keep its original schema and values,
and any queued command, until the user resolves the review.

`pre_migration` feeds the same modal, with the old schema used to render earlier
values. Closing the modal never saves or clears the durable notice. Successful
ordinary saves consume explicitly reviewed AI references; another editor's
private candidate is unaffected.

## Service worker boundary

The service worker owns response caching and offline network behavior. It
receives only the versioned connectivity-state message and does not carry
application updates between windows. `OfflineQueue` and document IndexedDB are
page-owned modules, not service-worker queues.

See [FRONTEND_SERVICE_WORKER.md](FRONTEND_SERVICE_WORKER.md).

## Change checklist

- Do not initialize forms from queued storage.
- Keep offline queueing opt-in per widget.
- Preserve ordered replay and stop at unresolved conflict.
- Reuse the normal form reconciliation UI for revision changes.
- Remove accepted records before publishing success.
- Keep service-worker caching separate from application mutation replay.
