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
assets through a property-masked entity mutation and refresh Redis
metadata without touching the parent's ordinary form fingerprint.

Checkpoint writers now share a bounded per-document Redis write lock, reload
the editable entity inside that lock, and guard the durable asset metadata with
a Datastore compare-and-set. The lock serializes the common path; the durable
guard still rejects an expired-lock/stale writer. HTML/YDoc checkpoint blobs use
attempt-isolated paths, so a losing writer cannot overwrite the winner's blob
before its metadata commit. After a successful commit, the existing mutation
cleanup retires only superseded HTML/YDoc objects, never embedded images. Paths
are not reused, even for equal content, so delayed cleanup cannot delete a newer
save. Readers and version copies use recorded Storage generations so an
in-flight reader can finish after its old live object is retired. Empty
documents retain Yjs tombstones to prevent offline resurrection.

## Versions and recovery

- Current editing state is one HTML/YDoc pair; normal checkpoints do not create
  DocumentHistory records or retained live checkpoint archives.
- Named/pinned versions remain explicit HTML snapshots in DocumentHistory.
  Existing automatic entries remain readable, restorable, and removable with
  Clear Unpinned Versions; no upgrade migration deletes them.
- A reviewed append to an existing document saves one named "Before report
  append" version in that same history, atomically with the append's metadata.
  The Report preallocates its version key, so retries do not duplicate versions.
  Undo uses that version and CRDT deletions, not retained checkpoint paths.
- Disaster recovery continues to use the existing Storage object generations
  and backup configuration. Retiring a live object allows the existing
  noncurrent-version lifecycle to reclaim it; no new retention policy is added.

Cleanup is post-commit best-effort and failures use the existing mutation outcome
reporting. A provider failure or interrupted write can leave an unreferenced
blob; failed/ambiguous writes never trigger deletion of the accepted pair.

## Reviewed document appends

`append_page_document` uses `pycrdt` to append editor-compatible nodes to the
existing Yjs `default` fragment without reconstructing old nodes. Only new,
sanitized Markdown fragments are converted; existing rich content and IDs remain
untouched. New AI-created documents are initialized with Yjs state immediately.

The action requires a saved baseline: pending Redis edits or an older HTML-only
document stop execution rather than guessing or replacing a draft. The latter
needs one ordinary editor save. A durable `lagniappeReports` Yjs map records the
operation receipt, including the expected post-append content signature, so a
retry after a Report checkpoint failure does not append twice. Undo emits
deletions (not an old snapshot reset) and checks that later edits are preserved.
If a required named version is missing, Undo stops without modifying the document.

After an append commits, the server publishes a new revision/generation with the
merged snapshot. Connected/offline clients merge it using the existing sync
protocol. A fresh durable fingerprint also repairs a missed cache publication
at the next write; any retained CRDT changes are merged, not discarded. Ordinary
browser checkpoints keep their current generation when their metadata refresh
succeeds. Source/time quotes belong to reviewed AI additions, not normal typing.

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
