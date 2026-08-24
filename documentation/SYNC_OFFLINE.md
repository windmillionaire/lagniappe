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

- equivalent values acknowledge automatically;
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
- structured Renderer values and ordinary fields;
- selected Files; and
- enough optimistic UI state to restore the queued record.

Local drafts are not durable until the User submits them.

Reconnect replays commands in order. A revision mismatch retains the command
and opens the same reconciliation path used for an external edit. If current
schema/state can safely rebase the queued submission, the queue saves the new
precondition and retries within the same ordered pass. A conflict needing User
choice remains queued and blocks later commands.

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

Autofill and related Page/Task work can acquire a durable `DeferredJobLock` for
the target form. Submit, quick-edit, and default-field routes reject conflicting
mutations. `form-lock` polling restores the lock and operation status after
reload or in another tab even when the entity fingerprint is unchanged.

On terminal state, a matching clean form may reconcile automatically. Unsaved
or queued state retains the ordinary saved/local review boundary. A stale
rendered lock is also cleared from authoritative terminal state.

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
