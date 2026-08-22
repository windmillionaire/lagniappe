# Sync and Polling Architecture

Lagniappe uses one browser polling coordinator for server-state invalidation.
The coordinator batches every due subscription into `POST /l/poll`; individual
features no longer own timers or push registrations.

| Surface | Durable authority | Poll contract |
|---|---|---|
| Entity and focused forms | Datastore entity `fingerprint` and `modified` | `entity`, `form-lock` |
| Collection/list membership | Existing Datastore `site` fingerprints | `channel` |
| Deferred work | `DeferredJob.status_revision`; expiring Redis revision projection is a bounded fast path | `operation` |
| Notification badge/list invalidation | Expiring Redis generation, revision, and membership projection | piggybacked `notification_state` |
| File ingress | Ingress entity fingerprint | `ingress` |
| Collaborative documents | Entity document asset plus revisioned Redis working state | `document` |
| Explicit offline submits | IndexedDB mutation records | replayed on reconnect |

This division is intentional. Entity and collection revisions must survive
Redis loss, so they remain in Datastore. Redis is used for high-churn
collaborative document state and for reconstructable notification membership
and deferred-operation revision hints. Notification bodies and complete job
status remain durable in Datastore. Notification membership may be rebuilt
with one keys-only ancestor query; operation hints are repaired from only the
jobs already tracked by a browser and are periodically reverified. A second
Redis copy of every entity fingerprint would introduce invalidation and
recovery work without improving correctness.

## Browser scheduler

`src/script/shared/polling.mjs` owns all polling for one mounted view. A
subscription has a stable client ID, type-specific fields, and an opaque
`revision` cursor. The coordinator:

- batches at most 64 due subscriptions into one request;
- runs a shared `beforePoll` hook once, allowing document edits to flush before
  their revision is checked;
- permits only one in-flight poll and reuses it only when it already contains
  every subscription requested by an awaited trigger;
- queues an immediate follow-up when an awaited trigger requests a subscription
  outside the active cycle, so initialization cannot complete without its
  requested result;
- provides a non-awaiting enqueue path for reconciliation initiated inside a
  poll callback, preventing a callback from waiting on its own active cycle;
- adds ten-percent jitter to avoid synchronized clients, using one jitter factor
  and one scheduling timestamp per response so subscriptions with the same
  cadence remain in the same request instead of gradually fanning out;
- gives every subscription an explicit `periodic` or `foreground` mode and an
  `immediate` or `scheduled` initial check;
- starts entity and form-lock conflict checks after 15 seconds, then backs them
  off while quiet;
- keeps collection channels foreground-only: they install no idle timer and
  run only in a catch-up cycle;
- polls active documents immediately and every 2 seconds, active ingress
  immediately and every 2.5 seconds, and server-rendered operations first at
  four seconds before their 8, 16, and 30 second quiet backoff. A locally
  started operation still nudges its own descriptor immediately;
- backs transport errors off exponentially to 60 seconds;
- stops ordinary polling when the tab is hidden, the browser window is
  unfocused, or the view is offline. A visible tab in an unfocused window keeps
  only rendered `operation` subscriptions on their normal cadence until they
  reconcile or ten minutes elapse, whichever comes first;
- performs one batched `catchUp()` after visibility, focus, browser-online, or
  server-online recovery. `resume()` only restores scheduled timers.

The existing connectivity health check remains the server-health authority and
drives the offline UI. Its optional `X-Lagniappe-Notification-State` header is
a Redis-only projection read; a miss or Redis failure never changes the health
result. It also stops on window blur; focus performs one health check and one
poll catch-up before the normal long interval resumes.

Native browser `online` and `offline` events publish their browser-link value to
the in-memory connectivity state synchronously, then schedule the asynchronous
health/view cycle. `connectivity.online` therefore remains a plain synchronous
read and is never a rendering prerequisite. Code that explicitly needs the
latest background cycle to finish may await `window.__CONNECTIVITY_READY__`;
Core also exposes `replayReady` for its latest background offline-form replay.
Neither promise participates in view initialization, component rendering, or a
view transition.

### Startup and readiness

Authenticated Core views install interaction handlers before touching storage
or starting a manager. As soon as the concrete view publishes, they start root
polling and component prefetching. SyncManager starts for a document capability;
an idle storage inspection starts SyncManager or OfflineQueue only when persisted
work exists. Visible prefetch and ordinary GET rendering never consult
OfflineQueue. Optional EditWatcher, DeferredOperationManager, and Notifications
warming is capability-gated and idle-scheduled with a one-second maximum delay.

This scheduling is not a correctness delay. Scheduled readiness promises may
resolve to `null` when the current surface has no matching capability or stored
work. Direct consumers call an idempotent `ensureOfflineQueue()`,
`ensurePollingCoordinator()`,
`ensureSyncManager()`, `ensureEditWatcher()`, `ensureDeferredOperations()`, or
`ensureNotifications()` method. All paths share the same single-flight manager
instance. Collaborative documents render their toolbar and editor shell immediately,
then keep editing inert while `initialStateReady` ensures SyncManager and fetches the
initial document state. Hydration establishes a clean baseline: editor setup and
untouched empty documents never produce save payloads, while a user edit (including
intentionally clearing existing content) marks the document dirty and remains
saveable. An accepted checkpoint clears that dirty state unless another local edit
arrived while the save request was in flight.
Offline forms become interactive from server HTML without reading queue state.
Initial replay waits for view readiness. A successful write with a mounted form
triggers a fresh poll cycle instead of directly acknowledging the response; an
already-in-flight poll is not accepted as evidence of the later write. Normal
EditWatcher reconciliation therefore owns the update. Replay also remains
fire-and-forget during reconnect: polling, sync, EditWatcher, and visible refresh
resume without waiting on IndexedDB or queued requests. Public pages do not
create any of these private managers.

### Subscription ownership

Recurring work is owned by the narrowest visible surface that can consume it.
Component rendering schedules a coalesced ownership reconciliation after every
activation or deactivation and returns without awaiting it. The explicit
reconnect path still awaits reconciliation before polling resumes. Visibility
includes the complete component ancestry, so a child that retains its active
selection beneath a closed parent does not subscribe.

| Subscription | Lifetime | Notes |
|---|---|---|
| Root `entity` | Mounted view while focused/visible | Periodic conflict check, first due after 15 seconds. |
| Index collection `channel` | Mounted view while focused/visible | Foreground-only; the rendered opaque poll revision is separate from the raw `/l/refresh` fingerprint. |
| Home collection `channel` | While its owning widget has loaded | `home-notes`, `tasks`, `starred`, `pages`, `projects`, `categories`, `ingress`, and `tool-reports` catch up independently and refresh only their owner. The legacy composite `home` channel remains server-compatible. |
| Notification state | Authenticated ping and any already-needed poll | No subscription or timer. A cold ping miss causes one personal-state seed poll. |
| Watched-form `entity` and `form-lock` | Active visible form widget only | A root form shares the root entity subscription, avoiding a duplicate entity descriptor and Datastore read. |
| `document` | Active visible collaborative document only | Deactivation checkpoints local state, unsubscribes, and explicitly closes presence. |
| `ingress` | Active visible import wizard while its import is running | Hidden running imports retain local running state and catch up when reopened. |
| `operation` | From durable deferred acknowledgement until terminal reconciliation | This is the deliberate widget-visibility exception: completion and notification delivery remain useful when the source widget is closed. Only an operation with rendered progress UI may also retain polling during a visible-window blur, bounded to ten minutes. |
| Offline document replay | One shot during reconnect | It is never a recurring mounted-widget subscription. |

Hidden form widgets retain their own last-seen fingerprint/modified baseline in
memory. The root entity subscription retains the newest observed revision.
When a form becomes active, those values are compared and only a stale form
uses its focused replacement route. Advancing the root DOM fingerprint while a
form is hidden therefore cannot make that form miss an update.

## `POST /l/poll`

The version 1 request envelope is:

```json
{
  "version": 1,
  "client_id": "browser-session-id",
  "subscriptions": [
    {
      "id": "edit:entity-key",
      "type": "entity",
      "key": "entity-key",
      "revision": "known-fingerprint"
    }
  ],
  "closed_documents": [],
  "notification_state": {
    "generation": "known-generation",
    "revision": 12,
    "seed": false
  }
}
```

The envelope is exact: `version`, `client_id`, `subscriptions`, and
`closed_documents` are required, while `notification_state` is optional.
Unknown fields are contract errors rather than compatibility data. Every
descriptor contains `id`, `type`, and `revision`; IDs and closed document IDs
must be unique within their lists.

| Type | Type-specific fields | Revision cursor |
|---|---|---|
| `entity` | entity `key` | null or nonblank opaque string |
| `channel` | allowlisted `channel` | null or nonblank opaque string |
| `form-lock` | entity `key` | nonblank opaque string |
| `ingress` | ingress `key` | null or nonblank opaque string |
| `operation` | deferred-job `key` | non-negative JavaScript-safe integer |
| `document` | entity `key`, document-suffixed `sync_id`, nullable `generation`, nullable `presence_digest` | non-negative JavaScript-safe integer |

String cursors are deliberately opaque; the contract bounds them without
coupling the browser to the server's current hash, UUID, or datastore-key
encoding. Empty strings are invalid where `null` represents an initial cursor.
Document `generation` and `presence_digest` fields remain present with `null`
initial values so missing fields cannot masquerade as an intentional initial
state.

Notification state has only two request modes: a cold seed is
`{generation: null, revision: null, seed: true}`, while a warm cursor has a
nonblank generation, a non-negative JavaScript-safe integer revision, and
`seed: false`.
Omitting the field means notification state was not requested.

The browser validates and canonicalizes descriptors at registration and again
at the request boundary. A first-party producer defect is captured once and
that descriptor is isolated from unrelated polling. The server independently
enforces exact fields, cursor types, channel/type allowlists, document suffixes,
uniqueness, and size bounds because the HTTP boundary remains untrusted. An
invalid request returns a safe structured `422` with
`code: "invalid_poll_contract"`, a field `path`, and a reason category; rejected
values are never echoed or reported to server-side error tracking.

Each result has the same outer contract:

```json
{
  "id": "edit:entity-key",
  "type": "entity",
  "status": "changed",
  "revision": "new-opaque-revision",
  "poll_after_ms": 15000,
  "payload": {}
}
```

`status` is one of:

- `unchanged`: the cursor is current and no payload is needed;
- `changed`: the new cursor and typed payload are present;
- `unavailable`: the object is missing or no longer visible to this user;
- `error`: this descriptor failed without failing the rest of the batch.

The coordinator also validates the result set before applying cursors: every
requested ID must appear exactly once with the matching type, a positive
`poll_after_ms`, and the cursor type declared above. `changed` requires an
object payload, `unchanged` carries no payload, and `unavailable`/`error` carry
neither a revision nor a payload. A malformed or missing result is captured and
converted to a retryable error for only its subscription. Document generation
and presence cursors are validated before they can update coordinator state.

Typed payloads are deliberately narrow:

| Type | Identifier | Changed payload |
|---|---|---|
| `entity` | `key` | `fingerprint`, `modified` |
| `channel` | allowlisted `channel` | `refresh: true` |
| `form-lock` | entity `key` | lock state and operation identity |
| `operation` | deferred-job `key` | owner-safe status projection |
| `ingress` | ingress `key` | `refresh: true` |
| `document` | entity `key` and `sync_id` | generation, revision, snapshot/deltas, presence |

Payload routes still exist for focused HTML or large content. Polling tells a
mounted consumer that its contract changed; the consumer then uses its normal
authoritative replacement route. This keeps `/l/poll` bounded and prevents it
from becoming a second rendering API.

### Channel revisions

Collection revisions reuse batched `database.site_fingerprints()` reads. Entity
saves already update these durable records in the same persistence workflow.
Only paths for mounted channels are loaded. Home uses one channel per loaded
widget so a changed Tasks fingerprint cannot reload Notes, Pages, or Projects;
the composite `home` channel remains only for older cached clients. Personal
channels use state already present on the directly loaded request user where
that is the narrower authority:

- `starred` uses the user revision;
- `tool-reports` uses report and user revisions.

Permission fingerprints are part of each channel revision, so a permission
change invalidates the viewer's collection even when membership did not change.
Operation-only user revision patches do not change the user's `modified`
fingerprint, refresh its Redis search cache, or invalidate the global users
collection. Notification mutations do not write the User or any site
fingerprint at all.

## Collaborative documents

Documents are the only live collaborative widgets. Forms do not register
presence or send field patches.

A document subscription includes:

```json
{
  "id": "document:page-hash:document",
  "type": "document",
  "key": "entity-key",
  "sync_id": "page-hash:document",
  "generation": "redis-generation",
  "revision": 12,
  "presence_digest": "opaque-digest"
}
```

Redis uses three keys:

| Key | Contents |
|---|---|
| `Sync.DOCUMENTS:{sync_id}` | Isolated JSON state: generation, revision, base revision, checkpoint, deltas, bounded author projections, asset fingerprint |
| `Sync.PRESENCE:{sync_id}` | Client IDs currently viewing one document |
| `Sync.CLIENTS` | Expiring client-to-user projections |

Document keys expire after five minutes; client presence expires after one
minute unless refreshed by the 2-second document poll. Redis loss creates a new
generation seeded from the durable entity document asset.

### Revisions, deltas, and checkpoints

`POST /l/sync` appends Yjs deltas under a Redis optimistic transaction. Each delta
gets a monotonically increasing revision. A client receives:

- a full snapshot when its generation differs or its cursor predates the
  compacted base revision;
- only deltas newer than its revision otherwise;
- a presence list only when its presence digest changed.

Each retained delta includes its author hash. Poll responses also include the
minimal `{hash, name}` projection for authors referenced by the returned
revisions, allowing transient colorization and attribution even after live
presence has closed. Author projections are pruned with the checkpoint/delta
window; they are not durable edit history. When an already-connected client
falls behind a newly compacted checkpoint, the snapshot carries an author only
when every compacted revision has that same author, so the transient highlight
is not attributed to mixed-author work. Initial clients and clients entering a
new Redis generation receive no historical author attribution.

A full Yjs checkpoint is accepted only when the submitted generation and
revision match the current Redis state. Stale writers may still append their
commutative Yjs delta, but cannot replace the checkpoint. The client then keeps
its old cursor, polls all missing concurrent deltas, and retries a merged
checkpoint. A rejected explicit save remains in IndexedDB until that retry is
accepted. This prevents both skipped concurrent edits and Redis-only data loss.

The client retains the last accepted generation/revision independently of its
active presence subscription. Edits made after an offline transition therefore
store the originating cursor with their IndexedDB checkpoint. IndexedDB keeps
one coalesced record per document: a compact Yjs state/update plus the latest
HTML checkpoint, not an indefinitely growing edit log.

A later headless replay uses the stored cursor for a one-shot document poll,
applies the returned snapshot or newer deltas, and then applies the compact
offline Yjs state. It submits that merged checkpoint against the cursor returned
by the poll. If another writer wins the poll-to-save race, Redis still appends
the commutative local delta but rejects the stale checkpoint; the compact record
remains in IndexedDB for another poll-and-merge pass. The record is removed only
after Redis accepts the merged checkpoint.

New document mention occurrences travel with that same coalesced checkpoint
and offline record. The server considers them only after the checkpoint was
accepted and the Page/Project document asset was durably saved. It then verifies
that each occurrence still exists in saved HTML, reloads the recipient, checks
current mention and recipient document-`VIEW` authorization, and transactionally
creates a deterministic `MentionMarker`, ordinary Notification, and aggregate
increment. The marker survives Notification deletion, so replay cannot deliver
the same occurrence twice. Public responses and site exports replace internal
mention nodes with inert `@Display Name` text before further sanitization.

After 64 retained deltas, the poll response asks an editable client for a
checkpoint. Explicit editor blur also sends a checkpoint and HTML. Accepted
checkpoints persist the document asset/history through a property-masked write;
they do not advance or overwrite the parent entity's `modified`, fingerprint,
form submission, or other sibling fields. The document asset fingerprint and
Redis revision remain the document-sync authorities.

The client remembers documents with a persisted checkpoint whose parent has
not yet been advanced. Document-widget deactivation, window/tab hide, and
navigation send one `touch_parent` lifecycle update. That update either combines
the checkpoint with masked parent/list-owner `modified` writes or, when the
checkpoint was already persisted on blur, sends a touch-only update. This makes
the changed Page visible to Category/list polling without turning every live
document checkpoint into a form conflict. Offline records retain this lifecycle
intent and coalesce document state rather than retaining individual edits.
Redis remains disposable working state.

`closed_documents` removes presence during widget deactivation, window blur,
tab hide, navigation, and teardown. The client first detaches the document
subscription and waits for any active poll before sending the close, so a late
presence refresh cannot recreate the entry. Stale presence also disappears
through field expiry if a browser closes without running cleanup.

## Committed form edits

`EditWatcher` discovers fingerprinted `[lp-entity]` markers, records a separate
baseline for every marker, and installs `entity` plus `form-lock` subscriptions
only for active visible form widgets. A watched form for the view's root entity
consumes the root `view:entity` result instead of installing a duplicate
descriptor. On an entity change it fetches only stale active markers through
their focused replacement routes and follows the existing reconciliation
rules:

- inactive forms perform no polling or replacement request and catch up when
  activated;
- visible active widgets enter revision review even when clean;
- equivalent baselines acknowledge automatically;
- schema drift projects the local draft through the latest schema;
- renderer-capable value drift offers per-field saved/local choices;
- non-renderer dirty forms offer reset/reload;
- unsafe or unavailable replacements fall back to a full reload.

Mutation responses still carry `X-Lagniappe-Entity-Revisions`, allowing the
originating tab to acknowledge its own successful edit immediately.

An active `DeferredJobLock` disables the owned Page/Task form. Other tabs learn
about it through `form-lock`, subscribe to its `operation`, and reconcile the
authoritative form when the job becomes terminal. A clean form applies its own
terminal operation result even while active, but only when the operation
identity matches its durable lock; unsaved and queued forms retain normal
revision review. An unlocked result also reconciles a form that still shows a
stale lock. Replacement probes are serialized per marker and revision so
identical overlap shares one request and a newer follow-up cannot invalidate an
earlier authoritative response.

## Deferred operations and notifications

Deferred job state is durable and correctness no longer depends on a delivery
attempt. `operation` polling returns `status_revision`, phase, elapsed time,
retry timing, terminal state, and bounded destination metadata. The manager
reconciles the configured entity/widget route when terminal and then removes
the subscription. Pending report lists do not run a second refresh timer; their
operation marker is the sole automatic completion authority.

Window blur remains a soft exception only while the browser reports the actual
tab visible. The coordinator dynamically admits operation subscriptions whose
progress marker is connected and rendered, while document, ingress, entity,
form-lock, collection, and notification-only polling remain suspended. The
original blur starts one ten-minute deadline that reconnects and newly tracked
operations cannot extend. A terminal reconciliation removes the operation and
ends the exception early; tab hiding, pagehide, or focus loss followed by an
offline state still prevents requests. Focus clears the exception and performs
the normal full catch-up.

Notifications remain durable entities. Each user also has one deterministic
aggregate Notification containing exact `ordinary_count` and
`unread_message_count` values plus revision/generation data. Badge/list
invalidation uses an expiring Redis projection containing those counters and
one membership field per ordinary notification key, plus a separately watched
epoch key. The public count is the sum of the durable counters; bodies and
message history are never cached there. Both Redis keys use a sliding
30-minute expiration.

The pure Redis wire/request-state codec lives in
`tools/cache/notification_state.py`; watched Redis transactions live in
`tools/cache/notifications.py`. Durable counters and ordinary membership are
owned separately by `tools/database/notifications.py`, so neither cache module
is a transaction authority for application data.

A cold seed watches the projection and epoch, records the epoch, performs one
keys-only notification ancestor query, and publishes only if neither watched
key changed. Concurrent creates, content updates, and deletes increment the
epoch and force a retry. After a durable notification mutation, one post-commit
effect upserts or removes membership and advances the revision once. If the
projection is absent, it advances only the epoch and leaves the next poll to
seed; Redis failure is reported but never rolls back the durable write. Opening
`/l/notifications` instead performs one bounded, newest-first ordinary query
with a limit of 25 and an opaque cursor, reads the aggregate by deterministic
key, and uses the returned ordinary keys for batch hydration. It performs no
Message or MessageConversation query. Additional ordinary queries occur only
when the user selects Load older.

`/l/ping` reads the signed session user key without activating Flask-Login and
peeks only at Redis. A warm state slides expiration and is returned in
`X-Lagniappe-Notification-State`; a miss is reported with null fields. The
browser folds that miss into the next `/l/poll`, or sends one personal-state-only
poll when no channel is otherwise due. Document, ingress, operation, and
foreground catch-up requests carry the last notification cursor, so warm checks
add no notification Datastore read. A changed state updates the badge and marks
an already-loaded menu stale; the list refreshes immediately only while open
and otherwise waits for its next opening.

Each client-visible deferred status revision publishes a separate per-job
Redis hash after its durable transaction commits. The hash contains schema,
status revision, terminal state, and the time that revision was last verified
against Datastore; it slides for 30 minutes but the verification timestamp does
not slide on a read. Server-rendered descriptors start with the job revision
and bounded current status, hydrate that status into the browser cache, and
wait four seconds for their first check; locally started operations nudge
immediately. A matching owner projection younger than 60 seconds returns
`unchanged` without loading the job. Misses, mismatches, and verification-due
entries load only operation keys tracked by that browser in batches of 50 and
repair the projection. Collaborator checks always load the durable job to
enforce current authorization. When a poll also checks notifications, their
separate physical keys share the same Redis pipeline. User entities carry no
polling cursors.

## Offline submissions

`OfflineQueue` remains separate from collaborative document sync. Only forms
with `lp-offline` and an `offline(context)` method opt in. IndexedDB stores the
complete user-authorized command, its entity fingerprint/modified precondition,
structured renderer values, ordinary fields, and files.

Reconnect replays commands in order. A fingerprint mismatch retains the command
and uses `EditWatcher`'s schema/value reconciliation. When that reconciliation
can safely project the queued form onto the newer entity, the queue persists the
rebased fingerprint and retries it inside the same ordered replay; a conflict
that still needs a user choice remains queued. Local drafts that were never
submitted are not durable. After the server accepts a command, the queue deletes
it from IndexedDB and live queue lookups before broadcasting the entity revision
or replay-success UI phase. Reconciliation therefore cannot mistake the
committed command for a still-queued mutation.

## Service worker boundary

The service worker handles application caching and receives only the versioned
connectivity-state message. It has no `push` listener and does not relay server
state to windows. Browser protocol version 3 intentionally contains no public
server events.

## Extending polling

Prefer an existing type whenever its payload contract fits. A new type should
be added only when it needs a distinct permission check, cadence, or bounded
payload:

1. add and validate its descriptor in `home/poll.py`;
2. return the common result envelope with an opaque revision;
3. add one coordinator subscription in the owning component;
4. use an existing focused route for large HTML/data;
5. add backend authorization/contract coverage and a Node scheduler/consumer
   test;
6. document its authority and inactive-tab behavior here.

Do not add feature-owned intervals, service-worker event relays, or Redis
copies of durable entity metadata. Reconstructable projections such as the
notification membership hash must define their authoritative seed and
mutation-race contract explicitly.
