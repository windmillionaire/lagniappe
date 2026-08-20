# Template Attributes

The `lp-*` attributes are the handshake between server-rendered Jinja
templates and the frontend. Templates write ordinary HTML with stable
`lp-*` markers, and the browser code reacts to those markers after
`main.mjs` initializes the page.

Think of an `lp-*` attribute as the opt-in signal and the neighboring
`data-*` attributes as the configuration and mutable state. For example,
`lp-component` says "this element is a frontend component"; `id`,
`data-default`, `data-visible`, `data-route`, and child `data-widget`
attributes tell the component what to show and where to fetch or submit.

For deeper references, see [FRONTEND_OVERVIEW.md](FRONTEND_OVERVIEW.md) for
entry points, [FRONTEND_VIEWS.md](FRONTEND_VIEWS.md) for the view/component
lifecycle, [FRONTEND_NAVIGATION.md](FRONTEND_NAVIGATION.md) for template
navigation authoring, [FRONTEND_ELEMENTS.md](FRONTEND_ELEMENTS.md) and
[FRONTEND_COMBOBOX.md](FRONTEND_COMBOBOX.md) for form fields and comboboxes,
and [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md) for collaborative state.

## Mental Model

The usual page shape is:

```html
<div lp-view lp-entity
     data-kind="page"
     data-key="{{ page.urlsafe_key }}"
     data-fingerprint="{{ page.fingerprint }}">
  <div id="tools" lp-component data-default="CreatePage">
    <div lp-nav data-nav="tools">
      <span data-role="title"></span>
      <div data-role="controls"></div>
    </div>

    <form data-widget="CreatePage"
          data-route="{{ url_for('pages.create') }}"
          data-destination="table:IndexTable"
          lp-create>
      ...
    </form>
  </div>
</div>
```

The flow is:

1. `main.mjs` finds `[lp-view]`, reads `data-kind`, imports the matching view,
   and calls `init()`.
2. The view delegates clicks and submits from the root. It creates
   `ViewComponent` instances from `[lp-component]` elements as needed.
3. Components activate child widgets by `data-widget` name. Widget targets can
   opt into loading, submits, offline queueing, deferred work, or sync with
   additional `lp-*` attributes.
4. `NavElement` reconciles titles, toggle buttons, and controls from the
   active widget's `data-*` settings.

The frontend mutates several `data-*` attributes during reconciliation,
especially `data-visible`, `data-open`, `data-selected`, `data-active`, and
`data-readonly`. Treat these as live UI state after hydration.

## Reference

| Attribute | Usual element | What it opts into | Related attributes and data |
|---|---|---|---|
| `lp-view` | Page root | Initializes the JS view. | Requires `data-kind` matching the view registry. Common: `data-key`, `data-hash` or `data-index`, `data-readonly`. |
| `lp-entity` | Entity view root, rows, list items | Marks entity-scoped DOM for entity views, list reconciliation, star/delete invalidation, and row replacement. | Durable entities carry `data-key` and `data-fingerprint`; often also `data-kind`, `data-readonly`, and on detail roots `data-hash`. |
| `lp-component` | Component container | Creates a `ViewComponent` that owns widgets and optional nav. | Needs `id` for `lp-show` navigation. Nested entity components may use `data-key` when they are only found by ancestor context. Common: `data-default`, `data-visible`, `data-persistent`, `data-kind`, `data-tab`, `data-title`, `data-route`, `data-parent-nav`, `data-merge-form-data`, `data-preload`. |
| `lp-nav` | Component nav/header element | Creates a `NavElement` for titles, toggles, and controls. | Requires `data-nav`. Pairs with a `nav[data-nav="..."]`. Looks for `data-role="title"`, `data-role="header"`, `data-role="controls"`, optional `[data-flipped]`; toggle navs use `data-persistent` and `data-standalone`. |
| `lp-show` | Button or clickable element | Navigates to a component/widget. | Value is `componentId:widgetName`. `widgetName` may be `active`, `default`, or `nav`. `data-toggle="true"` makes a selected trigger hide on re-click. |
| `lp-link` | Row/list container | Makes a non-link row act like its title link. | Requires a descendant with `data-role="title"`, usually an anchor. Ignored inside forms, anchors, and inputs. |
| `lp-menu` | Action-menu container | Opts a template-defined action list into the view-scoped menu controller. | `lp-menu="title"` uses a direct `data-role="menu-trigger"` child and a hidden `data-role="menu-items"` child containing connected `data-menu-item` actions. Place it with a `data-role="title"` inside `[data-menu-anchor]` to anchor the dropdown at the title's bottom-left; otherwise it falls back to the trigger. Use the macros in `templates/menus.html`. |
| `lp-control` | Button | Normalized command button. Some values have direct handlers; others route through `renderComponent()`. | See the control table below. Shared nav controls also carry `data-controls`; local direct controls such as star, pagination, builder help, and modal close buttons do not need nav wiring. |
| `lp-close` | Close control button | Stores the render target for close actions. | Value is `componentId:widgetName` or `componentId`. Usually written directly by templates or copied from active widget `data-close`. Modal close buttons can use `lp-control="close"` without `lp-close` because the modal owns that click. |
| `lp-help` | Help control button or builder button | Opens a help modal. | Value is the help section key. Usually copied from active widget `data-help`; builder buttons may render it directly. |
| `lp-delete` | Delete control button marker. | Opens a delete confirmation modal for the nearest `[lp-entity]` context. Shared nav controls can use the active widget's nearest `[lp-entity]`. |
| `lp-edited-marker` | Inline form notice | Opts its containing form and nearest fingerprinted `[lp-entity]` ancestor into lightweight committed-edit and active-autofill checks. | Requires `data-edited-route` pointing to a side-effect-free GET replacement for that form. Starts hidden with `data-visible="false"` and contains `data-role="edited-reset"`; the action resets only the staged form unless the watcher explicitly changes it to the reload fallback. It does not carry its own key or fingerprint. |
| `lp-create` | Active widget form | Routes submit handling to `Core.create()` and POST. | Requires `data-widget` and `data-route`. Usually needs `data-destination="componentId:widgetName"` for post-create reconciliation. Can combine with `lp-offline` or `lp-deferred`. |
| `lp-update` | Active widget form | Routes submit handling to `Core.update()` and PUT. | Requires `data-widget`; uses target or component `data-route`. Can combine with `lp-offline` or `lp-deferred`; update forms do not use live sync. |
| `lp-load` | Widget target or append sentinel | Fetches server HTML when a widget activates, or marks a chained/paginated append target. | Requires `data-route`. Tables use hidden rows such as `tr[lp-load]` as the next-page marker. |
| `lp-prefetch` | Component or widget target | Loads a component/widget before the user opens it. | On `[lp-component]`, `Core.prefetch()` activates its `[data-widget][lp-prefetch]` children. On a widget target, requires `data-route` when it should fetch. Create/update forms are instantiated but not network-loaded. |
| `lp-offline` | Create/update form target | Allows offline submit queueing through `OfflineQueue`. | Requires a widget with an `offline(context)` method. Uses the normal submit data, `data-route`, method, and often `data-destination` for optimistic rendering. |
| `lp-deferred` | Create/update form target | Marks an online-only async submit. The initial response acknowledges work; the operation subscription refreshes the destination at terminal state. | Requires `data-widget`, `data-route`, and `data-destination`. |
| `lp-sync` | Collaborative document target | Identifies a Yjs-backed document to `SyncManager`. | Value is the document `sync_id`, ending in `:document`. Pair with `lp-fingerprint`; the nearest view/component provides `data-key`. Forms deliberately do not use this attribute. |
| `lp-fingerprint` | Collaborative document target | Carries the client's current document-asset fingerprint for sync drift checks. | Used with `lp-sync` and updated by `CollaborativeDocument` after remote state is applied. The separate `data-fingerprint` on `[lp-entity]` belongs to `EditWatcher`. |
| `lp-select` | Select/facet/search control wrapper | Marks a select-like control for combobox widgets. | Common: `data-index`, `data-kind`, `data-multiple`, `data-preload`, `data-placeholder`, `data-title`. `data-creatable="true"` opts a `FacetsBox` into server-gated Add New rows for supported entity kinds. `data-permission="edit"` or `"assign"` restricts supported facet searches to entities on which the user has that action. Specific widgets instantiate `SelectBox` or `FacetsBox`; there is no single global scan. |
| `lp-search` | Global search container | Mounts the nav search combobox. | Requires an `input[name="q"]`. Builder/offline code may toggle `data-visible`. |

## Control Values

`lp-control` centralizes button semantics so templates do not need many
single-purpose attributes. Values currently seen in source templates/macros:

| `lp-control` value | Behavior | Related attributes and data |
|---|---|---|
| `help` | Opens `HelpModal`. | Needs `lp-help`, usually copied from widget `data-help`. |
| `star` | Toggles starred state by PATCH. | Needs nearest `[lp-entity]` or `[data-key]`; uses and updates `data-active`. |
| `delete` | Opens `DeleteModal`. | Uses the nearest `[lp-entity]` context; `lp-delete` is only the button marker. Shared nav delete controls also render `data-controls="delete"` as an explicit control marker. |
| `previous`, `next` | Fetches a paginated home/list route and refreshes the current widget. | Needs `data-route` and a closest `[data-widget]`. Ignored while offline. |
| `menu` | Routes an action-menu item to its explicit component/widget target. | Needs `lp-show`. This marker also keeps `NavElement` from treating the hidden source item as a visible header or tab toggle. |
| `close` | Routes to the target component/widget. | Needs `lp-close`, often from widget `data-close`. |
| `form`, `task`, `history`, `filters`, `reset` | Routes to the target component/widget. | Needs `lp-show`. `NavElement` can populate it from active widget `data-form`, `data-task`, `data-history`, `data-filters`, or `data-reset`. |

Add new control behavior as a documented `lp-control` value plus explicit
supporting configuration. Avoid introducing one-off direct control attributes
when an existing control value and `data-*` setting can express the behavior.

## Widget Data Attributes

Most behavior in this system depends on `data-*` values on the active
`[data-widget]` target. The important ones are:

| Attribute | Used for |
|---|---|
| `data-widget` | Widget registry name, such as `PageInfo`, `TaskSettings`, `IndexTable`, or `CollaborativeDocument`. |
| `data-route` | GET/POST/PUT endpoint for load/create/update. Component `data-route` is the fallback. |
| `data-destination` | Post-create or deferred destination in `componentId:widgetName` form. |
| `data-title` | Nav title while the widget is active. |
| `data-nav` | `"false"` hides nav toggles for the active widget; `"true"` keeps them available. |
| `data-controls` | On widgets, `"true"` shows the nav control group for the active widget. On shared nav control buttons, values like `show`, `close`, and `help` tell `NavElement` which `lp-*` attribute to populate from the active widget; `delete` marks the delete control explicitly but does not copy a target. Template-contract tooling checks routed controls for this marker and for a matching `lp-*` target or widget `data-*` route. |
| `data-close`, `data-help`, `data-reset` | Values copied into `lp-close`, `lp-help`, or routed reset controls. |
| `data-form`, `data-task`, `data-history`, `data-filters` | Values copied into routed control buttons as `lp-show` by `NavElement`. |
| `data-visible`, `data-persistent` | Initial and reconciled visibility. Persistent widgets/components remain visible when inactive. |
| `data-key`, `data-kind` | Entity identity and theme/routing context for widgets and controls. |
| `data-role` | Local semantic role for widget/template internals. Examples include `title`, `controls`, `expand`, `expandable-cell`, `notifications`, and `notification-count`. Use this for local structure that is not a global `lp-*` behavior hook. Table bodies, page task lists, and site settings sections each own their local `data-role="expand"` behavior. |
| `data-if-empty` | Switches list widgets to another widget when no items are present. |
| `data-preload`, `data-schema`, `data-submission`, `data-conditions`, `data-columns`, `data-selected`, `data-options`, `data-attributes` | JSON configuration parsed by `widgets/loader.mjs` and form/table widgets. |

## Authoring Notes

- Prefer adding configuration as `data-*` on the relevant widget or component;
  add a new `lp-*` attribute only when the frontend needs a new opt-in hook.
- Keep `lp-show` and `lp-close` values aligned with real
  component ids and widget names.
- When adding forms, make exactly one submit mode clear: `lp-create` for POST
  or `lp-update` for PUT. Add `lp-offline`, `lp-deferred`, or sync attributes
  only when the widget implements that behavior.
