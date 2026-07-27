# Frontend Builder

The form builder (`src/script/views/builder/`) is a drag-and-drop interface for creating and editing form schemas. It lets users add form elements, configure their settings, set up conditional visibility/status rules, define table columns and select/radio options, and preview the rendered form. The schema is serialized as JSON and submitted to the server on save.

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
  └── Sortable instances (drag-and-drop via SortableJS)
```

The builder is a standalone view -- it does not use the Core/Component/Widget system. It manages its own click handler, element selection, and schema state.

## FormBuilder (`builder.mjs`)

The main controller class. Owns the element map, sortable instances, and all panel references.

### State

| Property | Description |
|---|---|
| `elements` | `Map<id, {item, schema, settings}>` -- all form elements. Order matches the form layout. |
| `selectedElement` | The currently selected element entry from the map |
| `sortables` | `{model, components}` -- SortableJS instances |
| `schemaElt` | Hidden `<input name="schema">` that holds the serialized JSON |

### Initialization

1. Parses the existing schema from the hidden input (or from `data-schema`)
2. For page-type forms, ensures `name` and `description` fields exist (from `PAGE_DEFAULTS`)
3. Creates `ModelElement` DOM nodes and element entries for each schema item
4. Initializes SortableJS on both the components palette and the model panel
5. Sets up the global click handler

### Schema Management

**`updateSchema(silent)`** -- serializes all element schemas (in map order) to JSON and writes it to the hidden input. If the value changed and `silent` is false, marks the form as unsaved.

**`updateSchemaOrder()`** -- rebuilds the elements map in DOM order (defaults first, then model panel children). Called after drag-and-drop reordering.

### Element Lifecycle

**`createElement(schema)`** -- generates a unique ID if needed, creates the `ModelElement` DOM node and settings panels, and adds the entry to the elements map. Returns the DOM element.

**`selectElement(id)`** -- sets `selectedElement`, highlights the item in the model panel, and shows its settings.

**`removeElement()`** -- destroys the selected element (including any conditions), removes it from the DOM and the map, and updates the schema.

### Drag and Drop

Two linked SortableJS groups:

- **Components palette** (`pull: "clone"`, `put: false`): clones element types into the model. The `onMove` handler prevents adding duplicate unique elements (status, signature, bookmark).
- **Model panel** (`pull: false`, `put: true`): receives clones from the palette. `onAdd` creates the real element entry and selects it. `onUpdate` reorders the schema.

### Conditions

**`showCondition(name, index)`** -- loads or retrieves a condition editor for the given schema property (`visibility`, `status`, `options`, `columns`, `html`). Opens it in the condition panel. The `index` parameter determines whether it's creating new (-1) or editing existing.

**`getEligibleConditionTargets()`** -- returns checkbox, radio, and select elements (excluding the selected element) as potential visibility/status condition targets.

## Panels

### ComponentsPanel (`panels/components.mjs`)

The left sidebar showing available element types. Elements are draggable into the model panel.

### ModelPanel (`panels/model.mjs`)

The center panel showing the current form layout. Each element is rendered as a `ModelElement` -- a simplified visual preview (disabled inputs, labels, badges for table columns).

**`ModelElement`** is a registry of factory functions, one per element type. Each creates a styled `<div>` with the element's icon, label, and type-specific preview (input fields, radio buttons, select dropdowns, table column badges, etc.). These are display-only -- the actual form elements are rendered separately for preview.

**Default elements** (`name`, `description` for page forms) appear in a separate panel above the model and cannot be deleted or reordered relative to custom elements.

**`focusItem()` / `blurItem()`** -- when editing a condition, the model focuses on just the selected element (hides others). On close, all elements are restored.

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
methods that update both the schema object and the model DOM.

### FormSettings (`panels/formSettings.mjs`)

The form-level settings panel handles AI schema generation and form access
restrictions.

**AI generation**: A `BaseForm` with a textarea prompt. Submits to
`ENDPOINTS.createSchema` and receives a schema array. New elements are created
and appended to the model. Supports an "explain" mode that shows the AI's prompt
interpretation in an Initial Prompt modal. The modal shows only the starting
prompt; later tool or search context is dynamic and is not part of the preview.

It also wires group restriction selection through `FacetsBox` and updates
restriction rows through the route configured in the template.

### ConditionPanel (`panels/condition.mjs`)

An overlay panel that opens over the model when editing conditions, options, columns, or the HTML editor. Disables drag-and-drop while open and focuses the model on the selected element.

**Save flow**: validates the condition, pushes/updates the schema property, rebuilds settings, and updates the model preview.

### Header (`panels/header.mjs`)

Controls for the form name (inline editable), save button, and preview toggle.

**Form name**: Click to edit, blur or Enter to save. Escape reverts. Changes mark the form as unsaved.

**Preview toggle**: Creates a `Renderer` instance with the current schema and renders a live preview of the form. Expands the builder layout and hides the model panel while previewing.

**Save button**: PUTs the save form data to the server. Disables during save, shows saved/error state.

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
| `Options` | `options` | `Condition` | Add/edit radio or select options. Input for the option label, auto-generates a hashed value. |
| `Columns` | `columns` | `Condition` | Add/edit table columns. Select for column type (from `CONFIG.TABLE_COLUMNS`), input for column name, auto-generates a hashed ID. |
| `HtmlEditor` | `html` | `Condition` | Opens an `IndependentDocument` editor for rich text content. Expands the builder layout. Only initializes once. |

### Progressive Disclosure

Conditions use a progressive UI pattern -- each step reveals the next input:

1. Select a target element (visibility/status) or column type (columns)
2. Choose a value or enter a name
3. Submit button appears when `this.complete = true`

The `showProgress()` method is called after each step to check if new inputs should be shown and whether the form is complete.

## Config (`config.mjs`)

Static configuration for the builder:

| Key | Description |
|---|---|
| `FORM_COMPONENTS` | Available element types for standard forms |
| `PAGE_COMPONENTS` | Available element types for page forms (adds bookmark, removes html/status/signature) |
| `INPUTS` | Input subtypes (text, tel, number, email, date, time) |
| `TABLE_COLUMNS` | Column types (input types + external link, checkbox) |
| `LINKS` | Link types (external, internal) |
| `DEFAULT_SETTINGS` | Settings list per element type |
| `PAGE_DEFAULTS` | Default `name` and `description` schemas for page forms |
