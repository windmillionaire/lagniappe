# Sync Architecture

The application deliberately uses different state mechanisms for documents,
forms, and explicit offline submissions:

| Surface | Mechanism | Meaning |
|---|---|---|
| Documents | `SyncManager` + Yjs + Redis + FCM | Live collaborative editing and offline document-delta replay |
| Forms | `EditWatcher` + entity fingerprint/modified stamps | Local drafts with schema notices and explicit saved-value reconciliation |
| Offline submits | `OfflineQueue` + IndexedDB | Complete user-authorized submit commands replayed when online |
| Autofill ownership | `DeferredJobLock` + `EditWatcher` | Durable exclusion while an existing Page/Task autofill job runs |

Forms do not register presence, send field patches, merge Redis submissions, or
participate in `/register`, `/sync`, `/state`, or `/deregister`. This avoids
conflicts between local drafts, deliberate submits, and deferred autofill while
preserving the two behaviors users need independently: committed-change notices
and explicit offline submit/replay.

> **Push transport note.** Google App Engine installations do not provide the
> WebSocket topology this application would need. Document collaboration uses
> FCM multicast for update notification, with the existing fetch fallback for
> payloads above the provider limit. Form correctness does not depend on FCM.

---

## Document collaboration

### Document sync IDs

A collaborative document has an ID ending in `:document`, such as
`page_hash:document`. Page and Project expose only their document reference in
`entity.sync_ids`:

```python
{
    "document": {
        "id": page.properties.document.sync_id,
        "fingerprint": page.properties.document.fingerprint,
    }
}
```

Templates put the reference on `CollaborativeDocument`:

```html
<div data-widget="CollaborativeDocument"
     lp-sync="{{ page.sync_ids.document.id }}"
     lp-fingerprint="{{ page.sync_ids.document.fingerprint }}">
</div>
```

No form template should carry `lp-sync`, `lp-fingerprint`, or `lp-version` for
collaborative form state. The durable fingerprint on the surrounding
`[lp-entity]` remains the committed form-revision signal.

### Client flow

`src/script/shared/sync.mjs` discovers initialized widgets with a `syncId`.
Documents are the only producers, and the manager contract is:

```text
register()       join document presence and reconcile document offline records
state(widget)    fetch one document snapshot and co-viewers
sendUpdates()    batch Yjs deltas or explicit HTML saves
receiveUpdate()  apply a pushed delta or fetch the document snapshot
deregister()     flush the final document save and remove presence
```

`CollaborativeDocument` supplies:

- `syncData`: a merged Yjs update plus full encoded Yjs state;
- `saveData`: encoded state, any pending update, and saved HTML;
- `sync()`: remote update, offline state, and authoritative snapshot handling.

The view still creates a tokenless `SyncManager` when messaging is unavailable.
That path supports state fetches and the existing tokenless personal-document
save exception without registering presence.

Core starts messaging without awaiting it. Its `syncReady` promise resolves
after the token or state-only path has created the manager, and only
`CollaborativeDocument` waits for that promise before requesting `/state`.
Registration remains a background startup action because it also reconciles
offline document records through headless document widgets. A manager that
finishes initialization while its view is hidden does not register presence.

### Server routes

The routes in `lagniappe/web/routes/home/sync.py` accept document IDs only.
Form-shaped updates receive `422 Only document widgets may use live sync.`

`POST /register`:

```json
{
  "token": "<fcm token>",
  "active": [
    {
      "key": "<entity key>",
      "sync_id": "page_hash:document",
      "fingerprint": "<asset fingerprint>"
    }
  ],
  "offline": []
}
```

The response contains only document snapshots whose server fingerprint differs:

```json
{
  "modified": [
    {
      "key": "<entity key>",
      "sync_id": "page_hash:document",
      "ydoc": "<base64 state>",
      "fingerprint": "<asset fingerprint>",
      "users": []
    }
  ]
}
```

`POST /sync` accepts a batch of document updates:

```json
{
  "token": "<optional fcm token>",
  "updates": [
    {
      "key": "<entity key>",
      "sync_id": "page_hash:document",
      "fingerprint": "<asset fingerprint>",
      "update": "<base64 Yjs delta>",
      "ydoc": "<base64 Yjs state>",
      "html": "<saved HTML when explicitly saving>",
      "save": true
    }
  ]
}
```

`POST /state` accepts one document descriptor. `POST /deregister` accepts the
token and the document `sync_ids` joined by that view.

### Redis state

`lagniappe/core/tools/cache/sync.py` stores only collaboration/presence state:

| Key | Contents |
|---|---|
| `Sync.WIDGET:{sync_id}` | Tokens registered for one document widget |
| `Sync.ENTITY:{entity_hash}` | Tokens viewing an entity, also used by delete broadcasts |
| `Sync.USERS` | Token-to-user projection with expiring fields |
| `Sync.STATE` | Document sync ID to encoded state/fingerprint/timestamp |

The five-minute TTL is refreshed by active registration and state work. Cache
state remains recoverable from the document entity; Redis is not authoritative
storage.

### Offline document deltas

The IndexedDB `sync` store remains for document deltas/saves. On registration,
`SyncManager` filters records to IDs ending in `:document`.

Mounted and headless `CollaborativeDocument` instances use the same replay
path. A record is deleted only after its replay batch is accepted.

---

## Form state

### Local drafts

`FormElement` and `Renderer` are local rendering/submission components. They do
not expose the live-sync widget contract and do not fetch `/state` during
initialization. Ordinary edits update the rendered controls and generic
unsaved-state indicator until the user deliberately submits or resets.

Authoritative server responses still use the form's normal reset lifecycle:

1. `updated(response)` stores replacement HTML and any schema/submission data.
2. `postreconcile()` calls `reset()`.
3. `BaseForm` and `Renderer` rebuild the complete surface, including nested
   controls and uploads.

Reconciliation uses that same full reset boundary. A local draft can be
projected through the latest server schema before the reset: retained field IDs
keep local values, fields added by the new schema keep the server value, and
removed fields disappear. The client never selects or persists an alternate
schema version; historical schemas remain owned by form history.

### Committed edit detection

Forms that should notice changes elsewhere render `controls.edited_marker(...)`
inside a fingerprinted `[lp-entity]` anchor. Current marked form surfaces
include PageInfo, TaskForm, TaskSettings, CategoryInfo, and the other focused
settings forms documented in `FRONTEND_VIEWS.md`.

`EditWatcher` posts at mount, foreground/reconnect, and every 15 seconds:

```json
{
  "entities": [
    {"key": "<entity key>", "fingerprint": "<committed fingerprint>"}
  ]
}
```

`POST /edited` checks at most 32 unique, authorized entities and returns two
independent lists:

```json
{
  "edited": [
    {
      "key": "<entity key>",
      "fingerprint": "<new fingerprint>",
      "modified": "<entity modified ISO timestamp>"
    }
  ],
  "operations": [
    {
      "key": "<entity key>",
      "locked": true,
      "scope": "form-autofill",
      "operation": "<deferred job key>",
      "revision": 4
    }
  ]
}
```

For a changed fingerprint, the watcher fetches the marker's focused replacement
route and builds detached revision previews. Fingerprint drift detects both
entity and attached-form changes. Reconciliation depends on current local state
and on whether both revisions expose a renderer, non-empty schema, and structured
submission:

- clean form: apply the authoritative replacement immediately;
- baseline equals remote or local and remote are equal: acknowledge the new
  baseline automatically;
- renderer-capable schema drift: project the draft through the latest schema
  and show a schema-update notice, with no historical schema choice;
- renderer-capable submission drift: show **Review values**, rendering only
  changed fields side by side through the latest schema; saved values are
  selected by default, and each field can be switched to the tab/queued value
  before **Update values**;
- dirty non-renderer form: show inline **Reset form**;
- queued non-renderer form: offer a compact whole-form saved-versus-retry choice;
- unavailable or unsafe replacement: show **Reload page**.

Foreground/reconnect waits for this immediate watcher pass before collection
refresh. It retains the pre-check root fingerprint for the batched collection
request, so the watcher cannot accidentally suppress task/table deltas. Only
widgets with `refreshScope = "collection"` participate; forms are excluded.
PageTaskList row replacement also skips dirty, queued, or staged-review forms.

This comparison is why CategoryInfo can use the category's existing durable
fingerprint. Page-list membership may touch that same category fingerprint, but
unchanged CategoryInfo form data suppresses the irrelevant notice. No separate
category-form revision is required.

Successful mutation responses carry `X-Lagniappe-Entity-Revisions`. The request
wrapper dispatches fingerprint and modified acknowledgements so the watcher
advances baselines without waiting for the next poll.

---

## Server-change invalidation and collection refresh

The browser protocol uses the version 2 `server-change` event. Producers send
identifiers and routing metadata, never mutable entity fields. The parser
requires the exact protocol ID and version.

`Core.reconcileChange()` coalesces concurrent changes. For each batch it:

1. applies immediate control-only state such as star/unstar and search-cache
   invalidation for deletes;
2. invalidates the changed entity keys through `EditWatcher`;
3. refreshes only explicit collection widgets;
4. runs narrow view hooks for supplemental collections or workflow UI.

File extraction and summary events contain only `{type, key}`. `FileInfo` is a
normal watched form, so a clean form fetches and remounts its authoritative
focused response. The File view's extraction hook only reveals the reload-text
notice when the text tab was not mounted; it does not patch file metadata.
Deferred completion with an operation reference nudges the authoritative
operation coordinator, which performs its own revision-aware destination fetch.

---

## Offline submit and replay

Offline form submission is owned by `OfflineQueue`, not `SyncManager` or
`EditWatcher`.
Only a form with `lp-offline` and a widget `offline(context)` method opts in.
PageInfo, TaskForm, and CategoryInfo use deterministic update record IDs so a
later explicit offline submit replaces the earlier queued command for the same
entity.

Core awaits queue hydration so every consumer sees the durable record set, but
does not await the initial online replay. An `lp-offline` form waits on the
tracked replay promise immediately before restoring queued values. This avoids
mounting stale queued state if replay succeeds while the widget itself is still
initializing; replay failures and conflicts retain the record for normal form
restoration and review.

`OfflineQueue.queueSubmit()` serializes the complete `FormData`, including
files, into the IndexedDB `mutations` store:

Database version 5 stores explicit submissions in `mutations`.

```json
{
  "id": "update:page:<key>",
  "action": "update",
  "kind": "page",
  "method": "PUT",
  "route": "/pages/<key>/update",
  "target_key": "<key>",
  "fingerprint": "<entity fingerprint when submitted>",
  "modified": "<entity modified ISO timestamp when submitted>",
  "renderer_submission": {"field-id": "structured form value"},
  "form_controls": [],
  "fields": [["name", "Offline edit"]],
  "files": [],
  "created_at": 1780000000000
}
```

The fingerprint and modified stamp are replay preconditions/reconciliation
metadata. `renderer_submission` is likewise internal mutation metadata: the
renderer packages its fields in the same structured `form_value` shape used by normal
schema/submission rendering. `form_controls` retains selected option details for
non-renderer facets. Neither field is added to the replay request.

When an offline-capable update form mounts, it looks for a queued PUT command
for the same entity and route. The cached/server form is rendered first and
kept as the `EditWatcher` revision baseline. A second render then overlays the
saved ordinary fields/files, non-renderer facet selections, and structured
renderer submission. The submit control returns to **Queued Sync**. This also
means reset or cached offline reload restores the explicit queued submission,
not the older cached values.

When online, replay reconstructs `FormData`, adds `offline=True` and, when the
record has one, `offline-fingerprint`, then calls the original route/method.
Page and Task update routes compare that fingerprint before applying any mutation. An
unchanged fingerprint replays normally. A mismatch returns the latest focused
form response and leaves the mutation record durable.

The same `EditWatcher` reconciliation boundary handles that response. An equal
saved `modified` stamp on a renderer-capable form means schema-only drift: the
queued values are projected into the latest schema, called out, rebased to the
current fingerprint, and replayed after confirmation. A later renderer value
change shows only differing queued and saved fields, with the saved value
selected initially for each. A queued form without renderer/schema/submission
capability instead offers one whole-form choice: retry the queued version or use
the saved version. Keeping any queued values rebases the complete command
(preserving IndexedDB files) and replays it; accepting the saved version cancels
the queued command. Failed or repeatedly conflicting commands remain queued.

This is intentionally submit semantics rather than draft semantics:

- an explicit offline submit survives reload and reconnect;
- cached form HTML is overlaid with that submitted version while it is queued;
- a local draft that was never submitted is not durable;
- an update command is complete and ordered, not a stream of field patches;
- create commands use unique IDs while update commands may coalesce by entity.

Deferred AI subforms remain online-only. A normal CreatePage autofill is tracked
as a deferred create operation, but it does not use the update-form offline
queue described here.

---

## Deferred autofill ownership

Existing PageInfo and TaskForm autofill jobs acquire a deterministic
`DeferredJobLock` in the same Datastore transaction that creates the job. The
lock stores target, operation, idempotency key, and scope; it has no sync ID or
Redis dependency.

While active:

- mutation routes reject conflicting full form submits, direct uploads, and
  form-field quick edits with a structured `409` response;
- the originating tab locks immediately from the deferred response;
- `/edited` exposes the active operation on reload and to other mounted tabs;
- `EditWatcher` calls `FormElement.lockDeferredOperation()` and registers the
  operation with `DeferredOperationManager`;
- the whole form is disabled and the full submit/context area is replaced by
  one progress control;
- status polling remains authoritative; push only accelerates it.

Terminal cleanup uses compare-and-delete so an old worker cannot remove a newer
operation's lock. Successful terminal reconciliation fetches authoritative form
HTML through the configured deferred replacement route and clears the progress
state by replacing the locked form.

CreatePage autofill explicitly sets `lock_target=False`. The new Page is not an
already-mounted shared edit surface, so the job keeps idempotency, status,
notification, and form-revision drift validation without creating a target
lock. The source CreatePage still shows deferred progress.

---

## Choosing a mechanism

- Use document sync only for a Yjs-backed collaborative asset.
- Add `lp-edited-marker` plus a focused GET replacement route when a form needs
  committed-change detection.
- Add `lp-offline` plus `offline(context)` when an explicit submit should queue
  through `OfflineQueue`.
- Use `DeferredJobLock` when background work must exclusively own an existing
  entity mutation surface.
- Do not add ordinary form controls to `SyncManager` or Redis state.
