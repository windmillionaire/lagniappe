# Frontend Views

The view system is how the frontend connects server-rendered HTML to client-side behavior. The architecture has five layers:

```
ShellView
  └── View (Core / Entity / EntityIndex, or a shell-only view)
        └── Component (ViewComponent)
              └── Widget (loaded via loader.mjs)
                    └── Elements (form fields, tables, etc.)
```

Every page has one **view**. `ShellView` owns the synchronous interaction and
publication lifecycle. `Core` adds components and private application services;
Manual, Results, and Analytics stay shell-only. Components display one active
**widget** at a time, and widgets own the actual UI behavior.

## ShellView (`views/base/shell.mjs`)

`ShellView.init()` is the first synchronous startup boundary. Before it awaits
feature code, storage, or network work, it installs delegated click, submit,
pointer-down, mobile-breakpoint, and cold-control handlers, sets
`data-interactive="true"`, and records `lagniappe:interaction-ready`.

Pointer tracking is installed on `window` only between pointer-down and
pointer-up/cancel. Movement greater than five pixels suppresses the next click.
`destroy()` removes the root, media-query, document bootstrap, and temporary
pointer listeners, including when a lazy load is still pending.

Concrete views call `publish()` only after their structural `init()` completes.
Publication sets the existing `initialized` attribute and `_lp_view` handle,
then records `lagniappe:view-ready`. Optional/private service completion records
`lagniappe:services-ready` afterward. Public Manual uses the same focused shell
behavior but does not install private polling, offline, sync, notification, or
authenticated lifecycle work.

## Core (`views/base/core.mjs`)

Component-capable base class for Home, entity/detail views, indexes, Report, and
Admin. `getView()` creates it through the stable entry in `viewRegistry.mjs`.

### Constructor

Reads `data-kind`, `data-hash`, `data-key`, and `data-readonly` from the root
element. Initializes the component map and stable manager handles without
importing or constructing the managers themselves.

The PascalCase instance fields in `Core` (`SyncManager`, `EditWatcher`,
`SubmissionManager`, `DeferredOperations`, `Notifications`, and the other
manager/widget handles) remain public compatibility handles. Lower-camel fields
such as `offlineQueue` remain internal state. Consumers that require a lazy
manager must await its readiness promise or call the corresponding idempotent
`ensure…()` method; reading a handle directly is valid only after that point.

### Initialization (`init()`)

- Runs `ShellView.init()` immediately, then installs the stable readiness
  promises `offlineQueueReady`, `syncReady`, `initialReplayReady`, and
  `servicesReady`.
- At concrete view publication, starts PollingCoordinator and existing
  `[lp-prefetch]` work. SyncManager starts when a document capability exists;
  idle storage inspection starts SyncManager or OfflineQueue only for persisted
  work. Prefetch and ordinary GET rendering never wait for or inspect
  OfflineQueue. The offline modal loads on first use.
- During idle time (one-second maximum), starts correctness-sensitive
  Notifications, DeferredOperationManager, and EditWatcher only when matching
  DOM capabilities exist. SearchBox, EntityMenu, and modal UI load on first
  interaction through the same single-flight `ensure…()` loaders.
- Registers the root entity or collection subscription when the polling
  coordinator becomes ready. Entity/form-lock checks are periodic with their
  first request after 15 seconds; index collections are foreground-only and do
  not install a timer. Documents await `syncReady` and poll immediately while
  active. Offline forms render authoritative server state without touching
  queue readiness. Initial replay waits for view readiness; successful writes
  trigger an immediate poll when their form is mounted, using normal
  EditWatcher reconciliation.
- Keeps offline replay, reconnect reconciliation, polling batching, edit
  notices, deferred operations, and notification delivery behind the lazy
  service facades in `views/base/services.mjs`.

Cold controls synchronously prevent native navigation/submission when needed,
set `aria-busy`, and coalesce repeated activation. The intended operation is
replayed after its chunk resolves. A failed chunk clears the single-flight and
busy state so the next interaction retries.

### Click Delegation (`_click()`)

All clicks within the view bubble up to a single handler that checks for
control and navigation attributes:

| Attribute | Action |
|---|---|
| `[lp-menu] [data-role="menu-trigger"]` | Opens the view-scoped entity action menu |
| `data-role="flipper"` | Toggles `data-flipped` on the nearest `[data-flipped]` ancestor |
| `lp-control="help"` | Opens a help modal using `lp-help` |
| `lp-control="star"` | Toggles star via PATCH request |
| `lp-control="delete"` | Opens a delete confirmation modal using nearby entity context |
| `lp-control="previous"` / `lp-control="next"` | Fetches paginated list content for the current widget |
| Other `lp-control` values | Route through `renderComponent()` using `lp-show` or `lp-close` |
| `[lp-show]` | Routes to `renderComponent()` |
| `[lp-link]` | Clicks the `[data-role="title"]` child (makes rows act as links) |

`data-role="expand"` is local widget/table behavior rather than Core control
behavior. Table bodies own embedded table-cell expansion through `BaseTable`;
page task lists own their buttons directly. `SiteSettings` is a small composite
coordinator: it owns the shared section headers and persisted accordion state,
loads each persistent section body as a focused widget through its existing
component, and forwards the aggregate settings response for normal widget
reconciliation.

Title action menus are declared with the macros in `templates/menus.html`.
`menus.title()` supplies the trigger and hidden source items, while
`menus.show()` and `menus.delete()` attach ordinary delegated controls such as
`lp-show` and `lp-control="delete"`. `EntityMenu` renders the visible,
positioned menu at the document level and forwards a selection to its
connected source item, so menu operations continue to use the same view
routing as controls elsewhere in the template. Entity roots that offer
deletion must carry `lp-entity` and a `data-key`; a title-level Delete item can
set `data-return-url` so the modal returns to a safe page after deleting the
entity currently being viewed.

Delete confirmations may include named checkbox options marked with
`data-delete-option`. `DeleteModal` sends their checked states as JSON booleans
with the DELETE request; confirmations without options keep the existing
bodyless request behavior.

Notes use the shared `CreateNote` widget on Home and Pages. The textarea stays
available while the native image chooser is open, so a submission may contain
text, one photo, or both. The widget owns the selected-photo preview/removal
state and resets it after creation. Home note creation is available to signed-in
users and defaults to private; only users with `SITE:EDIT` (the site owner) see
the “Show for everyone” option. Home keeps its existing offline-create contract.
The Page title menu opens an online-only composer beneath the title for users
who can edit that Page, with both visibility options unchanged, while a
persistent `BaseList` keeps existing Page notes visible. Persisted note controls
use the normal `DeleteModal`; only an unsynced optimistic Home note uses the
local “Discard pending note” action.

### Submit Handling (`SubmissionManager`)

Core delegates the root `submit` event to its view-scoped `SubmissionManager`.
`Core.create()`, `Core.update()`, and `Core.successfulResponse()` remain stable
facades for widgets and subclasses.

1. Finds the nearest `[lp-component]` ancestor of the form
2. Gets or creates the `ViewComponent` for that element
3. Collects `FormData` from all active widgets via `component.formData`
4. Appends the submitter's `data-role` to the form data
5. Routes to `create()` if the active widget has `lp-create`, or `update()` if `lp-update`

If a widget performs asynchronous submit preparation such as direct uploads,
`SubmissionManager.submit()` abandons the submit when that original widget or
form is no longer active and connected by the time preparation finishes.

When the view is offline, `Core.create()` and `Core.update()` do not send
network requests. They delegate to `OfflineQueue.queueSubmit()` only when
the active widget's form has `lp-offline` and the widget implements
`offline(context)`. Forms without that opt-in stay disabled through
`BaseForm` with the offline icon and `Server Offline`.

Forms with `lp-deferred` are online-only async submits. `Core.create()` and
`Core.update()` send them normally, but a `{deferred: true}` response marks the
source form successful without running ordinary create/update reconciliation.
The acknowledgement includes an opaque operation reference. The AI Tools
create form declares `data-deferred-status="false"`, so the coordinator tracks
its operation without ever decorating that source form. Status is presented by
the destination report-list item and the pending/completed notification. The
shared polling coordinator includes operation descriptors in its bounded
`POST /l/poll` batch. The owner-authorized result carries the current durable
status revision and applies jittered backoff from roughly four to 30 seconds.
Each descriptor retains only that operation's last-seen status revision. A
matching, recently durable-verified Redis projection lets the server
acknowledge a quiet owner operation without reading its job row; at least once
per minute, or after a miss/mismatch, it reloads the durable job and repairs the
projection. Redis operation and notification state use separate keys but are
read in one pipeline when the same poll needs both.
Polling pauses while the tab is hidden, the window is unfocused, or the view is
offline. A server-rendered operation seeds its revision and schedules its
first request four seconds later. Its bounded current status is rendered into
the operation element and hydrated into the manager cache, so a matching quiet
check can skip the job row without leaving a stale phase label. An operation
started by this browser nudges its own descriptor immediately. Focus/visibility/connectivity runs one batched
catch-up, keeps elapsed time moving between responses, and displays a delayed
status/retry message instead of an indefinite silent spinner when a status
check fails.

The operation subscription is the authoritative completion mechanism. The
coordinator rejects stale revisions before refreshing the form's
`data-destination` widget. When several widgets share a name (for example, page
task forms), the destination is also part of source matching. A source can
provide `data-deferred-route` when completion needs a purpose-built replacement
endpoint instead of the widget's normal submit route. Report rows use this
coordinator for operation status. The lazy-loaded report list registers
operation markers after every reconciliation, including after a server refresh
replaces the list, so its phase/recovery text comes from the same status response
as report detail. A small report-list refresh still keeps domain fields such as
the saved report summary current.

The report detail's revision and **Execute Proposal** forms use the same
operation contract directly. Execution immediately changes the detail to a
saving state, decorates it with the returned operation reference, and reloads
authoritative report/result HTML when polling observes a terminal job.
Retrying a partially applied proposal follows the same path and resumes from
the report's server-side action ledger.

### Request Lifecycle

**`successfulResponse(response, component)`** -- central response handler used by both `create()` and `update()`:

- `response.reload` → full page reload
- `response.error` → calls `component.showError()`
- `response.modal` → attaches a modal with the response HTML
- `response.html` → parses the HTML string into a document for widget consumption

**`update(component, data)`** -- sends PUT, then calls `component.updated(response)` inside a view transition. Deferred acknowledgements instead show the pending notification and mark the active subform successful. Offline `lp-offline` updates are queued and keep the form in `Queued Sync` state until replay.

**`create(component, data)`** -- sends POST, then calls `component.created(response)` inside a view transition. Offline `lp-offline` creates use the same mutation queue and optimistic destination rendering. Online `lp-deferred` creates stop after the deferred acknowledgement and wait for their operation subscription to refresh the destination.

**`load(component)`** -- sends GET (or uses a prefetched response from `window._prefetch`). Used for lazy-loading widget content.

### Committed Edit Notices

Durable server-rendered `[lp-entity]` anchors carry `data-key`,
`data-fingerprint`, and (for Page/Task form reconciliation) `data-modified`. A
watched form contains an `lp-edited-marker`; it does not repeat those
attributes. `EditWatcher` walks from each marker to its nearest entity anchor
and retains that marker's own fingerprint/modified baseline. It deduplicates
active visible markers by key and installs `entity`/`form-lock` subscriptions
with the shared polling coordinator. A root marker shares Core's `view:entity`
subscription. Missing, inaccessible, or fingerprint-changed entities trigger a
focused probe only for active stale forms through `data-edited-route`.

The collector starts from markers; it never enumerates every `lp-entity` in the
view. `Core.reconcileChange()` can invalidate specific watched entity keys from
a changed poll result. Unmarked list and table rows remain
exclusively under the collection refresh flow. If foregrounding or a manual trigger overlaps an
in-flight poll, the triggers share one promise and run one follow-up pass after
the current snapshot completes so a just-committed revision is not deferred to
the next polling interval. Focused replacement probes use the same rule per
marker and revision: identical overlap shares the active request, while one
genuinely newer revision may run afterward. A later unchanged response cannot
supersede an earlier authoritative replacement.

The probe renders detached previews and compares normalized form state with the
live widget's committed baseline and current inputs. An inactive watched form
does not poll or remount. Its retained marker baseline is compared with the
newest root/entity revision on activation, at which point it performs one
catch-up probe if stale. A component's visible active widget is protected even
when clean, and a form with focus remains protected before an input or change
event fires. A protected form only gets the field-by-field reconciliation UI
when both revisions expose a renderer, a non-empty schema, and structured
submissions. Schema drift projects stable local field IDs into the latest
schema. A changed fingerprint with an unchanged entity `data-modified` stamp is
a schema-only revision: EditWatcher applies the latest schema, keeps compatible
local values, and shows the schema-update notice. When both stamps change,
actual renderer value differences show
**Review values** with saved values selected by default.

Dirty non-renderer forms instead show an inline **Reset form** notice. A queued
non-renderer mutation offers one compact whole-form choice between the queued
version and the saved version. Equal revisions apply automatically, and the
field modal is never opened with zero differences. Missing, inaccessible, or
unsafe replacements use **Reload page**. A local response acknowledgement does
not probe or remount forms because that response has already reconciled its
component. External polling invalidation performs the authoritative
reconciliation. The terminal result of a form's own deferred operation is the
narrow exception to active-widget protection: it applies automatically only
when the operation identity matches the form lock and the form has no unsaved
or queued state. A deferred destination also contributes its mounted widget
key, so nested task forms are invalidated even when the operation itself is
owned by the surrounding page.

Collection widgets explicitly opt into generic refresh with
`refreshScope = "collection"`. `Core.refreshCollections()` batches supported
table/list manifests and falls back to their normal GET routes; forms are never
generic refresh targets. It does not refresh the notification list. Index roots
carry a raw `data-fingerprint` for `/l/refresh` and separate
`data-poll-channel`/`data-poll-revision` attributes for the opaque collection
cursor, preventing raw-versus-opaque false changes. Index collection channels
have no idle timer and invoke `/l/refresh` only after a changed foreground
catch-up result. Active visible, dirty, queued, and staged-review task
rows are also protected from collection replacement, so the parent Page refresh
cannot replace a TaskForm before its entity revision is reviewed. Hidden clean
task forms still refresh silently. When a changed entity is already rendered
inside a collection whose widget has not been instantiated, Core loads that
collection owner before refreshing it. Delete and star changes remain
collection-only and are not sent through form reconciliation. A committed
delete removes elements with that exact entity key before collection and
supplemental-navigation refresh, allowing non-collection selectors to reconcile
without restoring widget-specific message handlers.

The same `/l/poll` batch independently carries active durable `form-lock`
results. PageInfo and TaskForm reconstruct their lock/progress state from those
results on reload or in another tab even when their committed fingerprint is
unchanged. This recovery does not register the form with `SyncManager`.

Successful entity mutation responses carry `X-Lagniappe-Entity-Revisions` with
both fingerprint and modified stamp; the request wrapper exposes
`response.entities` and normally dispatches acknowledgements. Revision probes
suppress that event until comparison is complete. A response may acknowledge
both the direct entity and owners whose fingerprints advanced. Notices remain
separate from the notification menu and from document collaboration. PageInfo,
TaskForm, TaskSettings, and CategoryInfo use focused edit markers; TaskMove and
TaskCombine remain action forms and are deliberately excluded.

The notification badge is driven by `X-Lagniappe-Notification-State`, parsed by
the initial/focus/ten-minute `/l/ping` and by the shared request wrapper. The
header contains only Redis generation, revision, and count. The menu module can
therefore initialize lazily without fetching `/l/notifications`: its first open
loads the list, a changed cursor marks an already-loaded list stale, and a stale
list refreshes immediately only when the menu is open. Create/delete/clear
responses carry the resulting state so the originating tab updates its badge
without waiting for another poll.

Home does not use the composite collection subscription for current clients.
Server-rendered Notes is marked loaded and owns `home-notes`; Tasks retains its
single prefetch and owns `tasks`. Starred and the lazy Pages, Projects,
Categories, Ingress, and Tool Reports widgets acquire their own foreground
channel only after loading. A changed result fetches and refreshes only that
channel's widget.

### `renderComponent(trigger)`

Parses a `componentId:widgetName` pair from `lp-show` or `lp-close` attributes. Handles special values:

- `"active"` → re-shows the currently active widget
- `"default"` → shows the component's `data-default` widget
- Toggle behavior (`data-toggle="true"`) → hides the widget if it's already showing

Calls `component.activate(widgetName)` then `component.render()` inside a view transition.
If the requested widget target exists, is not yet `loaded`, and has `lp-load`
or `lp-prefetch`, the clicked trigger gets `data-loading="true"` and
`aria-busy="true"` until activation and rendering finish. Templates can use
that trigger state for lightweight loading indicators.

### Component Access (`getComponent()`)

Lazily creates `ViewComponent` instances. Components are cached by ID on the view and stored as `element._lp_component` on their DOM node.

### Prefetch

On init, finds `[lp-component][lp-prefetch]` components and asks each component
to prefetch its `[data-widget][lp-prefetch]` children. The activated widget's
response is resolved from `window._prefetch` when available. The component's
`active` is then cleared so the widget does not appear until the user requests
it.

## Entity (`views/base/entity.mjs`)

Extends Core for entity detail pages (project, page, file). Adds:

- **Tab management**: Components with `data-tab="true"` are treated as tabs. The active tab is persisted in `localStorage` keyed by `data-hash`. On mobile, all tabs collapse into a shared container with a unified mobile nav. Page and project document tabs are rendered for editors or when saved document content exists, so readonly viewers do not see empty document affordances.
- **Mobile layout**: Listens for `mobile-resize` events. On mobile, moves secondary card components into the tabs container and shows a shared `mobileNav`. On desktop, restores the original layout.

Initial entity tab selection and active widget initialization stay together in
one atomic transition. The transition contains only structural/widget work;
polling, offline replay, and other deferred services begin after publication.
Later tab, secondary-card, and responsive layout changes use the same path.

Views extending Entity: `project.mjs`, `page.mjs`, `file.mjs`.

## EntityIndex (`views/base/index.mjs`)

Extends Core for list/index pages (users, forms, categories, tasks). Adds:

- **Tools panel**: A component for create/edit/settings widgets
- **Table editing**: Inline edit support via table widgets
- **Mobile controls**: Compact controls for mobile table views

Large index tables deliberately have two readiness stages. The lightweight
`TableVisibilityState` reads saved columns and installs visibility CSS before
the first table render. The checkbox panel stays in the lazy `TableVisibility`
widget. Chained row loading remains asynchronous and does not block those
surfaces. Sorting/filter buttons start hidden and become available only after
`IndexTable` finishes the chained load and initializes `TableSorting`; opening
mobile controls can retarget already-initialized sorting state but never starts
or awaits that row load. The tools `Dropdown` is imported only on mobile or
after a later resize into mobile mode.

Views using EntityIndex: user, form, category, task (all mapped to `views/base/index`).

## Form Builder (`views/builder/builder.mjs`)

The form builder is the one specialized view that does not extend `Core`.
Its model, settings, conditions, and preview panels operate on an unsaved local
schema rather than `ViewComponent` widgets. It still implements the shared
`sync()` lifecycle used by `main.mjs`, reading the canonical connectivity state
to keep its search, save control, and offline indicator current. It does not
publish separate global offline state.

## Startup-sensitive view behavior

- Manual imports its section dropdown only in mobile mode or after a mobile
  resize. Desktop Manual retains AJAX section navigation and copy controls
  without the combobox chunk.
- Page activates `PagePhoto` only when the photo card is initially visible or
  selected. A hidden card uses normal component activation on first use.
- Report imports `BaseForm` only when a report form exists, then initializes
  run/retry, undo, and revise forms concurrently.
- Home, table, note, and other `[lp-prefetch]` widgets start at concrete view
  publication. OfflineQueue hydration and replay run separately and reconcile
  successful late writes through polling/EditWatcher.

## ViewComponent (`views/base/component.mjs`)

Manages the widget lifecycle within a component. A component is a `[lp-component]` DOM element with an `id`, and it can contain multiple widget targets (`[data-widget]`).

### State

| Property | Description |
|---|---|
| `active` | Currently active widget instance (or null) |
| `widgets` | Map of loaded widget instances keyed by name |
| `visible` | Whether the component is visible (`data-visible`) |
| `persistent` | If true, stays visible when deactivated |
| `nav` | Associated `NavElement` instance |

### `activate(widgetName)`

1. Disables the previously active widget
2. If `widgetName` is null, deactivates entirely
3. If `widgetName` is `"default"` or `"active"`, resolves to `data-default`
4. If `widgetName` is `"nav"` and the nav is standalone, activates the nav itself
5. Otherwise, loads the widget (via `loadWidget()`) if not already cached
6. If the widget has `lp-load`, triggers `this.load()` to fetch server data
7. If the widget has zero items and `data-if-empty` is set, switches to that widget instead
8. Calls `widget.enable()`

### `load()`

Delegates to `view.load(this)` to fetch data. Passes the response to `active.updated()`. If the response contains a new `[lp-load]` element with a different route, recursively loads again (paginated/chained loading).

### `refreshCollections()`

Refreshes loaded widgets only when they declare `refreshScope = "collection"`.
Widgets already reconciled by the batched `/l/refresh` manifest are skipped;
remaining collection widgets use their normal GET/`refresh()` path. Form widgets
are outside this contract and are reconciled by `EditWatcher`.

### `updated(response)`

Called after a successful PUT. Finds the component's own element in the response HTML:

- If found, replaces the entire component element (full refresh)
- If not found, iterates `[data-widget]` elements in the response and either calls `widget.updated()` on loaded widgets or replaces unloaded widget targets in-place

Sets `this.reconcile` to a function that performs the actual DOM mutations, called later during `render()`.

### `created(response)`

Called after a successful POST. Reads `data-destination` from the active widget to find the receiving component and widget. Activates the receiver, then calls `render()` on both the source and destination components.

### `render(visible)`

The reconciliation entry point. User-initiated component changes and initial
entity enhancement are called inside a `withTransition()`:

1. Runs `this.reconcile()` if set (deferred DOM mutations from `updated`/`created`)
2. Sets `data-visible` and `data-open` on the component element
3. Calls `_setParentComponent()` to manage sub-component visibility
4. Iterates all widgets and calls `widget.reconcile()` on each
5. Updates the nav bar
6. Schedules polling subscription ownership reconciliation as a coalesced
   background task; rendering never waits for manager or poll work

### Data Aggregation

The `data` getter collects `FormData` from all loaded widgets that provide it, merges them into a single `FormData`, and appends the names of all active widgets. This merged data is what gets submitted via create/update.

Page-task moves and combines are intentionally isolated from ordinary task
settings. `TaskMove` submits only its page selector to the dedicated task move
route, while `TaskCombine` submits only the compatible-task checkboxes to its
combine route. This permits either action on a completed task while its settings
and attached form stay readonly. The combine form is loaded on demand and
refreshed whenever it is reopened so its candidates do not go stale.

A successful combine response uses the same task-list delta shape as page-task
refresh: one survivor upsert, loser keys to remove, and the authoritative page
order. The task component closes the combine form and passes that delta to
`PageTaskList.refreshDelta()`, which updates the active/completed lists without
a page reload.

### Parent/Sub-Component Relationships

Components can be nested. When a sub-component activates, `_setParentComponent()`:

- Deactivates sibling sub-components
- Shares the parent's nav bar if the sub-component doesn't have its own
- Dispatches a `set-subcomponent` event

## Widget System (`widgets/loader.mjs`)

Widgets are the leaf-level UI units. They're lazily loaded when first activated and cached on their component.

### Widget Contract

The loader provides default implementations of `enable()`, `disable()`, and `reconcile()`. Widgets only need to implement what they actually use.

**Provided by the loader:**

| Method | Behavior |
|---|---|
| `enable()` | Sets `this.visible = true`, marks `modified` |
| `disable(force)` | Sets `this.visible = false`, marks `modified` |
| `reconcile(silent)` | If `modified`, syncs `this.visible` to `target.dataset.visible` (skipped if persistent), then calls `postreconcile()` |

**Implemented by widgets (all optional):**

| Member | Type | Purpose |
|---|---|---|
| `init()` | async fn | One-time setup after instantiation |
| `updated(response)` | fn | Handle server response after PUT |
| `created(response)` | fn | Handle post-create (e.g. reset a form) |
| `postreconcile()` | async fn | DOM manipulation after visibility is synced (runs inside the transition) |
| `data` | FormData getter | Data to include in form submissions |
| `showError(msg)` | fn | Display a validation error. Falls back to the component-level `showError()` if not defined. |
| `destroy()` | fn | Cleanup listeners, teardown |

### Widget Attributes

When a widget is loaded, the loader extracts configuration from the widget's target element:

| Extracted | Source |
|---|---|
| `component`, `view` | Parent references |
| `name` | The `data-widget` value |
| `target` | The DOM element with `data-widget` |
| `key` | `target.data-key` → `component.key` → `view.key` |
| `kind` | `target.data-kind` → `component.kind` → `"default"` |
| `visible` | `target.data-visible` |
| `persistent` | `target.data-persistent` |
| `readonly` | Inherited from component |
| `endpoints` | Looked up from `ENDPOINTS[widgetName]` if defined |
| JSON attributes | `attributes`, `submission`, `schema`, `conditions`, `columns`, `selected`, `preload`, `options` -- auto-parsed from `data-*` attributes |

### Widget Registry

The `WIDGETS` map in `loader.mjs` connects widget names to their module imports. If a widget name isn't in the registry, a `DefaultWidget` is created -- a no-op widget that just holds the attributes. This is useful for simple show/hide targets that don't need behavior.

### Widget Base Classes

Most widgets extend one of these base classes rather than starting from scratch:

| Base | Used For | Key Features |
|---|---|---|
| `FormElement` (`elements/form.mjs`) | Settings forms, create forms | Form rendering, validation, error display, reset |
| `BaseList` (`elements/base/baseList.mjs`) | Task lists, starred lists | List item management, created/updated reconciliation |
| `BaseTable` (`elements/base/baseTable.mjs`) | Index tables | Column management, row rendering, sorting integration |
| `BaseUpload` (`elements/base/baseUpload.mjs`) | File uploads | Drag-and-drop, file validation, upload progress |

## Lifecycle Summary

### Page Load

```
DOMContentLoaded
  → main.mjs: initialize()
    → setTestMode()
    → getView()
      → find [lp-view], import its stable entry from viewRegistry.mjs
      → new View(node), view.init()
        → ShellView.init(): install handlers; mark interaction-ready
        → concrete view: finish structural initialization
        → publish initialized/_lp_view; mark view-ready
        → at view-ready: start root polling, document sync when present, and
          visible prefetch
        → idle: inspect for persisted offline work and start only the matching
          queue/sync manager; warm correctness-sensitive managers
        → first use: optional controls and UI managers
        → mark services-ready
        → CollaborativeDocument renders its editor shell immediately, then hydrates
          through initialStateReady; FormElement renders before offline replay
    → all pages: register the service worker immediately
    → private pages: start session updates, health lifecycle, and analytics
      without a paint gate
    → public pages: analytics/error handling only beyond the service worker;
      no authenticated lifecycle registration
```

### User Clicks a Toggle

```
click [lp-show="tools:CreateUser"]
  → Core._click()
    → Core.renderComponent(button)
      → component.activate("CreateUser")
        → loadWidget(component, "CreateUser")  [first time only]
        → widget.enable()
      → withTransition()
        → component.render(true)
          → set data-visible, data-open
          → all widgets: reconcile()
          → nav.reconcile()
```

### User Submits a Create Form

```
submit
  → SubmissionManager.submit()
    → component.data  [merges FormData from all widgets]
    → Core.create(component, data)
      → request.post(component.route, data)
      → successfulResponse(response)
      → withTransition()
        → component.created(response)
          → active.created()           [reset the form]
          → activate destination widget
          → destination.created(response)
          → render both components
```

### User Submits an Update Form

```
submit
  → SubmissionManager.submit()
    → component.data
    → Core.update(component, data)
      → request.put(component.route, data)
      → successfulResponse(response)
      → withTransition()
        → component.updated(response)
          → match [data-widget] elements in response HTML
          → widget.updated(response) for loaded widgets
          → replace targets for unloaded widgets
          → reconcile all, update nav
```
