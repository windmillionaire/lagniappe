# Frontend Forms

`FormElement` and `BaseForm` connect a widget's schema/submission to the
Renderer and own form replacement, submit feedback, unsaved state, offline
state, and committed-revision baselines.

## FormElement

`elements/form.mjs` is the widget base used by PageInfo, TaskSettings,
CreateUser, FileInfo, and similar forms. During `init()` it captures the
server-rendered target, creates `BaseForm`, renders fields, and installs local
read/edit and clear interactions.

It implements the widget lifecycle:

| Member | Purpose |
| --- | --- |
| `data` | Return `BaseForm.data`. |
| `showError()` | Delegate validation display. |
| `created()` / `updated()` | Record authoritative response schema/submission. |
| `prereconcile()` | Render a replacement form against a detached target. |
| `postreconcile()` | Destroy the connected form and commit the prepared target. |
| `markUnsavedState()` / `clearUnsavedState()` | Track local edits independently from server sync. |
| `destroy()` | Destroy the form and owned resources. |

`prepareReset()` builds detached state; `commitReset()` applies it synchronously.
Use those phases whenever the replacement participates in a view transition.

## BaseForm initialization

`elements/base/baseForm.mjs`:

1. finds the submit group/button;
2. creates the Renderer when a schema exists;
3. appends extra HTML and orders Page default fields;
4. removes persistence controls when readonly;
5. restores an `lp-edited-marker` displaced by rendering;
6. configures submit text/icon slots; and
7. watches editable input/change/reset events for unsaved state.

The submit icon occupies a fixed leading slot so unsaved, spinner, offline, and
success states do not shift button text. Primary form actions are full width;
navigation, toolbar, and icon-only controls use separate roles.

## Submit states

`messages.submit`, `messages.submitting`, and `messages.submitted` name the
default, in-flight, and brief success states. Any local edit shows the unsaved
cloud marker. Successful submission or reset clears it. Offline blocking and
queued state take precedence:

- a form without `lp-offline` shows **Server Offline**;
- an opted-in form can show **Queued Sync**; and
- deferred forms remain online-only.

`showError()` inserts one error before the submit action and clears the previous
error. Starting another submit hides it.

## Committed baselines

A marked FormElement retains an in-memory normalized snapshot of its form data.
The baseline is refreshed after initialization and authoritative replacement.
Repeated values compare without order; Files compare by metadata; a widget may
add state deliberately omitted from its HTTP payload.

The snapshot is not persisted or sent to the server. Entity fingerprints and
`modified` remain the server authorities. On an external change, EditWatcher
uses a detached focused response to compare the live draft with saved state.
See [FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md).

## Offline forms

An `lp-offline` form renders authoritative server HTML immediately and does not
wait for IndexedDB. Initial replay starts after view publication. Code that
creates an offline mutation must await `view.ensureOfflineQueue()`.

After replay acceptance, OfflineQueue deletes the stored record and requests a
fresh poll. EditWatcher then applies or reviews the current server form. This
keeps storage hydration and queued metadata out of initial rendering.

Structured Renderer values may be stored as queue metadata but are never added
to an ordinary HTTP submit.

## Uploads

`BaseUpload` prefers resumable browser-to-Storage upload and submits signed
metadata after each object completes. The widget checkpoints successful files
so retry resumes from the first unfinished selection.

When direct upload cannot start, a bounded multipart request may carry at most
five files and 30 MiB total. A selection outside those bounds is not collapsed
into one application-server upload. Internal retry signatures are removed from
metadata before form submission.

## Form replacement rules

- Prepare schema, imports, and nested element state while detached.
- Destroy the connected form before adopting its prepared replacement.
- Re-locate elements after replacement; callers must not retain stale field
  nodes.
- Preserve `lp-edited-marker` and the current entity identity.
- Do not patch individual fields from arbitrary server fragments; use the one
  authoritative form replacement path.
- Protect focused, unsaved, queued, or review-staged forms from collection
  refresh.

## Testing boundary

Use JavaScript tests for deterministic normalization, visibility logic, queue
serialization, and module lifecycle with small platform fakes. Use E2E for real
DOM focus, selection, upload, browser storage lifecycle, template structure,
and server reconciliation. Follow
[TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md).
