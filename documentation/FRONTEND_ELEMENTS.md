# Frontend Elements

The elements system handles dynamic form fields with read/edit modes. It sits inside the widget layer -- form widgets (like `PageInfo`, `TaskSettings`, `CreateUser`) use a **Renderer** to turn a schema into interactive form elements.

## Architecture

```
Widget (extends FormElement)
  └── Renderer
        ├── schema[] → getFormElement() → Element instances
        │                    │
        │              loader.mjs (dynamic import by type)
        │                    │
        │              BaseElement (base class)
        │                    │
        │              Element types (input, select, radio, etc.)
        │
        ├── elements: Map<id, Element>
        ├── visibilityTriggers: Map<Element, Set<Element>>
        ├── visibilityConditions: Map<Element, Condition[]>
        └── statusTriggers: Set

primitives.mjs (DOM factory functions)
```

## First-interaction loading

Global SearchBox and entity-menu/notification combobox behavior is not part of
the static `Core` startup closure. The shell installs capture-phase bootstrap
listeners synchronously. Input or click activation starts the
same idempotent loader used by idle warming, exposes `aria-busy` where
appropriate, and replays the intended open/search action after initialization.
Repeated activation shares one promise. Import failure clears transient state
so a later interaction can retry.

The navbar search remains a native GET form while `SearchBox` loads, so an
immediate Enter submission cannot be lost between first input and deferred
component initialization. Once initialized, `SearchBox` prevents that native
submission and owns keyboard routing and result selection.

Field-specific comboboxes remain widget/element-owned and load with their
containing form. Index tools and Manual dropdowns are further gated on mobile
mode.

## Messaging and mention controls

`MessageComposer` is the shared standard-modal composer used by Notifications
and the Messages page. Its single-value, user-kind `FacetsBox` requests
`permission=message`; selecting a recipient focuses the user-kind body field.
The body is required plain text capped at 1,000 characters, and one operation
ID is retained across a failed/retried submit. Existing Messages threads use a
separate inline reply form whose recipient and conversation pair are validated
by the server.

The collaborative editor registers the inline atom `LagniappeMention`. Typing a
non-empty `@query` opens an accessible listbox backed by
`permission=mention&document=<key>`; arrow keys, Enter, Escape, and pointer
selection are owned by `MentionSuggestions`. Inserted nodes retain occurrence,
recipient, and display-name attributes in internal document HTML. Newly
inserted occurrences remain in the document widget's pending map and its
coalesced offline sync record until the server accepts and persists that
checkpoint. Read-only and public-limited editors render existing nodes but do
not install the suggestion controller.

## FormElement (`elements/form.mjs`)

The bridge between the widget system and the form rendering system. Most settings and create widgets (`TaskSettings`, `DocumentSettings`, `PageInfo`, `CreateUser`, `FileInfo`, etc.) extend `FormElement` rather than writing their own form logic.

### How It Connects

```
Widget layer (loader.mjs)
  └── FormElement (widget base class)
        └── BaseForm (form rendering + UI)
              └── Renderer (schema → elements)
```

`FormElement` is instantiated as a widget (receives attributes from `loader.mjs`). It creates a `BaseForm`, which in turn creates a `Renderer` if the widget has a `schema`. The renderer creates individual `BaseElement` instances for each field.

### Initialization

`FormElement.init()` clones the widget's target element (for later reset), creates a `BaseForm` with the widget's schema/submission/target, calls `form.init()` to render the form, and adds a click handler for read/edit toggling and clear buttons.

### Widget Contract Methods

`FormElement` implements several methods from the widget contract:

| Method | Behavior |
|---|---|
| `data` | Returns `form.data` (FormData from the rendered form) |
| `showError(error)` | Delegates to `form.showError()` |
| `created()` | Sets a `_created` flag for postreconcile |
| `updated(response)` | Stores new schema/submission from the response, updates the initial target snapshot, sets `_updated` flag |
| `markUnsavedState()` / `clearUnsavedState()` | Tracks local edits for submit-button feedback independently of live sync |
| `prereconcile()` | Renders an authoritative replacement form against a detached target when created or updated. |
| `postreconcile()` | Synchronously destroys the old form and swaps in the prepared target inside the component transition. Shows success feedback if the response had HTML. |
| `destroy()` | Destroys the form and all destroyables |

### Reset Flow

`prepareReset()` creates a detached target and initializes a staged `BaseForm`
without disturbing the connected form. `commitReset()` then destroys the old
form, swaps the prepared target, and adopts its staged state synchronously.
`reset()` remains the compatibility convenience that runs both phases. This
gives widgets a clean re-initialization after create or update operations while
keeping dynamic imports and renderer work outside the visual transition.

## BaseForm (`elements/base/baseForm.mjs`)

The form rendering and UI management class. Used by `FormElement` (for widgets) and directly by the builder's `ComponentsPanel` and `Condition` system.

### Initialization

`BaseForm.init()`:

1. Finds the submit button (in the submit group or directly in the target)
2. If a schema exists, creates a `Renderer` and calls `render()` to populate the form
3. Appends any extra HTML elements
4. Moves default fields (`name-*`, `description-*`) to the top
5. If readonly, removes submit controls entirely
6. Restores any server-rendered `lp-edited-marker` that schema/HTML rendering displaced
7. Sets the submit button text from `messages.submit` and wires up click feedback (`messages.submitting` with spinner)
8. Listens for editable input/change/reset events and updates the generic unsaved state

### Submit Button States

The submit button cycles through states defined by `messages`:

| Property | When Shown |
|---|---|
| `messages.submit` | Default state (e.g. "Save", "Create") |
| `messages.submitting` | After click, before response (e.g. "Saving..." with spinner) |
| `messages.submitted` | After `success()` is called (e.g. "Saved" with check icon) |

Submit buttons use a stable, absolutely positioned leading icon slot. Changing
between no icon, unsaved, spinner, offline, and success states therefore does
not recenter or resize the text. The shared action style is full width by
default, including direct-request and modal actions; compact navigation,
toolbar, and icon-only controls use their own styles instead of overriding the
action style. Shared asynchronous buttons preserve direct `data-role="icon"`
and `data-role="text"` children through every state. Brief success feedback is
shown and hidden by short atomic commits rather than opacity fades.

Any editable form with a submit button shows the cloud-exclamation icon after
a local field change. Forms do not use live sync. A successful submit or form
reset clears that state. Offline blocking and queued-submit states still
take priority, so forms without `lp-offline` show `Server Offline`, while
offline-capable forms retain their existing queued feedback.

`resetSubmitButton()` returns to the default state. `showSubmitButton()` / `hideSubmitButton()` and `showSubmitGroup()` / `hideSubmitGroup()` control visibility.

### Committed Revision Baselines

Marked `FormElement` widgets keep an in-memory normalized snapshot of their
`formData`. The baseline is refreshed after initialization and authoritative
reset/reconciliation. Repeated values compare as unordered values and non-empty
files compare by metadata; widgets may add form-owned revision entries for
visible state deliberately omitted from their submit payload. The snapshot is
not hashed, persisted, or sent to the server.

An `lp-offline` form does not inspect `OfflineQueue` during initialization.
It renders the authoritative server state immediately. Initial replay starts
only after the view is ready. After a successful replay for a mounted form,
OfflineQueue asks EditWatcher/PollingCoordinator for an immediate entity check
rather than directly acknowledging the returned revision. The normal watcher
path then applies it to an inactive clean form or offers value reconciliation
for an active form. This keeps persisted queue state out of the rendering
lifecycle. Reconnect does not wait for queue hydration or replay before
restoring polling, sync, EditWatcher, or the visible refresh.

Code that needs to create a new offline mutation first calls
`view.ensureOfflineQueue()`; it must not assume the lower-camel `offlineQueue`
handle is already populated merely because the view is interactive. The
renderer's internal structured submission snapshot remains queue metadata and
is never submitted as an HTTP field.

`EditWatcher` builds detached revision-preview widgets from the form's focused
GET response. Preview mode does not register sync, navigate, update page
metadata, or issue secondary requests. Inactive forms do not subscribe or
request replacements; each marker retains its last-seen revision and performs a
single catch-up probe if stale when its widget becomes active. A component's
visible active widget enters revision comparison even when clean, so changes
remain visible to someone currently viewing that form. Schema drift is applied
through the latest schema while retaining local values by stable field ID; the
client does not retain a selectable historical schema.

Field-by-field reconciliation is reserved for forms where both the live and
saved revisions provide a renderer, a non-empty schema, and structured
submission data. When those submissions differ, **Review values** renders only
the changed fields and applies the selected values through the normal
`updated()`/`postreconcile()` reset path. A dirty form without that capability
shows **Reset form** inline. If such a form has a queued mutation, the review is
whole-form: retry the queued version or use the saved version. Equal revisions
resolve directly, so a zero-difference field modal is never shown.

### Error Display

`showError(message)` creates an error element (via `primitives.error()`) and inserts it before the submit button. `hideError()` clears it. Errors are automatically hidden when the submit button is clicked.

## Renderer (`elements/renderer.mjs`)

Orchestrates form rendering and element lifecycle.

### How It Works

The renderer receives a `form` widget that provides `schema` (field definitions), `submission` (existing values), `target` (DOM container), and `key` (entity identifier).

**`render()`** iterates the schema array, creates an element for each field via `getFormElement()`, appends it to the DOM, and wires up:

- **Read/edit toggle**: Clicking a field label switches `data-mode` from `"read"` to `"edit"`. Clicking outside switches back.
- **Clear button**: Fields with `schema.clear` get a clear button that calls `element.clear()`.
- **Visibility triggers**: Fields with `schema.visibility` are shown/hidden based on other fields' values. Multiple conditions for the same trigger field are alternatives; conditions for different trigger fields must all match. Initial visibility is evaluated for readonly renders too; readonly forms do not attach change listeners.
- **Status triggers**: Status-type elements update their messages whenever trigger fields change.

One input event computes all visibility changes first and commits their
`data-visible` state in one `withTransition()` call. Status text remains an
immediate update so rapid input does not create a queue of cosmetic animations.

`render()` may replace the host children only during `BaseForm.init()`; the
base form then adds headers, prepend/append content, and submit controls.
Server-supplied fragment replacement uses the full `reset()` boundary because
the form owns teardown for nested editors, uploads, and other widget state.
Schema and submission changes consequently have one authoritative
reconciliation path instead of a separate field-patch merge path.

**`destroy()`** cleans up all elements and removes listeners.

## Loader (`elements/loader.mjs`)

```js
const element = await getFormElement(renderer, schema, submission);
```

Dynamically imports the element class by `schema.type` and returns an instantiated element. Unknown types throw an error.

## BaseElement (`elements/base/baseElement.mjs`)

Base class for all form elements.

### Constructor

Receives `renderer`, `schema`, and `submission`. Sets up the element's identity (`id`, prefixed with renderer id if present) and mode tracking.

### Key Members

| Member | Description |
|---|---|
| `elt` | The rendered DOM element (calls `create()` lazily on first access) |
| `read` | Getter -- returns the read-only display element |
| `edit` | Getter -- returns the editable input element |
| `mode` | `"read"` or `"edit"` |
| `data` | `FormData` getter for submission |
| `id` | Field identifier |
| `showEmptyFields` | When true, empty readonly fields render a quiet "Not provided" display instead of being omitted. |

### Methods

| Method | Description |
|---|---|
| `create()` | Builds the complete DOM element with label, read view, edit view, and optional clear button |
| `update(value)` | Replaces the element with a new one using the given submission value |
| `destroy()` | Runs cleanup on any registered destroyables |

### Optional Overrides

| Member | Description |
|---|---|
| `cell` | HTML string for table cell display (used by inline table elements) |
| `active(value)` | Returns true if `value` is currently selected -- used by checkbox, radio, and select for visibility trigger evaluation |
| `clear()` | Resets the field. Only implemented on elements that can't be cleared by normal user interaction (radio buttons, select dropdowns, link fields). |
| `static` | If `true`, the element renders even when readonly with no submission |

Readonly rendering has two modes: sparse readonly omits empty non-static fields, while structural readonly keeps labels visible and shows "Not provided" for empty values. Completed task forms use sparse readonly; active permission-readonly task forms opt into structural readonly.

## Element Types

| Type | Class | Description |
|---|---|---|
| `input` | `InputElement` | text, number, date, time, email, tel, url (driven by `schema.input`) |
| `textarea` | `TextareaElement` | Multi-line text |
| `checkbox` | `CheckboxElement` | Single checkbox with icon |
| `radio` | `RadioElement` | Radio button group from `schema.options`, supports row/column layout |
| `select` | `SelectElement` | Dropdown powered by `SelectBox` combobox |
| `link` | `LinkElement` | Internal link (`FacetsBox` search) or external URL |
| `bookmark` | `BookmarkElement` | External URL with metadata and replace options |
| `location` | `LocationElement` | Google Places autocomplete via `LocationBox` combobox |
| `signature` | `SignatureElement` | Canvas drawing pad with file upload |
| `table` | `TableElement` | Inline editable rows with nested elements per column |
| `todo` | `TodoElement` | Task-only ordered checklist with inline add, rename, and remove controls |
| `html` | `HtmlElement` | Static HTML content (async loaded). Always renders (`static = true`). |
| `status` | `StatusElement` | Conditional messages based on other field values. Always renders (`static = true`). |

### Standard vs. Non-Standard Elements

Most elements follow the standard pattern: extend `BaseElement`, override `read` and `edit` getters, and let the base class handle `create()`, `mode` switching, and `data` collection.

Four elements override `create()` entirely because they don't fit the read/edit paradigm:

- **`TableElement`** -- manages its own row creation/editing flow
- **`TodoElement`** -- keeps checkboxes active in normal mode and disables them while list structure/text is being edited
- **`HtmlElement`** -- async-loads content, no edit mode
- **`StatusElement`** -- displays conditional messages, no edit mode

## Schema Properties

Common properties passed via the `schema` object:

| Property | Description |
|---|---|
| `id` | Unique field identifier |
| `type` | Element type (determines which class to load) |
| `title` / `label` | Display label |
| `placeholder` | Input placeholder text |
| `options` | Array of `{value, label}` for radio/select |
| `input` | Input subtype: `text`, `date`, `time`, `email`, `tel`, `number`, `url` |
| `visibility` | Array of `{id, value}` conditions, or `null`/absent for an unconditional field. Conditions sharing an `id` are OR'd together; different trigger `id`s are AND'd together. |
| `status` | Array of `{id, value, text}` for status element messages |
| `columns` | Array of column schemas for table element |
| `layout` | `"row"` or `"column"` for radio layout |
| `multiple` | Allow multiple selection (select) |
| `location` | `"in"` for internal link search, `"out"` for external URL |
| `clear` | If truthy, adds a clear button |

Todo values use `{items: [{text, checked}]}`. Enter or forward Tab from the
draft commits a non-empty item and focuses a fresh draft; Shift+Tab remains an
escape path. The latest-history control restores the most recent item texts
with every checkbox reset to unchecked, and unlike ordinary fields does not
persist that value as a repeating task default. Todo title actions use the
same lightweight icon treatment as table title actions: add and done are green,
while edit and latest-history retain the form color.

When a reopened task has history, every submission-bearing element exposes a
latest-history control while empty, including table and todo elements. Static
HTML, computed status, and signature assets do not expose that control.

## Primitives (`elements/primitives.mjs`)

Factory functions for creating DOM elements. All accept an attributes object. Used by elements to build their read/edit views without writing raw DOM manipulation.

### Form Inputs

| Function | Output |
|---|---|
| `input(attrs)` | `<input>` with optional label wrapper |
| `textarea(attrs)` | `<textarea>` with optional label |
| `checkbox(attrs)` | Checkbox with icon and optional label |
| `radio(attrs)` | Radio input with label |
| `select(attrs)` | `<select>` with options, icon, `lp-select` attr |

### UI Elements

| Function | Output |
|---|---|
| `label(attrs)` | Label element with optional icon |
| `badge(attrs)` | Badge with icon and text |
| `toggle(attrs)` | Toggle button with icon |
| `icon(attrs)` | Icon span |
| `div(attrs)` | Div with kind/role/style |
| `spinner()` | Spinning icon |
| `loading()` | Pulsing skeleton loader |

Icon-only controls use a two-element layout contract: the button or link owns
the interaction outline and grid stacking, while its direct Material Symbol
span owns all box and glyph sizing. Active/inactive variants place both
Material spans in the same grid cell and apply visibility state directly to
those spans. Component styles may position, color, or hide an icon, but icon
geometry and optical offsets belong in `icons.css`. Do not add a centering
wrapper around an icon; use an extra element only when it owns separate
behavior that cannot live on the control or icon.

### Buttons

| Function | Output |
|---|---|
| `buttons.submit(attrs)` | Submit button |
| `buttons.explain(attrs)` | "Initial Prompt" button |

### Common Attributes

```js
{
  name,           // input name
  id,             // element id
  value,          // input value
  required,       // boolean
  disabled,       // boolean (adds readonly, pointer-events-none)
  label,          // label text (wraps input in label element)
  placeholder,    // placeholder text
  styles: {},     // override default STYLES lookups
  data: {},       // dataset attributes
}
```

### Upload Controls

`BaseUpload` prefers resumable browser-to-storage uploads and submits signed
metadata instead of file bodies after those uploads finish. Single-file and
small compatibility submissions may fall back to multipart when direct upload
cannot start. The fallback is bounded by both aggregate size (30 MB) and file
count (five), so a large selection is never collapsed into one upstream
request. For a large selection, successful direct uploads remain checkpointed
in the widget and a retry resumes with the first unfinished file. Internal
browser retry signatures are removed before the signed metadata is submitted.

## Combobox System (`elements/combobox/`)

A family of typeahead/autocomplete components used by select, link, location, and search elements.

| Class | Used By | Description |
|---|---|---|
| `Combobox` | -- | Base class. Manages input, results list, keyboard navigation, ARIA attributes. |
| `Dropdown` | Buttons and compact action/select menus | Shared floating panel, dismissal, and keyboard behavior; defaults to the current trigger and supports an explicit `positionReference`, custom ARIA roles, and reference-width matching. |
| `SelectBox` | `SelectElement` | Read-only combobox trigger backed by local `<select>` options |
| `FacetsBox` | Internal links and entity selectors | Searches the server index for matching entities |
| `LocationBox` | `LocationElement` | Google Places autocomplete |
| `SearchBox` | Global search bar | Full search with faceted results, mounted by the observer on `[lp-search]` elements |
| `Submitter` | `SelectBox`, `FacetsBox` | Mixin that adds hidden `<select>` value management |

All combobox classes extend `Combobox` (or `Submitter(Combobox)`) and specialize
option loading or selection for their data source. `SearchBox` and
`LocationBox` extend `Combobox` directly.

Floating panels open normally while Floating UI computes their first
coordinates. `panelReady` and `data-positioned` expose completion of that
initial placement so lazy adapters can retain their busy state and focused
tests can wait on behavior rather than timing. Superseded asynchronous
measurements cannot overwrite newer coordinates, and later `autoUpdate`
placements remain live.
