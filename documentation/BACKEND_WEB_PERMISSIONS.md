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

Star mutation is asymmetric. Adding a new key requires an existing target with
`VIEW` access. Removing an already stored key is a mutation of the authenticated
user's own starred list, so it remains available when the target is inaccessible
or no longer exists. Starred-list rendering rechecks `VIEW` as defense in depth
and represents unavailable keys with removable placeholder rows; it does not
expose the entity's saved name or other details. The relation remains stored as
native Datastore keys; templates encode those keys only at the route/DOM
boundary.

Authentication provider flows are documented in
[AUTHENTICATION.md](AUTHENTICATION.md). Backend permission enums and entity
rules are documented in [BACKEND_DEFINITIONS.md](BACKEND_DEFINITIONS.md).

## Submitted reference boundary

The route decorator authorizes only the primary entity identified by the URL.
Entity keys in a request body are a separate authorization boundary; a key
being present in a permission-filtered facet is useful UI behavior, but is not
proof that the submitted request came from that facet.

Browser mutation handlers use `SubmittedReferenceResolver` to batch-load these
secondary keys and declare the expected entity type, required action, and any
relationship or domain predicate. Missing, malformed, wrong-kind, and denied
body references all return the same `422` response: `One or more selected items
are unavailable.` Route-path and route-parent mismatches continue to return
`404`, so they do not disclose whether a known key exists elsewhere.

The current policies are:

| Reference | Required boundary |
| --- | --- |
| Category, Page, Project, or ModelTask selection | Target `VIEW`, plus the route-parent relationship where applicable. |
| Attached Form | Target `VIEW` and the expected Page/Task form type. Schema generation requires target `EDIT`. |
| Task assignee | A user-backed Page accepted by the collaboration assignment policy. |
| Existing File attached to a Page or Task | Target `VIEW`. |
| Newly uploaded Task File | A short-lived signed claim bound to the actor, File, and authorized Task/Page upload scope. |
| Internal form Link submitted by a browser | Target `VIEW` before any submission field is mutated. |

An ordinary edit preserves an existing relation that the actor can no longer
view when the hidden field is omitted. It does not silently erase the relation,
and preservation does not authorize replacing it with another hidden target.
Task attachment selectors and attached-Form preload data are also
permission-filtered to avoid exposing stored details in the browser.

The internal Link preflight is deliberately enabled by browser route callers.
Trusted AI, import, migration, and background-service flows keep their existing
service-owned policy instead of depending on Flask session state.

Filter DTOs use their own versioned compiler because their source, field,
comparator, and value contracts are broader than entity-key resolution alone.
Condition/options routes resolve sources and dynamic selectors only through the
primary project's/category's authorized filter catalog. Preview, save, saved
run, AI queries, and polling all compile to the same `CompiledFilter` boundary;
an unavailable secondary reference returns a generic `422` and cannot reach
Datastore mutation or Redis query construction.

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
3. Treat request-body entity keys as submitted references with an explicit
   type, action, and relationship policy.
4. Keep poll payloads bounded and typed.
5. Batch keys and relations before adding per-descriptor reads.
6. Update focused unit tests and E2E coverage for observable browser behavior.
7. Run the changed-source traceability and template-contract checks when their
   respective contracts move.
