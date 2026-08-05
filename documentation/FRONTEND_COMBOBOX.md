# Frontend Combobox

The combobox system (`src/script/elements/combobox/`) provides typeahead, dropdown, and search components. All combobox types share a single base class that handles panel positioning, keyboard navigation, ARIA attributes, and lifecycle management.

## Class Hierarchy

```
Combobox (base)
  ├── Dropdown                  (toolbar menus, generic dropdowns)
  ├── SearchBox                 (global search bar)
  ├── LocationBox               (Google Places autocomplete)
  └── Submitter(Combobox)       (mixin -- adds hidden <select> + value management)
        ├── SelectBox           (form element dropdowns)
        └── FacetsBox           (entity link search)
```

`Submitter` is a mixin (higher-order class) that wraps a `Combobox` subclass
with value selection, hidden `<select>` management, multi-select support, and
placeholder display. `SelectBox` and `FacetsBox` use `Submitter(Combobox)`.
`LocationBox` extends `Combobox` directly.

## Combobox Base (`combobox.mjs`)

### Construction

The constructor receives a parent DOM element and finds the `<select>` or
`<input>` inside it. It reads an explicit configuration allowlist from
`data-*` attributes on both the parent and element: the common index, kind,
placeholder, preload, multiple, and creatable settings plus the FacetsBox
form-type, user-inclusion, and permission filters. It also sets up bound
handlers for keyboard, click, pointer, and intersection events.

### Lifecycle

**`init()`** sets ARIA attributes (`role="combobox"`, `aria-expanded`, `aria-haspopup`), disables autocomplete and 1Password, starts the `IntersectionObserver`, and stores itself as `parent._lp_combobox`.

**`destroy()`** removes all event handlers, disconnects the observer, cleans up the auto-update loop, and removes the panel from the DOM.

### Handler Registration

Trigger click and keydown handlers are attached synchronously during `init()` so
the first interaction cannot race initialization. An `IntersectionObserver`
dismisses an open panel if its trigger scrolls out of view; it does not own
trigger-handler registration.

### Panel

The dropdown panel is a `<div role="listbox">` appended to `document.body` and positioned using `@floating-ui/dom` with `offset`, `shift`, and `flip` middleware. The panel's width matches the input when the input has `w-full`. Positioning is kept in sync via `autoUpdate()` which recalculates on scroll/resize.

The default position reference is resolved from the combobox's current
`element` whenever positioning starts. This matters for adapters such as
`SelectBox` and button-backed facet controls, which replace the element they
had during construction. A dropdown that intentionally floats from another
element can set `positionReference`; `placement` defaults to `bottom-start`,
and `matchReferenceWidth` can make the panel at least as wide as that explicit
reference. Title action menus use these options to anchor the panel's
`bottom-start` placement to the title rather than to the adjacent menu button.

**`updatePanel(html)`** replaces panel content, rebuilds the `options` array from `[role="option"]` elements, and adds checkboxes for multi-select mode.

**`showPanel()`** opens the panel, starts auto-update positioning, and closes any other open combobox panels on the page.

**`hidePanel()`** closes the panel, removes panel handlers, and stops auto-update.

### Keyboard Navigation

DOM focus stays on the trigger while the panel is open. The active option is
represented with `aria-activedescendant` and `aria-selected`.

| Key | Behavior |
|---|---|
| ArrowDown/ArrowUp | Move the active option while the panel is open, wrapping at either end |
| Enter | Select the active option; `Submitter` comboboxes also use Enter to open or close the panel |
| Tab | Close the panel and continue normal focus navigation |
| Escape | Close and dispatch `deactivate` |
| Backspace/Delete | Clear an existing `Submitter` selection |

Pointer hover makes an option active, pointer down is cancelled to preserve
focus on the trigger, and click selects the option. Clicking outside the
trigger and panel closes and deactivates the combobox.

## Submitter Mixin (`submitter.mjs`)

Wraps a `Combobox` subclass to add value management. Used by `SelectBox` and `FacetsBox`.

### What It Adds

- **Hidden `<select>`**: Creates or reuses a hidden `<select>` element to hold selected values. This is what actually gets submitted with the form.
- **`values` (Set)**: Tracks currently selected option IDs.
- **`multiple`**: Multi-select mode. When enabled, selecting an option toggles it (with checkbox UI). When disabled, selecting replaces the previous value.
- **`preload`**: Reads `data-preload` JSON to pre-populate values on init.
- **Placeholder management**: Shows selected option names in the input placeholder, updates `data-kind` to match the selected option's kind.
- **Change events**: Dispatches `change` and `updated` (with option details) events on the input element when values change.
- **`clear()`**: Resets all values, hides panel, updates the select.
- **`deactivate()`**: Hides panel, clears input text, restores placeholder.

### `selectOption(option)`

For single-select: clears previous, adds new value, closes panel. For multi-select: toggles the value and its checkbox, keeps panel open.

## Results (`results.mjs`)

Manages recent selections in `localStorage` and generates option HTML.

### Storage

Recent selections are stored per index key as `recent-{index}` in localStorage, limited to 10 items. When no server results are available (e.g. on first focus), recent selections are shown.

### HTML Generation

Three rendering modes based on the `index`:

| Index | Renderer | Used By |
|---|---|---|
| `"search"` | `search()` | SearchBox -- shows icon, name, parent, form field matches, text snippets |
| Any other string | `facet()` | FacetsBox -- shows icon, name, parent breadcrumb |
| `null`/`undefined` | `option()` | SelectBox -- simple icon + name |

## Subclass Details

### SelectBox (`select.mjs`)

Used by the `SelectElement` form element for dropdown selects. Replaces the native `<select>` with a typeahead combobox input.

**`init()`** hides the real `<select>`, creates an `<input>` in its place (readonly, `inputmode="none"`), builds items from the select's `<option>` elements, and calls `updateSelect()` to sync initial state.

**`elementClick()`** toggles the panel (no search -- just shows all options).

**`addOption(option)`** dynamically adds a new option to the items list and refreshes the panel.

### FacetsBox (`facets.mjs`)

Used by the `LinkElement` for internal entity links. Searches the server index on input.

**`_search(query)`** sends a GET to `/l/search-index/{index}` with the query,
form type, and currently selected hashes (to keep them visible in results).
Displays server-returned HTML in the panel.

`data-permission="edit"` and `data-permission="assign"` add the corresponding
server-side permission filter. The setting may live on either the `lp-select`
wrapper/button or its nested input.

Opt-in quick-create is enabled with `data-creatable="true"` on the FacetsBox
trigger. When a non-empty search has zero real matches and the current user has
create permission for the facet kind, the server returns an `Add New ...`
command row. Selecting that row posts to `/l/search-index/{index}/create`, then
selects the server-rendered created option through the normal `Submitter`
selection path. Supported quick-create kinds are `project`, `category`, `form`,
and `page`; users and model tasks are intentionally excluded.

**`selectOption(option)`** calls the `Submitter` base (adds to values), then saves to recent results.

### LocationBox (`location.mjs`)

Used by the `LocationElement` for Google Places autocomplete. On init, requests the user's geolocation via `updateUserLocation()`.

**`_input(event)`** shows recent locations when empty, searches the server (`/l/search-location`) when typing.

### SearchBox (`search.mjs`)

The global search bar, mounted by the observer on `[lp-search]` elements. Does **not** use `Submitter` -- it navigates to results instead of selecting values.

**`init()`** sets up a debounced input listener (200ms) and creates an initial panel with recent searches.

**`_search(query)`** sends a GET to `/l/search-bar` with the query. Panel shows server-returned results.

**`selectOption(option)`** saves the selection to recent results and navigates to `option.dataset.url`.

**Enter key** navigates to the full search page (`/l/search-page?q=...`).

### Editor Link Search

The editor `addLink` form owns a small editor-specific `Combobox` subclass. It
queries the same `/l/search-bar` endpoint and renders the same `"search"`
results as `SearchBox`, but selecting an option applies `option.dataset.url` to
the current editor link instead of navigating.

### Dropdown (`dropdown.mjs`)

A general-purpose dropdown menu used by title actions, the editor toolbar, and
compact navigation/tools menus. It does not use `Submitter`.

**`init(menu)`** receives a menu config with `items` (array of `{icon, name, kind, onClick}` or `{html}`) and optional `placement`, `positionReference`, `matchReferenceWidth`, ARIA roles, and styles.

**`selectOption(option)`** calls `item.onClick(option)` if defined, then closes the panel.

## Test Boundary

`testing/tests_js/test_016_combobox_frontend.py` executes the source in Node
with small platform fakes. It covers the live-versus-explicit positioning
reference contract, application of Floating UI results, ARIA state, keyboard
navigation, pointer selection, and dismissal behavior. This is enough to catch
the stale-reference regression without starting a browser.

Exact viewport geometry, CSS layout, native event propagation, and rendered
template placement still require E2E coverage because Node has no layout
engine. The Node positioning check therefore verifies which element and
placement are supplied to Floating UI, not browser pixel geometry.
