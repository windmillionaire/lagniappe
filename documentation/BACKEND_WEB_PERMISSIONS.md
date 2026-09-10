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

Routes whose responses must never be reused declare that policy at the
authorization boundary:

```python
@permission(Resource.SITE, no_store=True)
def admin():
    return responses.admin_page()
```

`no_store=True` sets the response policy before authentication or conditional
request handling and skips ETag generation. This is required for live provider
status, dynamic forms, and downloads that must not be served from browser or
service-worker storage. Do not set `g.NO_CACHE` inside such a handler: an
`If-None-Match` request can otherwise receive `304` before the handler runs.

`_load_request_context()` keeps the session User and user Page at direct depth.
Task and File targets use `Fetch.nested()` so their Page/Form dependencies are
already resolved before fingerprints or permissions are evaluated. An attached
File stores `page` for a direct attachment, or `task` and `task_page` for a Task
attachment, keeping both parents' Forms
within two relation levels. Expanding a Task History table cell loads the
snapshot by its own key and expands its live Task as a nested root for
authorization. Permission checks never fetch their own relations. Missing required
parents or unresolved permission dependencies raise rather than opening access.

Only Forms, Pages, Tasks, and Files have `restricted_to`. Category, task-template,
and User access use their ordinary resource permissions; a User's Page has its
own content restrictions. Forms and Pages persist only their local arrays. Effective
restrictions keep three independent sources: `page`, `page_form`, and
`task_form`. A Page combines its own groups with its Form's groups; a Task adds
its own Form's groups. Files inherit their primary Task or Page's complete rule.
A non-administrator must belong to at least one group in every nonempty source,
in addition to holding ordinary resource permissions. Groups within a source
are ORed; the sources are ANDed. Assignment grants Task VIEW/EDIT only after
this restriction check succeeds.

Administrators bypass group restrictions with `Restriction.BELONGS_TO_ALL` in
search `belongs_to`; ordinary users without groups use `Restriction.BELONGS_TO_NONE`.
`Restriction.UNRESTRICTED` independently omits the required-access filter.
The reserved `["admin"]` local
restriction permits only administrators. Membership and role changes contribute to the
viewer's authorization fingerprint and invalidate cached restriction sessions.
Messaging uses actual group memberships rather than the search sentinel.

Page restrictions display separate rows for the Page's local Groups and its
Form's Groups. Group names are attached at the initial settings load boundary;
rendering and permission helpers do not fetch them. Both Page and Form editors
submit complete local restrictions explicitly, with submitted Groups resolved
in a batch. `Groups.attach()` materializes local group hashes in the Datastore
entity; ordinary saves persist them. Permission evaluation reads these stored
hashes without loading Groups.

Redis stores each source in its own TAG field: `restricted_to_page`,
`restricted_to_page_form`, and `restricted_to_task_form`. Each search ANDs three
clauses, each allowing either a missing field or a match with any of the
viewer's group hashes. This applies before pagination, counts, highlighting,
and model expansion. Query size is linear in group membership. Cached details
store `restricted_to` as a canonical mapping of source names to group arrays;
empty sources are omitted. Fingerprints preserve these source boundaries.

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
| File ownership move | Current File and destination Page/live Task both require `EDIT`. Page uploads only create new Files. |
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

Entity permission decorators set `g.fingerprint`. The fingerprint combines the
resource revision, App Engine deployment identity, frontend `BUILD_ID`, and
viewer's authorization fingerprint before the response hook emits an ETag. A
subsequent request may send `If-None-Match`; the decorator returns `304` only
after authenticating and authorizing it. The deployment identity invalidates
server-rendered HTML after backend or template-only deployments even when the
publish-only installer correctly reuses the existing frontend build.

Filter preview and saved-result routes pass `fingerprint=filter_result_revision`
to include the task-channel revision for Project results. A Task's changes can
alter those results without changing the Project or Filter. Reading that channel
adds one Datastore fingerprint-record read on these requests.

Permission routes declared `no_store=True` do not set `g.fingerprint` and never
answer a conditional request with `304`. Their `Cache-Control: no-store`
response also causes the service worker to discard any older stored response
for that URL.

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
