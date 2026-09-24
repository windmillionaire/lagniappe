# Frontend View Reconciliation

Mounted browser state changes through four distinct paths: watched entity
forms, collection refresh, deferred-operation completion, and notification
state. Collaborative documents use their own revision protocol in
[SYNC_DOCUMENTS.md](SYNC_DOCUMENTS.md).

## Authorities

| Surface | Authority | Browser owner |
| --- | --- | --- |
| Entity/form values | Fingerprint derived from durable state, effective restrictions, and own form version. | `EditWatcher` / `EditReconciler`. |
| Collection membership | Durable site/channel revision. | Core collection refresh. |
| Deferred work | `DeferredJob.status_revision` and destination metadata. | `DeferredOperationManager`. |
| Form operation lock | `DeferredJobLock`. | Form widget plus `form-lock` polling. |
| Notification badge/list | Durable aggregate with Redis invalidation projection. | Notification state/menu. |

The shared `PollingCoordinator` batches these descriptors, but their consumers
remain separate. A poll result is an invalidation signal; focused replacement
routes continue to own HTML and full data.

## Watched forms

The watcher, reconciler, review modals, and detached preview adapter live in
`forms/revisions/`. Core loads the watcher through `ensureEditWatcher()`;
the other modules remain internal to that service. Pure schema compatibility
comparisons live below them in `forms/representation.mjs`. Page/Task migration,
remote-edit, and autofill notices share the FormWidget-owned `forms/reviewBar.mjs`;
`forms/migrationNotice.mjs` remains a fallback for forms without review state.

A server-rendered entity anchor carries `data-key`, `data-fingerprint`, and,
for Page/Task forms, `data-modified`. An `lp-edited-marker` inside a form points
to a side-effect-free focused replacement route. `EditWatcher` starts from
markers rather than every `[lp-entity]` row and subscribes only active visible
forms.

Each marker keeps its own baseline. The root entity subscription supplies the
newest observed revision. An inactive form performs no replacement request; on
activation it compares baselines and catches up once when stale.

For a changed active form, `EditReconciler` uses
`forms/revisions/preview.mjs::loadRevisionPreview()` to render the focused
response in a detached preview and compares normalized submissions:

- an unchanged saved baseline and schema leave the live form and draft intact;
- otherwise, equal state installs automatically unless projecting an unsaved or
  queued draft omitted incompatible fields;
- schema-only change projects stable local field IDs into the current schema;
- renderer-capable value drift offers field-by-field saved/local choices;
- a dirty non-renderer form offers **Reset form**;
- a queued non-renderer form offers queued versus saved whole-form state; and
- missing, inaccessible, or unsafe replacement falls back to **Reload page**.

Revision modals use the same adapter for saved/local previews. It clones
response DOM and delegates construction to the generic widget loader, leaving
the original response available for application to the live form.
An online save rejected with a structured form conflict still carries replacement
HTML; the request layer parses it into a document before the reconciler renders
choices. After staging a rejected online Update, the browser refreshes the saved
values and opens the chooser directly when field-level review is available. If
the latest values already resolve the conflict, it leaves no false reload notice.
When the rejected action was an Autofill start, the chooser explicitly says the
job did not start and asks the user to select values before starting Autofill
again; ordinary Update and completion reviews keep their usual copy. A rejected
start also resets the Autofill submit button from **Starting…** to its idle
label while the chooser is open.
If preview construction fails, the form retains its draft, offers a reload
fallback, and releases the Update button instead of remaining busy.
The review/operation notice sits above an expanded Autofill Context panel.

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

Each row manifest contains `key`, `hash`, and `fingerprint`. The server loads the
parent revision. A changed parent or authorization revision triggers a root
membership/order query; an unchanged parent reuses the manifest's membership.
Both paths compare a batch of cached detail fingerprints.
It resolves only new, changed, or uncached rows with `Fetch.nested()` before
authorization and rendering. The view carries a separate authorization revision;
a change to that revision rechecks all candidates. Cache loss triggers canonical
loading rather than treating the row as deleted. Display/sort timestamps remain
independent of refresh fingerprints.

User rows identify their cached Page. A changed Users collection also refreshes
User-backed columns such as groups and last login. Form indexes retain full
fragment replacement when their collection revision changes.

Forms never participate in generic collection replacement. Active, dirty,
queued, or staged-review rows are protected. Hidden clean rows may refresh
silently. If a changed row belongs to a loaded DOM collection whose widget has
not been instantiated, Core loads the collection owner before refreshing it.

Task-index refresh fingerprints include the same viewer-scoped Tasks revision as
their poll channel. Other index roots retain their established fingerprints.
Home widgets own independent channels—Notes, Tasks, Starred, Pages,
Projects, Categories, Ingress, and Tool Reports—so a change refreshes only its
consumer.

A loaded Page task list owns a periodic Tasks channel subscription. Its
`collection_revision` is independent of the Page fingerprint so Task Form
restriction/schema changes invalidate the list without changing the Page's
form revision. A collection refresh updates existing task rows in place while
a task in that list is open; it defers sort-order moves until the task closes
or a later refresh, so an autofill save does not move the form under the user.
An unchanged task order leaves the existing row elements mounted, preserving
hover and click continuity across a harmless refresh.
Task title clicks are handled by the view's delegated `lp-show` handler; the
task-list widget does not add a second click-driven toggle. The delegated open
event scrolls the task only when its newly opened form starts outside the
viewport. Explicit task focus navigation still scrolls its target into view.

Polling service startup also schedules widget subscription reconciliation.
A cached list can finish rendering before the deferred coordinator loads;
its render-time reconciliation cannot subscribe yet. Revisiting loaded widgets
when the coordinator becomes available prevents that ordering from permanently
losing the list's subscription. This background pass does not delay rendering.

`ToolReportList` owns a panel containing filter controls, empty-state messaging,
and a nested `ul[data-role="report-items"]`. Report rows expose `data-tool` and
`data-status`; filtering changes row visibility locally without dropping hidden
rows or their deferred-operation markers. Collection replacements preserve the
widget's selected categories and reapply counts and visibility. Its panel stays
visible when empty, so users can change filters after clearing executed reports.

Full-page saved Project filters subscribe to both their Filter/Project entity
revision and the Tasks channel. Both subscriptions run periodically while active.
Saved Category filters subscribe to their Filter/Category entity revision.
Their durable filter key and hash let `/l/refresh` recompute membership through
the saved filter cache. Restriction changes alter row fingerprints even when the
entity's modification timestamp is unchanged.
Only changed or newly visible rows need replacement HTML; unchanged authorized
rows keep their DOM. Temporary project status filters use the Tasks
channel but retain their complete focused route, including query parameters,
and fall back to replacing that collection from the route.

Star and delete are collection changes, not form revision changes. A committed
delete removes exact entity-key DOM nodes before collection and supplemental
navigation refresh.

## Deferred operations and form locks

An online deferred acknowledgement registers an opaque operation descriptor.
Server-rendered operation markers seed their current phase and revision; a
locally started operation requests an immediate check. The coordinator uses
adaptive backoff and rejects a status revision older than the one already
seen.

Operation markers may live on the view root (Report detail) or inside a loaded
widget (Home AI Reports). Startup checks both. All markers for one job share
one subscription and the newest observed status, including when a later HTML
fragment carries an older revision. Notifications have their own aggregate
cursor and focused list fetch; they do not subscribe to individual jobs.

A terminal HTML seed normally requests an immediate operation poll with a cursor
behind that revision. HTML presentation attributes do not contain the full
destination contract, so they cannot acknowledge completion. Task forms are an
exception when their HTML already includes the terminal autofill status and its
review candidate: that form state needs no additional operation poll or eager
form initialization. Closed task forms also do not subscribe to running
operations; opening one subscribes and checks immediately, while closing it
unsubscribes. Other terminal payloads advance the poll cursor only after
reconciliation succeeds; a failed replacement remains retryable at the same
revision. Pending report spinners remain until the report/list replacement
installs authoritative content.
Likewise, a successful autofill operation stays subscribed and displays a
loading-review message while its active form awaits the authoritative review
candidate; the operation is retired only after that candidate arrives. If a
remote-edit notice is already present in a tab, it takes precedence over the
running or temporary loading message. The autofill review notice can appear once
its candidate is ready. A newer running autofill, or its successful completion
still awaiting review values, temporarily hides an older completed autofill's
notice and Review values action. The newer candidate takes their place once it
arrives; an older candidate remains available if the newer run fails.

For subscribed jobs, terminal status causes `DeferredOperationManager` to locate
the declared source and destination and fetch authoritative replacement state.
It never applies model output from the poll payload. Destination identity
includes the mounted widget key where repeated widget names exist.

PageInfo and TaskForm also consume `form-lock`. A reload or another tab can
restore the active job and progress state even when the target fingerprint did
not change. The lock scope is retained as `data-operation-scope` before the
deferred manager starts, so its initial DOM scan uses the correct progress text:
form changes show
**Schema migration in progress**, while autofill keeps its own queued message.
Subsequent operation responses supply the current phase.
A focused remote-form response can also carry an active operation before that
tab observes a lock change. The reconciler registers this operation for polling
as well as displaying it, and keeps a newer local operation status if an older
response arrives later. A progress banner must not outlive its subscription.
Autofill uses `forms/reviewBar.mjs` inside the existing edited marker, without
disabling inputs or removing Submit. Only schema migration sets `deferredLock`.
An unresolved remote-edit notice can coexist with a running autofill; the bar
keeps both the review action and operation progress/Cancel visible.
`data-form-state` seeds the answer revision, current operation, typed migration
values and authorized AI candidates; `data-operation-bootstrap` seeds polling.
Once an ordinary save acknowledges the last successful autofill review, the
server omits that historical success from form operation bootstrap. The client
also suppresses its in-flight loading notice after a tab has used the review.
An autofill completion never automatically replaces an actively viewed form,
even when it is clean. The normal revision modal offers compatible values from
the tab, saved form, pre-migration schema and AI candidates. Stale modal choices
must be reopened before application. Prompt-only refinement is private until
the user chooses values and performs an ordinary save.
The modal includes fields changed by autofill even if those values have already
been saved. Ordinary autofill compares the value in this tab with the AI
suggestion, omitting a saved value that is merely the unchanged launch baseline
or duplicates either choice. A distinct saved edit made after launch remains a
third choice so no concurrent human change is hidden; if it matches the AI
suggestion, the saved card replaces the redundant AI card. Fields the AI left
unchanged are omitted unless their saved value changed after launch; in that
case an AI card duplicating the tab's unchanged value is omitted, leaving the
distinct saved value available. Tab drafts remain intact when other
suggestions are applied. If any saved answer changes after the autofill's
launch snapshot, the review defaults all proposal fields to the latest saved
value (or its identical tab value). An unsaved edit made in this tab still wins;
AI values remain available for explicit selection. This avoids preselecting an
AI result derived from stale context in another field.
When an autofill review has no changed fields, the modal states that no new
values were suggested, omits an empty choice grid, and offers **Keep current
values** to acknowledge the review before an ordinary Update.
The review's apply action has no idle completion icon; it shows a spinner and
disabled **Applying values…** state while resolving the selection. The
**Revise suggestions** action uses the AI icon in the button's fixed left icon
slot, with its label centered.
Opening Review values immediately disables its action and shows
**Opening review…** while the focused route verifies the latest saved values
and the comparison modal is prepared; the action returns to its normal state
when that work settles.
Retry keeps visible pending feedback until the start request resolves.
For a Task job owned by its parent Page, an unchanged Task entity poll still
checks the matching operation lock. This installs completion even if an earlier
poll already staged the saved values for review.

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
If the first menu click arrives during a pending connectivity recovery, loading
waits for that cycle to settle and then checks the view's current online state.
It does not discard the click based on the previous offline state or send a
request when the cycle finishes offline.

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
