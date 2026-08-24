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
| `textarea` | Multiline text. |
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
the latest item text with all checkboxes unchecked. Todo values do not become
repeating Task defaults.

Empty submission-bearing fields on a reopened Task can restore their most
recent history value. Static HTML, computed status, and signature assets do not
offer that control.

## Primitives

`elements/primitives.mjs` owns DOM factories for inputs, labels, badges,
toggles, icons, loading states, and submit/explain buttons. Pass semantic style
and icon IDs rather than raw duplicated class sets or Material glyph names.

Icon-only controls use two layers: the control owns interaction outline and
stacking; its direct Material span owns icon geometry. `icons.css` is the sole
owner of the icon box, glyph size, line height, and optical offsets. Component
styles may position, color, stack, or hide the icon.

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
