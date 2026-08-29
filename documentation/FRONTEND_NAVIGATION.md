# Frontend Navigation

This guide explains how templates compose views, components, widgets, nav, and
tabs. The full attribute vocabulary is in
[FRONTEND_TEMPLATES_ATTRIBUTES.md](FRONTEND_TEMPLATES_ATTRIBUTES.md); do not
duplicate it here.

## Mental model

```text
[lp-view]
  -> [lp-component] with an id
       -> optional [lp-nav]
       -> one active [data-widget]
```

`lp-show="componentId:WidgetName"` selects a widget. `Core` activates it,
finishes imports/loads/preparation, and commits component, widget, and nav state
together.

```html
<div lp-view data-kind="user">
  <section id="tools" lp-component data-default="CreateUser">
    <header lp-nav data-nav="tools">
      <h2 data-role="title"></h2>
      <div data-role="controls"></div>
    </header>

    <form data-widget="CreateUser"
          data-route="{{ url_for('users.create') }}"
          data-destination="table:IndexRows"
          data-title="Create a user"
          lp-create>
      ...
    </form>
  </section>
</div>
```

## Components and widgets

Every component needs a stable `id`. `data-default` names the widget selected
by `default` or when no active widget exists. `data-persistent="true"` keeps a
component or widget rendered when inactive. `data-tab="true"` marks a child
component as an Entity tab.

A widget's `data-widget` must match `widgets/loader.mjs` or intentionally use
the no-op default widget. Put request and presentation configuration on the
widget:

- `data-route` for GET/POST/PUT;
- `data-destination` for create/deferred reconciliation;
- `data-title` for the current nav heading;
- `data-close`, `data-help`, and routed control targets;
- `data-nav` / `data-controls` for nav visibility; and
- `lp-load`, `lp-prefetch`, `lp-create`, `lp-update`, `lp-offline`, or
  `lp-deferred` for the widget behavior it implements.

## Navigation targets

`lp-show` uses `componentId:widgetName`.

| Widget name | Meaning |
| --- | --- |
| Exact registry name | Activate that widget. |
| `active` | Reopen the selected widget, falling back to the default. |
| `default` | Activate `data-default`. |
| `nav` | Activate a standalone selector nav. |

Add `data-toggle="true"` when selecting an already-visible target should hide
it.

## Nav header and toggle bar

An `[lp-nav][data-nav="tools"]` header pairs with
`nav[data-nav="tools"]`. The active widget supplies the title, available
toggles, and controls. A toggle bar can be persistent or standalone.

```html
<nav data-nav="tools" data-persistent="true">
  <button lp-show="tools:CreateUser">New user</button>
  <button lp-show="groups:nav">Groups</button>
</nav>
```

Controls use documented `lp-control` values. Shared nav controls also carry a
`data-controls` marker so `NavElement` knows which widget setting to copy.

```html
<div data-role="controls">
  <button type="button" lp-control="help" data-controls="help"></button>
  <button type="button" lp-control="close" data-controls="close"></button>
  <button type="button" lp-control="delete" data-controls="delete" lp-delete></button>
</div>
```

Title action menus use `templates/menus.html`. Hidden source items carry the
same delegated `lp-show` or delete controls used elsewhere; `EntityMenu`
renders the floating panel and forwards selection to those items.

## Entity tabs and mobile layout

An Entity root carries `lp-entity`, `data-key`, `data-hash`, and `data-kind`.
Its tab components use `data-tab="true"`; their toggles use ordinary `lp-show`.
`Entity` persists the active tab by `data-hash` and moves secondary cards into
the tab stack on mobile.

```html
<div lp-view lp-entity data-kind="project" data-key="..." data-hash="...">
  <section id="tabs" lp-component>
    <section id="info" lp-component data-tab="true" data-default="ProjectInfo">...</section>
    <section id="document" lp-component data-tab="true" data-default="CollaborativeDocument">...</section>
  </section>
</div>
```

Do not create a second mobile-only content tree. Entity moves the same
components and reconciles their nav ownership.

## Authoring checklist

- Use stable component IDs and registered widget names.
- Put behavior opt-ins on the element that owns the behavior.
- Keep routed controls aligned with actual component/widget targets.
- Give create and deferred forms an explicit destination.
- Use the macros and attributes already recognized by template-contract
  tooling.
- Run `venv/bin/python run.py template-contracts --changed --check` after
  changing a tagged template contract.
