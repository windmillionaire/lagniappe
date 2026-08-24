# Frontend View Reconciliation

Mounted browser state changes through four distinct paths: watched entity
forms, collection refresh, deferred-operation completion, and notification
state. Collaborative documents use their own revision protocol in
[SYNC_DOCUMENTS.md](SYNC_DOCUMENTS.md).

## Authorities

| Surface | Authority | Browser owner |
| --- | --- | --- |
| Entity/form values | Durable `fingerprint` and `modified`. | `EditWatcher` / `EditReconciler`. |
| Collection membership | Durable site/channel revision. | Core collection refresh. |
| Deferred work | `DeferredJob.status_revision` and destination metadata. | `DeferredOperationManager`. |
| Form operation lock | `DeferredJobLock`. | Form widget plus `form-lock` polling. |
| Notification badge/list | Durable aggregate with Redis invalidation projection. | Notification state/menu. |

The shared `PollingCoordinator` batches these descriptors, but their consumers
remain separate. A poll result is an invalidation signal; focused replacement
routes continue to own HTML and full data.

## Watched forms

A server-rendered entity anchor carries `data-key`, `data-fingerprint`, and,
for Page/Task forms, `data-modified`. An `lp-edited-marker` inside a form points
to a side-effect-free focused replacement route. `EditWatcher` starts from
markers rather than every `[lp-entity]` row and subscribes only active visible
forms.

Each marker keeps its own baseline. The root entity subscription supplies the
newest observed revision. An inactive form performs no replacement request; on
activation it compares baselines and catches up once when stale.

For a changed active form, `EditReconciler` renders the focused response in a
detached preview and compares normalized submissions:

- equal state installs automatically;
- schema-only change projects stable local field IDs into the current schema;
- renderer-capable value drift offers field-by-field saved/local choices;
- a dirty non-renderer form offers **Reset form**;
- a queued non-renderer form offers queued versus saved whole-form state; and
- missing, inaccessible, or unsafe replacement falls back to **Reload page**.

A visible active form is protected even when clean, and focused forms are
protected before the first input event. Probes are serialized per marker and
revision: identical overlap shares a request, and a newer follow-up cannot let
a slow earlier response overwrite current state.

Successful mutation responses carry `X-Lagniappe-Entity-Revisions`. The
originating request normally acknowledges those revisions because its own
response already reconciled the component. Poll-driven probes suppress the
acknowledgement until comparison completes.

## Collection refresh

Loaded list/table widgets opt in with `refreshScope = "collection"`. A changed
channel invokes the batched `/l/refresh` contract where supported, then falls
back to a widget's focused GET route. Data fetch and detached preparation
finish first; root fingerprint, row changes, deletions, supplemental nav, and
widget commits apply together.

Forms never participate in generic collection replacement. Active, dirty,
queued, or staged-review rows are protected. Hidden clean rows may refresh
silently. If a changed row belongs to a loaded DOM collection whose widget has
not been instantiated, Core loads the collection owner before refreshing it.

Index roots keep raw refresh fingerprints separate from opaque poll-channel
revisions. Home widgets own independent channels—Notes, Tasks, Starred, Pages,
Projects, Categories, Ingress, and Tool Reports—so a change refreshes only its
consumer.

Star and delete are collection changes, not form revision changes. A committed
delete removes exact entity-key DOM nodes before collection and supplemental
navigation refresh.

## Deferred operations and form locks

An online deferred acknowledgement registers an opaque operation descriptor.
Server-rendered operation markers seed their current phase and revision; a
locally started operation requests an immediate check. The coordinator uses
adaptive backoff and rejects a status revision older than the one already
seen.

Terminal status causes `DeferredOperationManager` to locate the declared source
and destination and fetch authoritative replacement state. It never applies
model output from the poll payload. Destination identity includes the mounted
widget key where repeated widget names exist.

PageInfo and TaskForm also consume `form-lock`. A reload or another tab can
restore the active job and progress state even when the target fingerprint did
not change. The terminal result may replace an active form automatically only
when the operation matches its durable lock and the form has no unsaved or
queued state. Otherwise normal form reconciliation protects the draft.

Ordinary polling pauses while hidden, unfocused, or offline. A visible tab in
an unfocused window may retain only connected, rendered operation progress for
at most ten minutes. Documents, forms, entities, ingress, collections, health,
and notification-only work remain suspended.

## Notifications

`X-Lagniappe-Notification-State` contains only Redis generation, revision, and
the combined ordinary-plus-unread-message count. It can arrive on `/l/ping`,
ordinary requests, or `/l/poll`.

The authenticated control is always rendered. It shows an indeterminate state
until the first authoritative projection, then shows the exact count including
zero. Opening the menu loads ordinary Notifications and the durable aggregate.
A changed cursor marks an already-loaded list stale; the list refreshes
immediately only while open.

The Messages entry represents the aggregate and cannot be cleared with
ordinary Notifications. **Clear All** affects ordinary rows only. Message
history is loaded by the Messages view, not by the menu query.

## Offline replay

Offline mutation records retain the request, entity revision precondition,
structured submission, ordinary fields, and files. Reconnect replays in order.
A revision mismatch hands the form to `EditReconciler`; a safely rebased form
updates the queued precondition and retries in the same ordered replay. A
choice-dependent conflict stays queued.

After server acceptance, the queue removes the durable record and live lookup
before publishing replay success or requesting a fresh entity poll. That order
prevents reconciliation from treating committed work as still queued.

## Change checklist

- Choose entity, collection, operation, lock, notification, or document
  authority explicitly.
- Keep poll payloads bounded and fetch rich state from focused routes.
- Protect active drafts and rows from generic replacement.
- Serialize overlapping probes by identity and revision.
- Make terminal operation status trigger a refetch, not a success assumption.
- Test stale response rejection, hidden/active transitions, and offline replay
  at the JavaScript or E2E layer appropriate to the behavior.
