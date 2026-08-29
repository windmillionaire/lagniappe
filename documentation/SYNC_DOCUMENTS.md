# Collaborative Document Sync

Collaborative Page and Project documents use Yjs in the browser, revisioned
Redis working state, and durable entity assets/checkpoints. Forms do not use
this protocol.

## Browser components

`CollaborativeDocument` owns the TipTap/Yjs editor. `SyncManager` owns state
loading, `/l/sync` writes, `document` polling, IndexedDB document records, and
headless replay.

The editor renders its shell immediately but remains inert until
`initialStateReady` loads the initial document state. Hydration creates a clean
baseline. Setup and untouched empty content do not produce a save; a user edit,
including clearing content, marks it dirty.

A document subscription contains entity key, `sync_id`, Redis generation,
revision, and presence digest. Only an active visible document subscribes.
Deactivation checkpoints local work, detaches the subscription, and closes
presence.

## Redis working state

Redis uses isolated keys per document:

| Key | Contents |
| --- | --- |
| `Sync.DOCUMENTS:{sync_id}` | Generation, revision, base revision, checkpoint, bounded deltas, author projections, and asset fingerprint. |
| `Sync.PRESENCE:{sync_id}` | Client IDs viewing that document. |
| `Sync.CLIENTS` | Expiring client-to-User display projections. |

Document state expires after five minutes. Presence fields expire after one
minute and are refreshed by the active two-second poll. An existing document
poll reads the state and refreshes its TTL with one Redis `GETEX`; it does not
enter an optimistic transaction or rewrite the full document. When working
state is absent, the poll enters the normal isolated transaction to create one
new generation from the durable document asset. Document updates and asset
refreshes continue to use optimistic transactions.

## Deltas and checkpoints

`POST /l/sync` appends Yjs deltas under a Redis optimistic transaction. Every
delta receives a monotonic revision. Polling returns:

- a full snapshot when generation differs or the cursor predates compaction;
- only newer deltas otherwise; and
- a presence list only when its digest changed.

Each delta records an author hash, and a response includes only the minimal
name projection needed for temporary highlight attribution. Author data is
pruned with the delta window and is not durable edit history. A compacted
snapshot carries one author only when every compacted revision shares that
author.

A submitted checkpoint is accepted only for the current generation and
revision. A stale writer may append its commutative delta but cannot replace
the checkpoint. It keeps its cursor, polls missing deltas, merges, and retries.
This prevents both lost concurrent edits and Redis-only state.

After 64 retained deltas, the server requests a checkpoint from an editable
client. Editor blur can also send one. Accepted checkpoints persist document
asset/history through a property-masked entity mutation and refresh Redis
metadata without touching the parent's ordinary form fingerprint.

## Offline document records

IndexedDB stores one coalesced record per document: compact Yjs state/update,
latest HTML checkpoint, originating generation/revision, mention occurrences,
and pending parent-lifecycle intent. It is not an edit log.

Headless replay:

1. polls once from the stored cursor;
2. applies the returned snapshot or deltas;
3. merges the compact offline Yjs state;
4. submits the merged checkpoint against the returned cursor; and
5. deletes the IndexedDB record only after checkpoint acceptance.

If another writer wins between poll and save, the delta is still appended but
the checkpoint is rejected, leaving the compact record for another pass.

## Parent lifecycle

Document checkpoints do not advance Page/Project `modified` on every save.
The client remembers that a durable checkpoint still needs parent advancement.
Document deactivation, tab/window hide, or navigation sends one `touch_parent`
lifecycle update. The server either combines it with a new checkpoint or
performs a touch-only masked write.

This makes changed documents visible to collection polling without turning
each live checkpoint into a form-edit conflict. Offline records retain the same
intent.

## Presence closure

`closed_documents` removes presence on deactivation, blur, hide, navigation,
and teardown. The browser detaches the subscription and waits for an active poll
before closing so a late poll cannot recreate presence. Field expiration cleans
up clients that close without running teardown.

## Mentions

New mention occurrences travel in the accepted document checkpoint. After the
asset is durable, the server verifies the occurrence in saved HTML, reloads the
recipient, checks current mention and document-view authorization, and creates
a deterministic marker, Notification, and aggregate update transactionally.
The marker makes replay idempotent. Public rendering converts mention atoms to
inert display text before sanitization.

See [BACKEND_COMMUNICATIONS.md](BACKEND_COMMUNICATIONS.md#mentions).

## Change checklist

- Treat Yjs deltas as commutative but checkpoints as revision-qualified.
- Keep Redis state isolated per document and recoverable from durable assets.
- Remove IndexedDB only after checkpoint acceptance.
- Keep presence expiring and separate from document content.
- Advance parent/list fingerprints at the document lifecycle boundary.
- Test generation reset, stale checkpoint, simultaneous edits, compaction,
  offline replay, and presence closure.
