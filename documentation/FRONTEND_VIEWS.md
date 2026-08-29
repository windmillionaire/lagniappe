# Frontend Views

The view system connects server-rendered Jinja HTML to browser behavior. Every
page has one view; views own components, components activate widgets, and
widgets own form fields, lists, tables, editors, and other leaf behavior.

```text
ShellView
  -> Core / Entity / EntityIndex (or a shell-only view)
       -> ViewComponent
            -> Widget
                 -> Elements
```

Read the focused guides for lifecycle and server-state behavior:

| Guide | Covers |
| --- | --- |
| [FRONTEND_VIEWS_LIFECYCLE.md](FRONTEND_VIEWS_LIFECYCLE.md) | Startup, readiness, transitions, component activation, and form submissions. |
| [FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md) | Polling, watched forms, collections, deferred operations, and notifications. |
| [FRONTEND_NAVIGATION.md](FRONTEND_NAVIGATION.md) | Template structure for components, widgets, nav, controls, and tabs. |
| [FRONTEND_TEMPLATES_ATTRIBUTES.md](FRONTEND_TEMPLATES_ATTRIBUTES.md) | Canonical `lp-*` and frontend-consumed `data-*` attributes. |

## ShellView

`views/base/shell.mjs` installs the synchronous page shell. Before awaiting
feature code, storage, or network work, it installs delegated click, submit,
pointer, responsive-breakpoint, and cold-control handlers and publishes
`data-interactive="true"`.

Concrete views call `publish()` after structural initialization. Publication
sets `initialized`, stores `_lp_view`, and records `lagniappe:view-ready`.
Optional private services become ready later. Manual, Results, and Analytics
can use the shell without the component and authenticated-service stack.
The shell also delegates copy controls for the Manual command-block component,
so its padded, scrollable, copyable presentation can be reused in views such as
Admin without view-specific clipboard code.

## Core

`views/base/core.mjs` adds components and private application services. It owns:

- delegated control and `lp-show` routing;
- lazy component creation;
- create/update/load request flows;
- prefetch;
- modal and entity-menu loaders;
- service façades for polling, document sync, offline replay, watched forms,
  deferred operations, and Notifications; and
- collection and entity reconciliation.

`Core` reads `data-kind`, `data-hash`, `data-key`, and `data-readonly` from the
root. Lazy managers are obtained through idempotent `ensure...()` methods or
their readiness promises. Do not assume a manager exists merely because the
view is interactive.

Controls are delegated from the view root. `lp-control` handles help, star,
delete, pagination, close, and routed component controls; `lp-show` navigates
between widgets; `lp-link` forwards a row click to its title link. Local widget
behavior such as table expansion stays with the widget instead of growing the
Core switch.

## Entity views

`views/base/entity.mjs` extends Core for Page, Project, and File detail pages.
It owns:

- tab components marked `data-tab="true"`;
- active-tab persistence keyed by the entity hash;
- the shared mobile tab navigation; and
- moving secondary cards between desktop and mobile layouts.

Initial tab selection and later responsive changes prepare their state before
one synchronous commit. Empty readonly document tabs are omitted; editors and
saved documents retain the document surface.

## Entity indexes

`views/base/index.mjs` extends Core for User, Form, Category, and Task indexes.
It owns the tools component, inline table editing, and mobile controls.

Large tables have two readiness stages. `TableVisibilityState` applies saved
column visibility before first paint. The interactive checkbox panel and
sorting controls remain lazy; sorting appears only after chained row loading
and `TableSorting` initialization complete.

## Specialized views

The Form Builder owns an unsaved local schema and does not extend Core. It still
implements the shared connectivity `sync()` lifecycle. See
[FRONTEND_BUILDER.md](FRONTEND_BUILDER.md).

Manual imports its section dropdown only in mobile mode. Report initializes
forms only when present. Page activates its photo widget only when the card is
visible or selected. These optimizations preserve the same published view and
widget contracts.

## ViewComponent

`views/base/component.mjs` manages one `[lp-component]` element.

| State | Meaning |
| --- | --- |
| `active` | Current widget or standalone nav. |
| `widgets` | Loaded widgets by name. |
| `visible` | Current component visibility. |
| `persistent` | Remains visible when inactive. |
| `nav` | Associated `NavElement`. |

`activate(name)` disables the prior widget, resolves `default`, `active`, or
`nav`, lazy-loads the requested widget, follows its `lp-load` route when needed,
applies `data-if-empty`, and enables it. Network and initialization work finish
before `render()` commits component, widget, and nav visibility.

`updated(response)` prepares a component or widget replacement after PUT.
`created(response)` resolves the source widget's `data-destination` after POST.
Both return prepared work to the view transition boundary. Nested components
deactivate siblings and inherit the parent nav where needed.

Loaded collection widgets opt in with `refreshScope = "collection"`.
`prepareCollectionRefresh()` resolves data and detached DOM first;
`refreshCollections()` commits all prepared changes together. Forms are never
generic collection refresh targets.

## Widget contract

`widgets/loader.mjs` maps `data-widget` names to lazy imports and caches one
instance per component. Unknown names receive `DefaultWidget`, which provides
only visibility and configuration for simple show/hide targets.

The loader provides `enable()`, `disable()`, and synchronous `reconcile()`.
Widgets implement only the members they need:

| Member | Purpose |
| --- | --- |
| `init()` | One-time asynchronous setup. |
| `updated(response)` / `created(response)` | Prepare server response state. |
| `prereconcile()` | Finish imports, detached rendering, or data work. |
| `postreconcile()` | Commit connected-DOM work synchronously. |
| `data` | Contribute `FormData` to the component. |
| `showError(message)` | Present a validation error. |
| `destroy()` | Remove listeners and owned resources. |

Loader settings come from the widget target, component, and view: key, kind,
readonly, visibility, persistence, endpoint registry, and parsed JSON values
such as schema, submission, conditions, columns, selected, preload, and options.

Most behavioral widgets extend `FormElement`, `BaseList`, `BaseTable`, or
`BaseUpload`. See [FRONTEND_FORMS.md](FRONTEND_FORMS.md) and
[FRONTEND_ELEMENTS.md](FRONTEND_ELEMENTS.md).

## Change rules

- Install interaction handlers before awaited startup work.
- Keep network, imports, rendering preparation, and storage reads outside the
  synchronous DOM commit.
- Put feature behavior in the narrowest widget or manager that owns it.
- Use public `lp-*` / `data-*` contracts for template integration.
- Reconcile forms, collections, documents, and deferred jobs through their
  distinct authorities instead of a general refresh shortcut.
