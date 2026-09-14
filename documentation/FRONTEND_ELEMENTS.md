# Frontend Elements

`src/script/elements/` turns a form schema and submission into dynamic read/edit
fields. A `FormElement` widget owns a `BaseForm`; the form owns a `Renderer`;
the renderer lazy-loads one `BaseElement` subclass per schema field.

```text
FormElement widget
  -> BaseForm
       -> Renderer
            -> BaseElement subclasses
```

Form lifecycle, submit state, revision baselines, and uploads are documented in
[FRONTEND_FORMS.md](FRONTEND_FORMS.md). Comboboxes have their own guide:
[FRONTEND_COMBOBOX.md](FRONTEND_COMBOBOX.md).

## Renderer

`elements/renderer.mjs` receives the schema, submission, target, and entity key.
`render()` creates fields through `getFormElement()`, appends them, and wires:

- read/edit toggling;
- clear controls;
- conditional visibility; and
- conditional status messages.

Visibility conditions sharing one trigger ID are alternatives; conditions on
different trigger IDs must all match. One input event computes all resulting
visibility and commits it in one `withTransition()` call. Status text updates
immediately.

The Renderer may replace host children only during `BaseForm.init()`. Server
fragment updates use the full form replacement path so nested editors, uploads,
comboboxes, and listeners have one teardown boundary. `destroy()` removes every
field and renderer listener.

## Loader and base element

`elements/loader.mjs` imports a field class by `schema.type`; unknown types are
errors. `BaseElement` receives the renderer, schema, and submission and lazily
creates its DOM.

| Member | Contract |
| --- | --- |
| `elt` | Complete rendered field. |
| `read` / `edit` | Read and editable surfaces. |
| `mode` | `read` or `edit`. |
| `data` | Submitted `FormData`. |
| `cell` | Optional inline-table HTML. |
| `active(value)` | Condition matching for checkbox/radio/select fields. |
| `clear()` | Explicit reset for fields that need it. |
| `static` | Render even when readonly and empty. |
| `destroy()` | Cleanup registered resources. |

Readonly forms can be sparse or structural. Sparse mode omits empty non-static
fields. Structural mode keeps the labels and displays **Not provided**; active
permission-readonly Task forms use this mode.

## Field types

| Schema type | Class and behavior |
| --- | --- |
| `input` | Text, number, date, time, email, telephone, or URL. |
| `textarea` | Plain text; read mode preserves line breaks and spacing while wrapping long lines. |
| `checkbox` | One boolean control. |
| `radio` | Option group with row or column layout. |
| `select` | `SelectBox` over a native select. |
| `link` | Internal `FacetsBox` reference or external URL. |
| `bookmark` | External URL with fetched metadata. |
| `location` | Google Places through `LocationBox`. |
| `signature` | Canvas capture and uploaded asset. |
| `table` | Inline rows with nested field types. |
| `todo` | Ordered task checklist with add, rename, remove, and completion. |
| `html` | Static rich HTML. |
| `status` | Conditional computed messages. |

Table, Todo, Html, and Status implement their own `create()` because they do
not follow the normal read/edit field shape.

Todo item text keeps the same normal color in checked and unchecked states,
without strikethrough. The checkbox indicates completion in both interactive
and read-only displays.

Location selections are verified through the Places detail endpoint before an
ID is stored. If details are temporarily unavailable, the submitted name or
address and secondary address are retained as free text with a warning; an
unverified provider ID is never persisted.

## Schema values

Common schema keys are `id`, `type`, `title`, `placeholder`, `required`,
`options`, `input`, `visibility`, `status`, `columns`, `layout`, `multiple`,
`location`, and `clear`. The canonical backend contract is in
[BACKEND_ENTITIES_PROPERTIES.md](BACKEND_ENTITIES_PROPERTIES.md#canonical-form-schemas).

Todo values use `{items: [{text, checked}]}`. Enter or forward Tab commits a
nonempty draft and opens a new one; Shift+Tab exits. The history action restores
the latest item text with all checkboxes unchecked. Completion is shown by the
checkbox; item text has no strikethrough in editable or read-only displays.

Empty submission-bearing fields on a reopened Task can restore their most
recent history value. Static HTML, computed status, and signature assets do not
offer that control. Filling changes only the current form and uses its normal
Update/completion flow to save; every uncompletion starts with fresh answer
fields while retaining the attached Form and task settings.

Completed Task forms show their flat current answers with the current Form.
Only a completed Task whose answers changed through a generation conversion shows
editors the warning **This form was modified after this task was completed.**, with
**View Original Submission**. View-only users see neither this notice nor the
archive choices, and the live Task's original-submission endpoint requires edit
access. Completed forms do not show the separate migration **View changes** notice.
That action replaces the displayed form with the original and keeps the warning
visible. Inside it, a **When Reopened** fieldset reveals vertically stacked,
standard site **Archive original submission** / **Archive modified submission**
radios; no modal opens. The link remains available and reuses the loaded original
when clicked again. Original
is initially selected; changing the radio switches the rendered form. The existing
completion checkbox archives the selected submission when reopening. Without
opening the original, manual uncompletion archives the modified submission.
Completed forms have no submit or separate archive button. Ordinary completion
and same-generation schema/content edits show no warning or selection controls.
The history view uses one normal table per Form generation, with newest-first
rows and groups ordered by their newest record. Each table has the standard
column controls and expandable cells, with the same frame and header spacing as
project filter results. There are no per-row completion forms.
Completion and reopening leave the task open in its current list until the server
accepts the change. Errors preserve the open widget and entered values. On success,
one transition replaces it with a closed row and moves it to the appropriate list,
without the new-task highlight animation. The completed section keeps its existing
expanded/collapsed state. Loaded widgets are discarded in both directions; no
history request runs during the transition. The next History click loads the latest
records through the usual lazy-loading route. Ordinary Update saves keep the current
widget open.
Original/history views use the current Form while its generation matches,
so same-generation label and HTML edits remain visible; older generations use
their archived definitions and content. Missing definitions are shown as
unavailable with raw original answers retained for review. History-fill controls
remain available for saved answers whose fields still exist. Clicking one requests
that field's value and applies the deterministic conversion to the current schema.
An unconvertible value returns HTTP 422 with a field-specific error in the form;
other history-fill controls remain usable. Filling changes only the draft and
ignores responses after the field is replaced or the user enters a new value.

## Primitives

`elements/primitives.mjs` owns DOM factories for inputs, labels, badges,
toggles, icons, loading states, and submit/explain buttons. Pass semantic style
and icon IDs rather than raw duplicated class sets or Material glyph names.

Icon-only controls use two layers: the control owns interaction outline and
stacking; its direct Material span owns icon geometry. `icons.css` is the sole
owner of the icon box, glyph size, line height, and optical offsets. Component
styles may position, color, stack, or hide the icon.

## Document editor menus

Document editor toolbar menus use compact icon-and-arrow triggers at every
viewport size, with History last and Align immediately before Insert. History
opens from the start edge of its trigger, subject to viewport collision handling.
Toolbar menu widths depend on their content, capped by the viewport, so moving
a menu does not change its measured width. Shared combobox positioning tries
an alignment flip before shifting into the viewport and retains the configured
preferred placement across resize updates. Title anchoring and minimum title
width remain explicit options used by entity action menus; toolbar menus and
notifications use their own triggers.
Buttons and menus share one wrapping row so each control uses the available
width, including Style and Headings beside the buttons on smaller screens.
Menu glyphs use the standard dropdown size rather than the larger toolbar size.
Lists contains the bullet, ordered, and task list toggles. Table inserts a
three-by-three table with a shaded header row when the
cursor is outside a table; inside a new or pasted table it offers applicable
row/column insertion and deletion actions, Toggle Header Row, and Delete Table.
The header toggle changes the first row, keeping its contents, even when the
cursor is in a body cell. Menu actions
retain the editor selection and use the existing editor commands and autosave.

## Messaging and mention elements

`MessageComposer` is a shared modal form with a single User `FacetsBox`, a
required plain-text body capped at 1,000 characters, and a stable operation ID
across request retry. Existing conversation replies use a separate inline form
whose exact conversation pair is checked by the server.

The editor's `LagniappeMention` atom and `MentionSuggestions` controller own
`@query` search, keyboard/pointer selection, and occurrence metadata. New
occurrences remain in the document's pending checkpoint/offline record until
the server accepts the document save. Readonly/public editors render saved
mentions but do not install suggestions.

## Change checklist

- Keep durable schema normalization on the backend.
- Give every field an explicit data, readonly, clear, and teardown contract.
- Evaluate conditional visibility from normalized values.
- Use primitives and semantic styles for shared DOM roles.
- Put layout/focus/native-event behavior in E2E tests; deterministic field
  algorithms may use the JavaScript suite.
