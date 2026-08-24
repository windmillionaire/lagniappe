# Sync and Polling Architecture

Lagniappe uses one view-scoped browser polling coordinator for server-state
invalidation. It batches all due subscriptions into `POST /l/poll`; rich HTML
and data continue to come from focused routes.

Use the focused guides for stateful consumers:

| Guide | Covers |
| --- | --- |
| [SYNC_DOCUMENTS.md](SYNC_DOCUMENTS.md) | Collaborative Yjs state, Redis revisions, presence, checkpoints, mentions, and offline replay. |
| [SYNC_OFFLINE.md](SYNC_OFFLINE.md) | Committed form edits, offline mutation replay, deferred form locks, and service-worker boundaries. |
| [FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md) | How mounted forms, collections, operations, and Notifications consume invalidations. |

## Authorities

| Surface | Durable or working authority | Poll type |
| --- | --- | --- |
| Entity and focused form | Datastore `fingerprint` and `modified`. | `entity`, `form-lock` |
| Collection membership | Datastore site/channel fingerprints. | `channel` |
| Deferred work | `DeferredJob.status_revision`; Redis is a verified read hint. | `operation` |
| Notification invalidation | Durable aggregate; Redis generation/revision/membership projection. | Request-level `notification_state` |
| File ingress | Ingress entity state and fingerprint. | `ingress` |
| Collaborative document | Durable asset plus revisioned Redis working state. | `document` |
| Offline form mutation | IndexedDB command until accepted by the server. | Replayed on reconnect |

Entity and collection revisions survive Redis loss. Redis is appropriate for
document working state and reconstructable notification/operation projections.
Do not add Redis copies of durable fingerprints merely to avoid a bounded
Datastore read.

## Browser scheduler

`src/script/shared/polling.mjs` owns scheduling for one mounted view. Each
subscription has a stable ID, type-specific fields, and an opaque revision.
The coordinator:

- batches at most 64 due subscriptions;
- runs one `beforePoll` hook so document edits can flush first;
- permits one in-flight request and coalesces overlapping triggers;
- schedules one immediate follow-up when a trigger needs a subscription that
  was not in the active request;
- uses one jitter factor and scheduling timestamp per response so equal
  cadences remain batched;
- distinguishes periodic from foreground-only work and immediate from
  scheduled first checks;
- backs transport errors off to 60 seconds;
- keeps a cold notification seed pending until the response header publishes a
  warm generation, retrying an unacknowledged seed with the same 4-to-60-second
  jittered error backoff even when no ordinary subscriptions exist;
- suspends ordinary polling when hidden, unfocused, or offline; and
- performs one catch-up batch after focus, visibility, browser-online, or
  server-online recovery.

Current cadences:

| Type | First/steady behavior |
| --- | --- |
| Entity and form lock | First due after 15 seconds, then quiet backoff. |
| Collection channel | Foreground catch-up only; no idle timer. |
| Document | Immediate while active, then every 2 seconds. |
| Ingress | Immediate while running and visible, then every 2.5 seconds. |
| Server-rendered operation | First at 4 seconds, then 8/16/30-second quiet backoff. |
| Locally started operation | Immediate nudge, then adaptive cadence. |

A visible tab in an unfocused window may retain only operations whose progress
UI is connected and rendered, for at most ten minutes. All other subscription
types remain paused.

## Startup and ownership

Shell interaction becomes ready before polling or storage. When a concrete
Core view publishes, it starts its root subscription and visible prefetch.
Document capability starts SyncManager. An idle IndexedDB inspection starts
SyncManager or OfflineQueue only when persisted work exists. Capability-gated
services share idempotent `ensure...()` loaders.

Recurring work belongs to the narrowest visible consumer:

| Subscription | Lifetime |
| --- | --- |
| Root entity | Mounted, focused, visible detail view. |
| Index channel | Mounted view; checked on foreground catch-up. |
| Home channel | After its owning Notes, Tasks, Starred, Pages, Projects, Categories, Ingress, or Tool Reports widget loads. |
| Watched entity/form lock | Active visible form only; root forms reuse the root entity result. |
| Document | Active visible collaborative editor. |
| Ingress | Visible wizard while the import is running. |
| Operation | From durable acknowledgement until terminal reconciliation, even if the source widget closes. |

Component rendering schedules ownership reconciliation without waiting on the
poll. Reconnect explicitly reconciles ownership before resuming.

## `POST /l/poll`

The version 1 request is exact:

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

`version`, `client_id`, `subscriptions`, and `closed_documents` are required.
Descriptors require unique `id`, `type`, and `revision` fields plus the exact
type fields:

| Type | Fields | Revision |
| --- | --- | --- |
| `entity` | `key` | Null or opaque string. |
| `channel` | Allowlisted `channel` | Null or opaque string. |
| `form-lock` | `key` | Opaque string. |
| `ingress` | `key` | Null or opaque string. |
| `operation` | job `key` | Nonnegative JavaScript-safe integer. |
| `document` | `key`, `sync_id`, nullable `generation`, nullable `presence_digest` | Nonnegative JavaScript-safe integer. |

Notification state is either a cold seed with null cursors and `seed: true`,
or a warm nonblank generation and nonnegative revision with `seed: false`.
Omitting it means the caller does not need notification state.

The browser validates descriptors before registration and request creation.
The server repeats validation because the HTTP boundary is untrusted. Invalid
requests receive a safe `422 invalid_poll_contract` with a field path and
reason category; rejected values are not echoed or reported.

## Results

Every requested ID appears once with the matching type:

```json
{
  "id": "edit:entity-key",
  "type": "entity",
  "status": "changed",
  "revision": "new-revision",
  "poll_after_ms": 15000,
  "payload": {}
}
```

`status` is `unchanged`, `changed`, `unavailable`, or `error`. Changed results
carry the type's revision and bounded payload; unavailable/error results carry
neither. A malformed or missing result becomes a retryable error only for that
subscription.

| Type | Changed payload |
| --- | --- |
| `entity` | `fingerprint`, `modified`. |
| `channel` | `refresh: true`. |
| `form-lock` | Lock state and operation identity. |
| `operation` | Owner-safe job status/destination. |
| `ingress` | `refresh: true`. |
| `document` | Generation, revision, snapshot/deltas, and presence. |

## Collection revisions

Channel loaders batch only the required `database.site_fingerprints()` values.
Permission fingerprints participate in collection revisions, so access changes
invalidate a viewer's list even when membership is unchanged. Home widgets use
independent channels. Personal Starred and Tool Reports channels combine their
narrow User/report authorities.

Operation and notification bookkeeping do not modify User or site collection
fingerprints.

## Extending the contract

Prefer an existing type when its permission, cadence, and payload fit. A new
type needs:

1. exact browser and server descriptor validation;
2. a bounded common result envelope;
3. one narrow authority and permission check;
4. ownership in the consuming component;
5. a focused route for rich content; and
6. backend contract tests plus JavaScript scheduler/consumer coverage.

Do not add feature-owned intervals or service-worker relays for application
state.
