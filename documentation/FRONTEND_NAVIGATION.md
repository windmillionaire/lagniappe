# Frontend Navigation

Reference for authoring templates that use the navigation system. The nav system controls which widgets are visible within components, manages toggle buttons, titles, and control buttons (help, close, delete, reset). For the canonical attribute inventory, see [TEMPLATES_ATTRIBUTES.md](TEMPLATES_ATTRIBUTES.md).

## How It Works

A **view** (`lp-view`) contains **components** (`lp-component`). Each component can display one active **widget** (`data-widget`) at a time. Navigation is driven by `lp-show` attributes on buttons/elements — when clicked, the Core view parses the `componentId:widgetName` pair, activates that widget in that component, and reconciles the nav bar to reflect the new state.

Widgets are lazily loaded on first activation. Once loaded they stay cached on the component. All DOM visibility changes happen inside a transition via the `reconcile()` cycle — the nav reads `data-*` attributes off the active widget's target element to determine what title, controls, and toggles to display.

## View & Component Structure

```html
<!-- Root view element -->
<div lp-view data-kind="project" data-key="{{ key }}">

  <!-- A component: owns widgets and optionally a nav bar -->
  <div id="tools" lp-component data-default="CreateUser" data-visible="false">
    <!-- nav bar header -->
    <div lp-nav data-nav="tools">...</div>

    <!-- widgets live inside the component -->
    <form data-widget="CreateUser" data-visible="false">...</form>
    <form data-widget="EditUser" data-visible="false">...</form>
  </div>
</div>
```

| Attribute | Element | Purpose |
|---|---|---|
| `lp-view` | root | Marks the view root. Core/Entity binds event listeners here. |
| `lp-entity` | root | Use alongside `lp-view` for entity detail pages (enables tabs, mobile nav, collaboration). |
| `lp-component` | div | Marks a component container. Must have an `id`. |
| `id` | component | Used as the `componentId` in `lp-show="componentId:widgetName"`. |
| `data-default` | component | The widget to activate when showing `"default"` or `"active"`. |
| `data-visible` | component | `"true"` / `"false"` — whether the component is visible. |
| `data-persistent` | component | `"true"` keeps the component visible even when deactivated. |
| `data-key` | component | Entity key, used for delete operations and routing. |
| `data-kind` | component | Kind identifier (e.g. `"project"`, `"user"`), used for theming. |
| `data-tab` | component | `"true"` marks this component as a tab within an entity view. |
| `data-title` | component | Fallback title when no widget-level title is set. |
| `readonly` | component | Marks the component as read-only; propagates to widgets. |

## Widgets

A widget target is any element inside a component with a `data-widget` attribute. The name must match a key in the widget loader's registry (or it gets a default no-op widget).

```html
<form data-widget="CreateUser"
      data-visible="false"
      data-route="{{ url_for('users.create') }}"
      data-destination="table:IndexRows"
      data-title="Create a User"
      data-close="tools"
      data-help="create_user"
      data-nav="true"
      data-controls="true"
      lp-create>
  <button type="submit" class="..."></button>
</form>
```

### Widget Attributes

These `data-*` attributes on widget targets are read by the nav during reconciliation to configure the nav bar.

| Attribute | Purpose |
|---|---|
| `data-widget` | **Required.** Widget name — must match a loader registry key. |
| `data-visible` | Initial visibility. Managed automatically after first activation. |
| `data-title` | Title displayed in the nav bar when this widget is active. |
| `data-nav` | `"true"` shows component toggle buttons in the nav; `"false"` hides them. |
| `data-controls` | `"true"` shows the control buttons (help, close, delete, reset) when active. |
| `data-close` | Value for the close button — format `"componentId:widgetName"` or just `"componentId"`. Navigates there on close. |
| `data-help` | Help topic key. Populates the help button when this widget is active. |
| `data-reset` | Reset target — format `"componentId:widgetName"`. Shows the reset button, navigating to that target on click. |
| `data-route` | Server endpoint for this widget (used by load, update, create). |
| `data-destination` | `"componentId:widgetName"` — where to navigate after a successful `lp-create` submission. |
| `data-persistent` | `"true"` keeps the widget's target visible regardless of active state. |
| `data-key` | Entity key specific to this widget. |
| `data-kind` | Kind override for this widget. |
| `lp-create` | Marks the form as a create action. |
| `lp-update` | Marks the form as an update action. |
| `lp-load` | Triggers a server fetch when this widget is first activated. |

## Nav Bar

Each component can have one nav bar. It consists of two parts: the **header** (inline with the component, marked with `lp-nav`) and the **toggle bar** (a `<nav>` element matched by `data-nav` name).

### Nav Header (`lp-nav`)

```html
<div lp-nav data-nav="tools" class="...">
  <h2 data-role="title"></h2>
  <div data-role="controls">
    <!-- control buttons go here -->
  </div>
</div>
```

The `data-nav` value on the `lp-nav` element links it to a `<nav data-nav="...">` toggle bar with the same name. The title element (`data-role="title"`) is auto-populated from the active widget's `data-title`.

### Toggle Bar

```html
<nav data-nav="tools" data-persistent="true">
  <button lp-show="tools:CreateUser">New User</button>
  <button lp-show="user-groups:nav">User Groups</button>
</nav>
```

| Attribute | Element | Purpose |
|---|---|---|
| `data-nav` | `<nav>` | Links this toggle bar to a nav header with the same `data-nav` value. |
| `data-persistent` | `<nav>` | `"true"` keeps the toggle bar visible even when the component isn't active. |
| `data-standalone` | `<nav>` | `"true"` means the nav itself can be the component's active element (used for selector-style navs like user groups). |

### Controls

Control buttons use `lp-control="..."` values. They are placed inside
`data-role="controls"` and their visibility is automatically managed based on
the active widget's settings.

```html
<div data-role="controls">
  <button lp-control="help" data-controls="help" lp-help="create_user" type="button">Help</button>
  <button lp-control="close" data-controls="close" lp-close="tools:IndexRows" type="button">Close</button>
  <button lp-control="delete" data-controls="delete" lp-delete type="button">Delete</button>
  <button lp-control="reset" data-controls="show" lp-show="tools:CreateUser" type="button">Reset</button>
</div>
```

`NavElement` usually sets the supporting attributes dynamically from the active
widget's `data-help`, `data-close`, `data-reset`, and routed-control settings.
Routed controls such as `form`, `task`, `history`, `filters`, and `reset` use
the active widget's matching `data-*` value to populate `lp-show`. Delete
controls get their key from the nearest `[lp-entity]` context. For shared nav controls,
`DeleteModal` can use the active widget's nearest `[lp-entity]`.

## Toggle Buttons (`lp-show`)

The primary navigation mechanism. Any element with `lp-show` triggers navigation on click.

```html
<!-- Show the CreateUser widget inside the tools component -->
<button lp-show="tools:CreateUser">New User</button>

<!-- Show the active widget (or default) in the info component -->
<button lp-show="info:active">Info</button>

<!-- Show the component with its default widget -->
<button lp-show="tools:default">Settings</button>

<!-- Activate standalone nav in user-groups -->
<button lp-show="user-groups:nav">User Groups</button>
```

### Format: `componentId:widgetName`

- **componentId** — the `id` of the target `lp-component` element.
- **widgetName** — one of:
  - A specific widget name (e.g. `CreateUser`, `BaseList`)
  - `active` — re-show the currently active widget (or default if none)
  - `default` — show the component's `data-default` widget
  - `nav` — activate the component's standalone nav

### Toggle Behavior

Add `data-toggle="true"` to make a button toggle — clicking it again when that widget is already active will hide it.

```html
<button lp-show="tools:default" data-toggle="true">Settings</button>
```

## Sub-Toggles

Widget toggles that appear inside the nav header (e.g. a "create" button that only shows when a specific component is active). These go inside a `data-role="subtoggles"` container.

```html
<div lp-nav data-nav="mobile">
  <div data-role="subtoggles">
    <span data-role="title"></span>
    <button lp-show="model-tasks:CreateModelTask">
      {{ render_icon("plus") }}
    </button>
  </div>
</div>
```

Sub-toggle buttons are shown/hidden based on which component is currently active.

## Entity Views (Tabs + Mobile)

Entity detail pages use `lp-entity` and organize content into tab components. The `Entity` class handles responsive layout — on mobile, a shared `mobileNav` replaces per-card nav bars, and tab components are stacked instead of side-by-side.

```html
<div lp-view lp-entity data-key="..." data-hash="..." data-kind="project">
  <!-- Mobile nav: shared across tabs on small screens -->
  <div lp-nav data-nav="mobile" data-visible="false">
    <div data-role="subtoggles">...</div>
    <nav>
      <!-- tab toggle buttons -->
      <button lp-show="info:active">Info</button>
      <button lp-show="document:active">Document</button>
    </nav>
  </div>

  <!-- Tab components -->
  <div id="tabs" lp-component>
    <div id="info" lp-component data-tab="true" data-default="ProjectInfo">...</div>
    <div id="document" lp-component data-tab="true" data-default="CollaborativeDocument">...</div>
  </div>

  <!-- Secondary card (e.g. model tasks), moves into tabs on mobile -->
  <div id="model-tasks" lp-component data-tab="true" data-persistent="true">...</div>
</div>
```

Key points:
- `data-tab="true"` on a component marks it as a tab. The active tab is persisted to `localStorage`.
- `data-hash` on the view root is used as the localStorage key prefix.
- On desktop, `#tabs` and secondary cards (like `#model-tasks`) sit side-by-side. On mobile, everything collapses into `#tabs` with a shared mobile nav.
- The `_defaultTabId` in the Entity class determines which tab shows first (defaults to `"info"`).

## Loader Buttons

Toggle buttons inside a `<nav>` that have the `loader` class get automatic loading states — when clicked, the selected button is disabled and others are dimmed until the widget finishes loading.

```html
<nav data-nav="tools">
  <button class="loader" lp-show="tools:CreateUser">New User</button>
  <button class="loader" lp-show="tools:EditUser">Edit User</button>
</nav>
```

## Quick Reference

| I want to... | Do this |
|---|---|
| Add a toggle that shows a widget | `<button lp-show="componentId:WidgetName">` |
| Make a toggle hide on re-click | Add `data-toggle="true"` to the button |
| Set the title when a widget is active | `data-title="My Title"` on the widget target |
| Show help/close/delete buttons | `data-controls="true"` on the widget, plus `data-help`, `data-close`, and key/delete context as needed |
| Hide the nav toggles for a widget | `data-nav="false"` on the widget target |
| Keep a widget visible always | `data-persistent="true"` on the widget target |
| Create a nav that acts as a selector | `data-standalone="true"` on the `<nav>` element |
| Add a new tab to an entity view | New `lp-component` with `data-tab="true"`, add a toggle button to the nav |
| Navigate somewhere after form create | `data-destination="componentId:widgetName"` on the `lp-create` form |
| Navigate somewhere on close | `data-close="componentId:widgetName"` on the widget target |
