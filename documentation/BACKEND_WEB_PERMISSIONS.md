# Web Permissions and Freshness

The web authorization layer joins Flask-Login, entity permissions, explicit
fetch scope, HTTP caching, and shared polling. The primary implementation is in
`lagniappe/web/auth.py` and the poll routes under `lagniappe/web/routes/home/`.

## Decorators

`@permission(resource, action)` is the standard entity-route decorator. It:

1. requires an authenticated user;
2. loads the entity named by the route `key`;
3. sets `g.fingerprint`;
4. evaluates `current_user.has_permission(...)` or `entity.allowed(...)`;
5. checks `If-None-Match` only after authorization; and
6. passes the typed entity as `kwargs["entity"]`.

The fixed authorization fetch uses the session user, user page, and requested
entity as explicit roots. One batch resolves missing roots and a second attaches
one relation level. This supplies groups, starred entities, the user page's
direct relations, and the target's direct relations without expanding the full
graph.

Handlers that require a deeper graph declare it at the point of use:

```python
@permission(Resource.TASK, Action.EDIT)
def update(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(
            because=FetchReason.TASK_SAVE_REQUIREMENTS,
        ),
    )
    task.name = request.form["name"]
    task.save()
    return responses.page_task(task)
```

The nested reason documents the handler dependency. Do not add route-specific
behavior to the authorization loader. Repository-health checks reject
route-level `Entities.load`, `Entities.get(load=True)`, and injected-entity use
outside `@permission`.

Other access decorators:

| Decorator | Use |
| --- | --- |
| `@logged_in` | Authentication without a resource-wide permission check. |
| `@home_permission()` | Home access plus the route or starred fingerprint. |

Star mutation is an entity route protected by `@permission(requested=VIEW)`:
missing targets return 404 and existing targets the user cannot view return
403 before either the User or target can be touched. Starred-list rendering
rechecks VIEW as defense in depth. A temporarily inaccessible saved key is
hidden but retained; only keys whose entities no longer exist are cleaned up.

Authentication provider flows are documented in
[AUTHENTICATION.md](AUTHENTICATION.md). Backend permission enums and entity
rules are documented in [BACKEND_DEFINITIONS.md](BACKEND_DEFINITIONS.md).

## ETags and collection fingerprints

Entity permission decorators set `g.fingerprint`. The response hook combines
that fingerprint with `BUILD_ID` and emits an ETag. A subsequent request may
send `If-None-Match`; the decorator returns `304` only after authenticating and
authorizing it.

Collection pages use site fingerprints attached by `responses.index()`. These
drive focused browser refreshes and are separate from HTTP ETags.

Index access follows the collection's visibility rules. Forms and users require
their global permissions. The task index requires login and relies on
`TaskIndex` to apply user restrictions. Restricted task queries combine the
ordinary `requires` branch with the user's personal Page in `assigned_to`, so
assigned work remains visible even when its source Page is unavailable.

## Shared polling

`POST /l/poll` accepts a bounded, versioned batch of typed subscriptions. It
groups descriptors, batches target loads, authorizes each viewer, and returns a
common changed/unchanged/unavailable/error envelope.

Cursor types follow the underlying state:

| Subscription | Cursor |
| --- | --- |
| Entity or collection | Durable fingerprint. |
| Collaborative document | Redis generation and revision. |
| Deferred operation | `status_revision`. |
| Form lock | Lock identity and revision. |
| Ingress | Stage and progress revision. |

Large HTML and data stay on focused replacement routes. Polling reports only
enough state for the owning frontend service to decide whether to fetch them.

Owner operation projections use cached terminal state when fresh; misses and
verification-due projections load only the keys tracked by that browser.
Collaborator descriptors load durable operation records so authorization is
always checked.

The optional request-level `notification_state` cursor uses Redis and returns
its state in `X-Lagniappe-Notification-State`. A seeded cache miss performs one
authoritative keys-only query. `HEAD /l/ping` uses the signed session user key
for the same warm Redis peek without activating Flask-Login; a Redis miss does
not change health-check status.

See [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md) for the scheduler and protocol,
[SYNC_DOCUMENTS.md](SYNC_DOCUMENTS.md) for document state, and
[BACKEND_JOBS.md](BACKEND_JOBS.md) for operation projections.

## Change checklist

When changing route authorization or freshness:

1. Keep authentication and authorization ahead of conditional responses.
2. Express extra entity scope through a registered `FetchReason`.
3. Keep poll payloads bounded and typed.
4. Batch keys and relations before adding per-descriptor reads.
5. Update focused unit tests and E2E coverage for observable browser behavior.
6. Run the changed-source traceability and template-contract checks when their
   respective contracts move.
