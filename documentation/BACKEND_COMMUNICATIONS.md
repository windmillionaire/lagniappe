# Backend Communications

Lagniappe communication consists of ordinary Notifications, direct Messages,
document mentions, Notes, and optional notification email. Domain records are
durable in Datastore; Redis is used only for reconstructable badge/presence
state and an activity hint.

## Ownership map

| Concern | Entity/property owners | Service and persistence owners |
| --- | --- | --- |
| Notifications | `properties/notification.py`, `notification_aggregate.py` | `tools/notifications/service.py`, `database/notifications.py` |
| Direct messages | `properties/message*.py` | `tools/messaging/`, `database/messaging.py` |
| Mentions | `properties/mention.py` | `tools/mentions/`, `database/mentions.py` |
| Notes | `entities/note.py` and note properties | Note routes plus normal mutation planning |
| Email delivery | User email preference and `email_deliveries` rows | `tools/email/notifications/`, `database/notification_email.py` |

Properties own validation, identity, and pure transitions. Authorization,
cross-record transactions, projection publication, email capture, and delivery
belong to services.

## Notifications and aggregate

An ordinary Notification belongs to one User, has plain text, may point to a
target, and may be pending while deferred work runs. Each User also has one
deterministic aggregate row containing exact ordinary and unread-message
counts plus revision/generation state. The aggregate remains durable at zero
and is rendered as one undeletable Messages entry, not as an ordinary row.

Create, update, delete, and clear operations update the durable row and
aggregate transactionally. A post-commit effect updates the Redis membership
projection. Redis failure does not roll back the mutation. The menu loads at
most 25 ordinary keys per page and reads the aggregate separately; it does not
query message history.

Deferred work may create a pending Notification and update the same row at
completion. File jobs can use completion-only notifications. Reviewed report
execution uses no Notification. AI email ingestion creates a Notification only
when handoff fails before a report job owns the workflow.

## Direct messages

`MessageConversation` uses a deterministic key derived from two sorted User
keys. It stores participant/name snapshots, per-user read/clear cursors,
visibility, sequence, and revision. Message children store sender, recipient,
sequence, a trimmed plain-text body of at most 1,000 characters, and each
participant's hide state.

A deterministic sender/operation key makes replay idempotent and conflicting
reuse an error. All reads are participant-authorized; Owner status does not
override message privacy. Losing permission blocks new sends but keeps the
existing participant's history. Per-message delete and conversation clear hide
only that User's copy.

Recipient eligibility comes from the cached union of group membership and
group `VIEW`, unless the User has global Users `VIEW`. The Owner's inbound
message and mention settings fail closed. Mutation authorization always checks
the loaded canonical Owner/User rows, not the Redis search projection.

## Mentions

The editor stores a mention occurrence, recipient, and display name in the
collaborative document checkpoint. Delivery begins only after that checkpoint
is accepted and the document asset is durable. The server then:

1. confirms the occurrence still exists in saved HTML;
2. reloads the recipient;
3. checks current mention eligibility and document `VIEW` permission; and
4. creates a deterministic `MentionMarker`, Notification, and aggregate update
   in one transaction.

The marker remains after Notification deletion, preventing replay from
delivering the same occurrence twice. Public document output replaces mention
nodes with inert display text before sanitization.

## Notes

Notes have an author, owning parent, optional plain text and photo, a
server-assigned `home` or `page` scope, and `private` or `everyone` visibility.
Home shared notes appear in authenticated feeds; Page shared notes also require
Page view access. Only the creator or an Administrator can delete a private
Note. Only an Administrator may make a Home Note visible to everyone; Page
creation follows Page edit access.

Note mutations touch the parent and author. Page and User deletion cascade
through their Notes and photo assets.

## Notification email

Managed Users choose `NONE`, `IMMEDIATE`, or `DAILY`; public Users use their
separate site-email consent. Selecting `NONE` advances an opt-out generation so
queued deliveries are suppressed at send time.

After the primary communication transaction, the service captures a compact
`email_deliveries` row. Email is supplementary: capture or enqueue failure does
not roll back the Notification, Message, mention, or task assignment.

- Immediate Notification mail is due after five minutes and is suppressed by
  recent authenticated site activity.
- Immediate Message mail coalesces by conversation and is suppressed after a
  read, clear, hide, reply, or recent activity.
- Daily mail groups events for the recipient's next local 8:00 AM and includes
  events even when already viewed in the application.

`policy.py` decides eligibility and due time; `presence.py` owns the
best-effort Redis activity hint; `capture.py` creates delivery rows;
`dispatch.py` schedules Cloud Tasks; `presentation.py` renders provider-neutral
multipart email; `delivery.py` owns send-time suppression and terminal state.

## Browser surfaces

`views/messages.mjs` owns the Messages page. `MessageComposer` is shared with
the Notification menu. Mention suggestions are owned by the editor. Badge and
menu invalidation use the notification projection described in
[BACKEND_CACHE.md](BACKEND_CACHE.md); browser polling and reconciliation are in
[SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md).

## Change checklist

- Keep message bodies and notification content durable and out of Redis.
- Update aggregate counters in the same transaction as visible unread state.
- Make replay keys deterministic.
- Recheck authorization at delivery time.
- Treat email as a non-authoritative side effect.
- Cover participant privacy, duplicate delivery, counter races, opt-out, and
  post-commit cache failure.
