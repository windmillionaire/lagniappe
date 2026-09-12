# Frontend Builder

The form builder (`src/script/views/builder/`) is a drag-and-drop interface for creating and editing form schemas. It lets users add form elements, configure their settings, set up conditional visibility/status rules, define table columns and select/radio options, and preview the rendered form. Name, schema, static HTML and local images belong to one browser draft and are published together on explicit Save.

## Architecture

```
FormBuilder
  ├── ComponentsPanel   (palette of draggable element types)
  ├── ModelPanel         (the form model -- draggable element list)
  ├── ElementSettings    (settings panel for the selected element)
  ├── FormSettings       (form-level generation/restriction/settings panel)
  ├── ConditionPanel     (overlay for editing conditions/options/columns)
  │     └── Condition instances (visibility, status, options, columns, html)
  ├── Header             (form name, save button, preview toggle)
  ├── SearchBox + OfflineModal (standalone shell services)
  └── Sortable instances (drag-and-drop via SortableJS)
```

The builder is a standalone view -- it does not use the Core/Component/Widget system. It manages its own click handler, element selection, and schema state.

Below the `lg` breakpoint, the builder layout is hidden and the existing
Desktop Only notice is shown. This prevents the desktop columns from creating
horizontal overflow behind the notice.

## FormBuilder (`builder.mjs`)

The main controller class. Owns the element map, sortable instances, all panel
references, the global SearchBox mounted for this standalone view, and its
OfflineModal.

### State

| Property | Description |
|---|---|
| `elements` | `Map<id, {item, schema, settings}>` -- all form elements. Order matches the form layout. |
| `selectedElement` | The currently selected element entry from the map |
| `sortables` | `{model, components}` -- SortableJS instances |
| `schemaElt` | Hidden `<input name="schema">` that holds the serialized JSON |
| `draft` | `BuilderDraft` owns the saved baseline, current snapshot and bounded Undo/Redo history. |
| `htmlFields` | Static content keyed by field ID; local image references resolve to browser blobs for preview. |

### Initialization

1. Parses the existing schema from the hidden input (or from `data-schema`)
2. For page-type forms, ensures `name` and `description` fields exist (from `PAGE_DEFAULTS`)
3. Creates `ModelElement` DOM nodes and element entries for each schema item
4. Initializes SortableJS on both the components palette and the model panel
5. Sets up the global click handler

Search initialization may finish after the rest of the view. The Builder
stores the instance before awaiting initialization; teardown destroys it
immediately, and the late completion path destroys it again safely rather than
publishing. OfflineModal enablement similarly uses one removable trigger
listener.

### Schema Management

**`updateSchema(silent, group)`** -- serializes all element schemas (in map order) to JSON, writes the hidden input and records form edits. Typing in one field setting can share a history entry. Document content uses `setHtml()` → `BuilderDraft.updateHtml()` instead: it updates HTML, revision and dirty status without copying or comparing the schema on every editor update.

**`updateSchemaOrder()`** -- rebuilds the elements map in DOM order (defaults first, then model panel children). Called after drag-and-drop reordering.

### Element Lifecycle

**`createElement(schema)`** -- generates a unique ID if needed, creates the `ModelElement` DOM node and settings panels, and adds the entry to the elements map. Returns the DOM element.

**`selectElement(id)`** -- sets `selectedElement`, highlights the item in the model panel, and shows its settings.

**`removeElement()`** -- removes an unsaved draft element and its conditions as an undoable change. Saved field identities cannot be removed until the migration workflow is available. The server enforces the same saved-field, option-value and table-column compatibility constraints.

`BuilderDraft` keeps at most 100 commands covering schema, name and field order,
with selection restored alongside them. A generated schema change is one command.
Document text, formatting and image layout belong to the editor's own Undo;
these edits neither add Form history nor clear Form Redo. Generated HTML for
existing Document fields also leaves Form history unchanged. Form Undo/Redo
preserves their current content. Adding/removing a Document field is a schema change, so its
snapshot retains content and image references for restoring that field.

Dirty status still includes all active HTML and form edits. Undo after Save can
produce an unsaved draft and cannot bypass saved-identity constraints. Ordinary
Save retains the current editor and its keyboard history. Undo/Redo, generation,
or a Save response that changes the visible draft rebuilds the form and recreates
editors; their local keyboard history does not survive that rebuild.
Consequently, generated replacement HTML currently has no local Undo; supporting
that requires applying it through a retained editor history.
The toolbar Undo/Redo controls are hidden during Preview and return with their
existing enabled/disabled states when Preview closes.

### Drag and Drop

Two linked SortableJS groups:

- **Components palette** (`pull: "clone"`, `put: false`): clones element types into the model. The `onMove` handler prevents adding duplicate unique elements (status, signature, bookmark).
- **Model panel** (`pull: false`, `put: true`): receives clones from the palette. `onAdd` creates the real element entry and selects it. `onUpdate` reorders the schema.

### Conditions

**`showCondition(name, index)`** -- loads or retrieves a condition editor for the given schema property (`visibility`, `status`, `options`, `columns`, `html`). Opens it in the condition panel. The `index` parameter determines whether it's creating new (-1) or editing existing.

Async condition loading and initialization retain the selected element as the
publication owner. If selection changes or the Builder is destroyed, a newly
loaded condition is destroyed instead of being opened.

**`getEligibleConditionTargets()`** -- returns checkbox, radio, and select elements (excluding the selected element) as potential visibility/status condition targets.

## Panels

### ComponentsPanel (`panels/components.mjs`)

The left sidebar showing available element types. Elements are draggable into the model panel.

### ModelPanel (`panels/model.mjs`)

The center panel showing the current form layout. Each element is rendered as a `ModelElement` -- a simplified visual preview (disabled inputs, labels, badges for table columns).

**`ModelElement`** is a registry of factory functions, one per element type. Each creates a styled `<div>` with the element's icon, label, and type-specific preview (input fields, radio buttons, select dropdowns, table column badges, etc.). Todo lists intentionally render only their title in the builder model. These are display-only -- the actual form elements are rendered separately for preview.

**Default elements** (`name`, `description` for page forms) appear in a separate panel above the model and cannot be deleted or reordered relative to custom elements.

**`focusItem()` / `blurItem()`** -- when editing a condition, the model focuses on just the selected element (hides others) and removes its minimum height so the outline fits that element. On close, all elements and the normal drop area height are restored.

### ElementSettings (`panels/elementSettings.mjs`)

The right sidebar showing settings for the selected element. Settings are
determined by `CONFIG.DEFAULT_SETTINGS[type]` -- each element type has a list
of setting names, and each name maps to a `SettingsElement` factory function.

**Available settings:**

| Setting | Creates |
|---|---|
| `title` | Text input for the element title |
| `placeholder` | Text input for placeholder text |
| `visibility` | List of visibility conditions with add/edit/remove |
| `status` | List of status message conditions with add/edit/remove |
| `options` | List of radio/select options with add/edit/remove |
| `columns` | List of table columns with add/edit/remove |
| `input` | Radio group to select input subtype (text, tel, number, email, date, time) |
| `location` | Radio group to select link type (internal/external) |
| `required` | Checkbox |
| `multiple` | Checkbox (select elements) |
| `checked` | Checkbox for default checked state |
| `editor` | Toggle to open the rich text editor |
| `deleteButton` | Delete button for removing the element |

Settings changes update the element schema and model preview in real-time. The
`input` and `change` event handlers on the settings panel delegate to `_set*`
methods that update both the schema object and the model DOM. Existing
conditions, options, and columns are rendered as compact button surfaces whose
two-pixel outline appears only on hover or keyboard focus; their adjacent add,
reorder, and remove controls use the shared centered icon-button interaction
style.

### FormSettings (`panels/formSettings.mjs`)

The form-level settings panel handles AI schema generation and form access
restrictions.

**AI generation**: A `BaseForm` with a textarea prompt. Submits the current
schema and HTML draft, saved baseline, draft revision and request identity to
`ENDPOINTS.createSchema`. The response contains validated additions and exact-ID
title, placeholder, option-label and column-title updates, plus HTML sidecars.
Unmentioned fields and settings survive. The response is applied as one local
command and remains unsaved; generation writes no Form or content assets.
Generated instruction text may replace an HTML field's content. Existing images
retain their attributes from the submitted draft before final sanitization,
including unsaved size/alignment edits. The builder prompt requests ordinary
Markdown image references; attribute suffixes are parsed instead of displayed
as text. This does not change normal Page document updates: those remain
append-only, with a server-generated source/time quote before each addition.
Successful generation keeps the prompt open and uses the normal submitted
checkmark, clearing the prompt's unsaved marker. The Form's Save icon still
indicates that the generated schema is unsaved. Generation and Undo/Redo do not
add success banners above the model.
Supports an "explain" mode that shows the AI's prompt
interpretation in an Initial Prompt modal. The modal shows only the starting
prompt; later tool or search context is dynamic and is not part of the preview.
Generation is single-flight. Failure leaves its form error visible and releases
the submitter for retry. A changed draft, canceled request or destroyed view
cannot accept a late proposal. Stale-draft feedback retains the prompt for
Regenerate. A no-op response uses the same success checkmark, without a notice,
dirty state, Undo/Redo entry or rebuilding the form and its editors.

Group restrictions and the owner checkbox are local drafts. Save Restrictions
submits the complete snapshot in one PUT, using the standard `BaseForm` spinner
and error state. Adding or removing a group does not autosave. Failed saves keep
the draft available for retry; duplicate submissions share one pending request.

### ConditionPanel (`panels/condition.mjs`)

An overlay panel that opens over the model when editing conditions, options, columns, or the HTML editor. Disables drag-and-drop while open and focuses the model on the selected element.

Opening and closing a panel does not add empty lists to the schema or mark the
Form unsaved. Option, column, visibility and status lists are created only when
the user explicitly adds an entry.

**Save flow**: validates the condition, pushes/updates the schema property, rebuilds settings, and updates the model preview.

### Header (`panels/header.mjs`)

Controls for the form name (inline editable), save button, and preview toggle.

**Form name**: Click to edit, blur or Enter to finish the local edit. Escape reverts. Changes mark the form as unsaved.

**Preview toggle**: Creates a `Renderer` instance with the current schema and renders a live preview of the form. Expands the builder layout and hides the model panel while previewing.

Preview rendering uses a generation guard. A renderer that finishes after a
new toggle or Builder teardown destroys its detached resources and cannot
reopen the preview.
The Preview switch keeps keyboard focus and a visible outline in both states.

**Save button**: Uses `aria-disabled` while the draft matches the saved Form or a
Save is pending. It remains focusable so keyboard focus survives acknowledgement;
the clean-draft and in-flight guards prevent redundant publication. Calling Save
with no changes returns without publishing or rebuilding the open editor.
Save always stays at full opacity. While pending, the standard spinner replaces
the cloud; once settled, the cloud/check reflects the saved state. Only Undo/Redo
fade when disabled.
An edited draft publishes the complete name/schema/HTML/image snapshot, saved
baseline and request identity through one single-flight promise. While pending,
it is aria-disabled and exposes `aria-busy`. The backend recognizes a retry before
consuming its image uploads and rejects a changed saved baseline.
Only an explicit successful response can acknowledge the submitted snapshot;
if the live draft changed in the meantime, later edits remain unsaved. When the
acknowledged content matches the current display, Save retains the model,
settings and open condition/editor, refreshing newly saved restrictions in
place. This preserves unsubmitted option/column buffers and focus. The existing
restore path is used only when server normalization or saved image URLs change
the displayed draft. Copy uses the complete current draft to create a separate
Form with independently owned content, without saving its source.
Failure leaves an error in the Builder's polite live region and releases the
connected button in `finally`, including its accessibility and focus state, so
the same action can be retried. Successful Save marks the button aria-disabled unless newer
edits remain unsaved. Connectivity continues to own whether the save
control is visible. Copy and restriction actions use the same retryable-failure
rule, except successful copy navigation and successful row removal are terminal
and do not restore the old control.

Readonly builders keep the component palette, settings, schema manipulation,
and preview interactions available for exploration. Persistence controls are
omitted, and a persistent notice beneath the title explains that changes will
not be saved. Temporary builder feedback continues to use the separate
notification element.

## Conditions System

Conditions are property editors that open in the ConditionPanel. Each condition type is lazy-loaded from `conditions/loader.mjs`.

### Base Classes (`conditions/base.mjs`)

**`Condition`** -- base class for all condition editors. Creates a target container, header (with help/close buttons), progress section, and submit button. Uses a `BaseForm` for error display and submit state. Manages a `Map<name, element>` of progressive option inputs and a `destroyables` array for cleanup.

**`ConditionTarget`** -- extends `Condition` for conditions that reference another form element (visibility, status). Adds:

- **Target select**: A `SelectBox` dropdown of eligible condition targets (checkbox, radio, select elements)
- **Checkbox target**: For checkbox targets, auto-completes with "is checked"
- **Value chooser**: For radio/select targets, shows a dropdown of their options

### Condition Types

| Type | Key | Extends | Purpose |
|---|---|---|---|
| `Visibility` | `visibility` | `ConditionTarget` | Show/hide element based on another element's value |
| `Status` | `status` | `ConditionTarget` | Display a status message based on another element's value. Adds a text input for the message. |
| `Options` | `options` | `Condition` | Add/edit radio or select options. New options receive a value once; relabeling preserves the existing value. |
| `Columns` | `columns` | `Condition` | Add/edit table columns. New columns receive an ID once; title edits preserve it. Saved column representations cannot change. |
| `HtmlEditor` | `html` | `Condition` | Opens a builder-owned `DraftDocument` rich-text editor and expands the layout. Only initializes once. |

`DraftDocument` reads and updates the builder's HTML state. Images stay in a
browser-local blob registry until Save or Copy; temporary preview URLs are
revoked during teardown. Blur, hide, reconnect and condition destruction do
not publish HTML or initiate document checkpoints. Failed loading preserves
the unavailable state instead of substituting blank content.

### Progressive Disclosure

Conditions use a progressive UI pattern -- each step reveals the next input:

1. Select a target element (visibility/status) or column type (columns)
2. Choose a value or enter a name
3. Submit button appears when `this.complete = true`

The `showProgress()` method is called after each step to check if new inputs should be shown and whether the form is complete.

## Teardown

`FormBuilder.destroy()` is idempotent and owns the complete standalone view
inventory: SearchBox, OfflineModal, Components/Model/Settings/Condition/Form
Settings/Header panels, EntityMenu, active element conditions, draft editors,
local image URLs, and the document click listener. Panel classes remove the exact
delegated listeners they installed and destroy Sortable/combobox/form/modal
children. Conditions destroy their current `BaseForm`, child controls, and
feedback timers; rebuilt column editors replace their exact `updated` handler
instead of accumulating listeners. Async saves and mutation responses may
finish, but re-check destruction before changing connected UI or navigating.

## Config (`config.mjs`)

Static configuration for the builder:

| Key | Description |
|---|---|
| `FORM_COMPONENTS` | Available element types for task forms, including the task-only todo list |
| `PAGE_COMPONENTS` | Available element types for page forms (adds bookmark; excludes html, status, signature, and todo lists) |
| `INPUTS` | Input subtypes (text, tel, number, email, date, time) |
| `TABLE_COLUMNS` | Column types (input types + external link, checkbox) |
| `LINKS` | Link types (external, internal) |
| `DEFAULT_SETTINGS` | Settings list per element type |
| `PAGE_DEFAULTS` | Default `name` and `description` schemas for page forms |
