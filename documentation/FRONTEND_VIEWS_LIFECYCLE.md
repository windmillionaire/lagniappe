# Frontend View Lifecycle

This guide covers startup, readiness, structural DOM commits, component
activation, and create/update requests. For server-state invalidation after the
view is mounted, read
[FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md).

## Startup boundaries

`main.mjs` finds `[lp-view]`, imports the matching stable entry from
`viewRegistry.mjs`, constructs it, and calls `init()`.

```text
DOMContentLoaded
  -> main.initialize()
  -> getView()
  -> ShellView.init()
       install delegated interaction and cold-control handlers
       publish interaction-ready
  -> concrete view prepares structural state
  -> view.publish()
       set initialized and _lp_view
       publish view-ready
  -> start root polling, visible prefetch, and document sync when present
  -> inspect storage and warm capability-gated services
  -> publish services-ready
```

Readiness markers name different boundaries:

| Boundary | Meaning |
| --- | --- |
| `data-interactive`, `lagniappe:interaction-ready` | Delegated input is protected and can lazy-load its owner. |
| `initialized`, `lagniappe:view-ready` | Structural view initialization is complete. |
| `lagniappe:services-ready` | Capability-gated private service warming completed. |
| `window.__CONNECTIVITY_READY__` | The latest background connectivity cycle settled. |
| navigation transition ready/settled globals | Cross-document visual transition observation only. |

Component rendering does not wait for storage inspection, offline replay,
Notifications, or optional managers. A direct consumer calls the matching
`ensure...()` method and shares its single-flight promise.

Cold controls prevent a native action when required, set `aria-busy`, import
their owner, and replay the intended action. A failed import clears the busy
and single-flight state so the next interaction can retry. Global Search keeps
its native GET submit available until `SearchBox` takes over.

## Transition policy

Cross-document navigation uses the CSS View Transition opt-in. In-page
structural changes use `withTransition()` with a synchronous callback.

Before that callback, finish:

- network requests;
- dynamic imports;
- widget activation;
- detached rendering; and
- any other awaited preparation.

The callback may only commit prepared connected-DOM changes. Calls made in the
same microtask join one browser transition and every callback runs once. If the
browser cannot run the transition, the same commits run directly.

Use transitions for noticeable geometry changes. Update progress text, editor
content/caret state, pointer-driven tables, and stable counters immediately.
Collection rows do not receive independent snapshots, and nav transitions do
not crossfade.

## Component navigation

`Core.renderComponent(trigger)` parses `componentId:widgetName` from `lp-show`
or `lp-close`.

- `active` reopens the selected widget or the default.
- `default` resolves the component's `data-default`.
- `nav` activates a standalone selector nav.
- `data-toggle="true"` hides an already-active target.

The view awaits `component.activate()` and `prepareRender()`, then calls
`component.render()` inside `withTransition()`. A trigger for an unloaded
`lp-load` or `lp-prefetch` widget carries `data-loading` and `aria-busy` until
preparation finishes.

At concrete view publication, components marked `lp-prefetch` start loading
their child widget targets marked the same way. The response is held for later
activation; prefetch does not make the widget visible.

## Submit routing

`SubmissionManager` owns the root `submit` handler. It:

1. resolves the containing `ViewComponent`;
2. collects `FormData` from all active widgets in that component;
3. appends the submitter's `data-role`; and
4. routes to POST for `lp-create` or PUT for `lp-update`.

If asynchronous preparation finishes after the original form or widget was
disconnected or deactivated, the submit is abandoned.

When offline, only a form marked `lp-offline` whose widget implements
`offline(context)` may queue. Other forms show `Server Offline` and do not send
a request. Deferred forms are online-only.

## Create

For an ordinary POST:

1. `request.post()` obtains the response;
2. source and destination widgets run `created()` and `prereconcile()` against
   detached/prepared state;
3. one transition commits source reset, destination content, component
   visibility, and nav; and
4. the response's entity revisions update local reconciliation baselines.

`data-destination="componentId:WidgetName"` names the receiving widget. Offline
create uses the same destination contract for optimistic rendering and leaves
the source in queued state.

A deferred create may return immediate destination HTML with `background:
true`; that HTML renders and the source resets while operation tracking
continues. Without destination HTML, the source shows its pending state until
the terminal operation refreshes the destination.

## Update

For an ordinary PUT, the active widget consumes response schema/submission or
component HTML, prepares its replacement, and commits replacement plus nav and
visibility in one transition. Unloaded widget targets may be replaced directly;
loaded widgets retain their instance and run their update contract.

An offline update stores the mutation and keeps the form in `Queued Sync`.
Successful replay triggers a fresh poll/EditWatcher pass; it does not directly
install the replay response as authoritative form state.

## Response envelope

`successfulResponse()` recognizes:

- `reload` for a full navigation reload;
- `error` for widget/component validation display;
- `modal` for returned modal HTML; and
- `html` for detached fragment parsing.

A deferred acknowledgement is handled separately from ordinary create/update
reconciliation. It marks the source successful as configured and registers the
opaque operation; terminal status later drives the authoritative destination
fetch.

## Destruction and navigation

`destroy()` removes root, media-query, document bootstrap, and temporary
pointer listeners, even when a lazy load is pending. Component/widget teardown
must remove owned listeners, observers, editor instances, Floating UI loops,
and polling subscriptions. Do not leave page-scoped work attached to globals
after navigation.
