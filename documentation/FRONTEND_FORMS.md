# Frontend Forms

`FormWidget` owns the form's widget and revision lifecycle. It composes a
`FormController`, which handles presentation, submit feedback, dirty/offline
state, and reusable controls. Schema-driven forms additionally use
`FormRenderer`; server-rendered forms use the same lifecycle and controller.

## FormWidget

`widgets/base/formWidget.mjs` is the widget base used by PageInfo, TaskSettings,
CreateUser, FileInfo, and similar forms. During `init()` it captures the
server-rendered target, creates `FormController`, renders fields, and installs local
read/edit and clear interactions.

It implements the widget lifecycle:

| Member | Purpose |
| --- | --- |
| `formData` | Return native form fields, with feature-specific serialization and optional direct-upload contributions. |
| `showError()` | Delegate validation display. |
| `created()` / `updated()` | Record authoritative response schema/submission. |
| `prereconcile()` | Render a replacement form against a detached target. |
| `postreconcile()` | Destroy the connected form and commit the prepared target. |
| `markUnsavedState()` / `clearUnsavedState()` | Track local edits independently from server sync. |
| `destroy()` | Destroy the form and owned resources. |

`prepareReset()` builds detached state; `commitReset()` applies it synchronously.
Use those phases whenever the replacement participates in a view transition.
Migration notices and their modals belong to the same prepared state as the form.
Preparation leaves the current notice intact; committing adopts the replacement's
notice, and discarding destroys only the prepared notice. A settings-only update
retains the notice supplied by the server, while saving submission values clears it.

Detached preparation isolates all widget assignments, including feature selector
instances. Committing adopts them and switches their controller callbacks to the
live widget. Replacement preparation is serialized; newer accepted HTML replaces
superseded preparations before one synchronous commit. Failure and discard clean
up prepared resources without destroying the live form. Each attempt starts from
a clone of the authoritative markup, so retries do not reuse partially enhanced
controls.

An `lp-load` form without `loaded` is a shell with its entity/revision marker but
without editable controls. It is initialized only after the focused route supplies
complete HTML with `loaded`. A validated cached response
can fill a cold shell; it does not rebuild an already initialized form. Dirty
background revisions and explicit reset decisions belong to `EditReconciler`.

Completed Tasks with a deleted attached form initially show a warning and
**Load the archived version**. TaskForm fetches and renders that readonly view
inline only after the click, retaining it for the widget lifetime. Reset and
destruction discard the archive renderer and invalidate pending loads. Viewers
can load the saved current submission; original-completion archive choices keep
their existing edit-access gate.

Completed task forms omit `lp-edited-marker`. When a completion has no stored
answers, its form shows **Task was completed with an empty submission**; a missing
attached form retains the separate archived-version prompt. Reopening restores
the editable form and its revision marker.

CreatePage requires a name in the browser, including after selecting an attached
form. The category create endpoint also rejects empty or whitespace-only names
before creating a page.

Task creation retains its draft when closed. Selecting a model task with an
attached form replaces the draft's current form selection, including after
reopening the draft. Selecting a project or a model without a form leaves the
form selection alone. A user can choose a different form after selecting the
model task.

## FormController initialization

`forms/controller.mjs`:

1. finds the submit group/button;
2. creates the FormRenderer when a schema exists;
3. appends extra HTML and orders Page default fields;
4. excludes submit feedback when readonly;
5. restores an `lp-edited-marker` displaced by rendering;
6. initializes declared controls through `forms/controls/loader.mjs`;
7. configures submit text/icon slots; and
8. watches editable input/change/reset events for unsaved state.

## Composed controls

`data-form-control` on the form itself or a descendant declares a reusable
control. The registry uses literal dynamic imports, so forms without these
markers do not load the controls. Each control receives its root and
`{ readonly, onChange }`, implements `init()` and `destroy()`, and belongs to the
controller's destroyables before asynchronous initialization begins. Controls
edit native fields; the enclosing form owns submission and revision state.

- `permission-sections` enhances the HTML from `users/permissions.html`: facet
  selection, new-row templates, removal, and conditional visibility. Hidden
  sections retain their submitted values. Group/Public permission widgets extend
  `FormWidget` directly and live in `widgets/userPermissions.mjs`.
- `access-restrictions` enhances `forms/access_restrictions.html` in Page
  Permissions, User Settings, and the Builder. It manages administrator/group
  mutual exclusion and group rows. Each host keeps its own submission and summary
  behavior. User Settings retains an explicit field allowlist to isolate these
  settings from Page form values and categories.

Permission GET/PUT responses contain complete HTML rather than separate section
JSON. The Users index retains lazy shells; group creation supplies complete HTML
immediately. Native name fields hold rename drafts, while the GroupPermissions
widget updates saved navigation labels and preserves a name edited during a save.

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

Page restriction controls keep administrator and group edits local until
**Save Restrictions**. The request submits the complete local setting, and the
normal form replacement refreshes the saved Page and Form restriction rows.
Unrestricted sources are omitted; when both sources list groups, the summary
explains that a viewer must match at least one group in each set. The same
controls in User Settings save with **Update User Settings**.

Administrator-only access and local group restrictions are mutually exclusive.
Checking **Administrators only** removes the selected local groups from the
draft; saving also clears their stored relationship keys. Unchecking it does
not restore those groups. Selecting a group clears the administrator-only
checkbox. An attached Form's restrictions remain independent.

## Committed baselines

A marked FormWidget retains an in-memory normalized snapshot of its form data.
The baseline is refreshed after initialization and authoritative replacement.
The saved renderer values are refreshed too, including explicit clears. If edits
arrive during an ordinary save request, its accepted submission becomes the
comparison baseline while the later draft remains available for reconciliation.
Repeated values compare without order; Files compare by metadata; a widget may
add state deliberately omitted from its HTTP payload.

The snapshot is not persisted or sent to the server. Entity fingerprints and
`modified` remain the server authorities. On an external change, EditWatcher
uses a detached focused response to compare the live draft with saved state.
See [FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md).

## Revision coordination

`forms/revisions/` owns watched-form revision coordination:

| Module | Responsibility |
| --- | --- |
| `watcher.mjs` | `EditWatcher`: entity/marker discovery, polling subscriptions, acknowledgements, and deferred-operation coordination. |
| `reconciler.mjs` | `EditReconciler`: focused authoritative probes, draft/queued comparisons, and revision resolution. |
| `modals.mjs` | `FormRevisionModal` and `WholeFormRevisionModal`: field or whole-form saved/local choices. |
| `preview.mjs` | `loadRevisionPreview()`: detached form construction through the generic widget loader, using cloned response DOM. |

Views obtain the service through `ensureEditWatcher()` and retain it as
`view.EditWatcher`. The loader awaits the shared polling coordinator and loads
the watcher dynamically. Revision coordination stays outside Core's static
startup closure; there is no forms barrel or shared-facade re-export.

`forms/representation.mjs` provides dependency-free `compatibleField()` and
`incompatibleSchema()` comparisons to both FormWidget and revision UI. The
widget continues to own snapshots, local-state capture/projection, and staged
replacement; those operations do not import revision coordination.

`forms/migrationNotice.mjs` independently installs the informational notice for
saved values converted, cleared or removed by a schema migration. It binds **View
changes** in the shared review bar when present. Its dialog is read-only. The
notice persists through closing/reloading and clears on the next ordinary save/completion.
Its banner/modal and the separately owned review bar belong to FormWidget's
prepared state, not the revision watcher or reconciler. Polling, offline replay,
deferred operations, and collaborative documents keep their existing owners.

## Offline forms

An `lp-offline` form renders authoritative server HTML immediately and does not
wait for IndexedDB. Initial replay starts after view publication. Code that
creates an offline mutation must await `view.ensureOfflineQueue()`.

After replay acceptance, OfflineQueue deletes the stored record and requests a
fresh poll. EditWatcher then applies or reviews the current server form. This
keeps storage hydration and queued metadata out of initial rendering.

Structured FormRenderer values may be stored as queue metadata but are never added
to an ordinary HTTP submit.

## Uploads

`shared/directUpload.mjs` owns direct-upload sessions, resumable chunk transfer,
retry recovery, and progress callbacks. `BaseUpload` and the Form Builder import
that client directly. `elements/upload.mjs` owns upload controls and menus.

`BaseUpload` prefers resumable browser-to-Storage upload and submits signed
metadata after each object completes. The widget checkpoints successful files
so retry resumes from the first unfinished selection.
On drag-and-drop, `BaseUpload` snapshots the dropped `File` objects before its
asynchronous directory check; browser `DataTransfer.files` need not remain
available after the drop handler yields.
Autofill start keeps the current form draft unsaved. Review acceptance records
which AI operation supplied a selected value; the next ordinary Update sends
that selection so the server can attach a staged original only when used.

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
