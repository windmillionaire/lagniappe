# Backend Web

The web layer (`lagniappe/web/`) is a Flask application that serves HTML pages, handles API requests, manages authentication, and renders templates. It connects the entity/property system to the browser via routes, Jinja templates, and a permission system.

## App Initialization (`web/__init__.py`)

The Flask app is created at module load. `initialize_app()` wires the rest of
the stack. Initialization:

1. **Sentry**: Initialized in production if `CAPTURE_ERRORS` is enabled, using
   the installation's selected maintainer or operator DSN and final event
   sanitization for SDK-added request/context data. The browser bundle uses the
   same DSN, and the response CSP permits only that DSN origin for delivery.
   Reports sent to the maintainer DSN are governed by the
   [error-reporting privacy notice](../ERROR_REPORTING_PRIVACY.md).
2. **Flask config**: Secret key, secure session cookies (SameSite=Lax, HttpOnly, Secure)
3. **CSRF**: Flask-WTF CSRF protection on all routes (except `process` blueprint)
4. **`initialize_app()`**: Starts cache, database, AI, entity registry, Jinja,
   error handlers, blueprints, and Flask-Login
5. **Login manager**: Flask-Login with `load_user()` that resolves email to a User entity; templates use the lazy `current_user` Jinja global from `web/start/jinja.py` instead of Flask-Login's eager context processor
6. **Security headers**: Applied via `after_request` -- HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
7. **ETag support**: If `g.fingerprint` is set by a route, it's included as an `ETag` header (combined with build ID)
8. **Cache invalidation**: If Flask-Login already loaded an authenticated user and that user has `invalidate_cache` set, adds `X-Lagniappe-Invalidate-Cache` (triggers service worker cache wipe without forcing user loads for static/health-check requests)
9. **Polling routes**: Registers the versioned, permission-checked `/poll`
   contract used by mounted browser state

## Startup (`web/start/`)

### `initialize_app()` (`__init__.py`)

Runs all initialization in order: cache, database, AI, entity registry, Jinja
environment, error handlers, blueprint registration, and login manager setup.

### Blueprint Registration (`blueprints.py`)

| Blueprint | URL Prefix | Description |
|---|---|---|
| `home` | `/` | Home page, admin settings, search, sync, delete; ingress list UI |
| `projects` | `/projects` | Project views and model task management |
| `files` | `/files` | File views, upload, ingress pipeline |
| `categories` | `/categories` | Category index and management |
| `forms` | `/forms` | Form index, builder, schema operations |
| `users` | `/users` | User index, login, groups, permissions |
| `pages` | `/pages` | Page views, notes |
| `tasks` | `/tasks` | Task index and management |
| `process` | `/process` | Background process endpoints (CSRF exempt) |
| `manual` | `/manual` | User manual pages |
| `reference` | `/reference` | Help/reference content (loaded in modals) |
| `filters` | `/filters` | Filter creation and management |
| `assets` | `/assets` | Document editor, images, form submission |
| `testing` | `/testing` | Test-only endpoints |

The `/assets/<key>/<name>` file response supports single `Range: bytes=...`
requests for private file assets, returning `206 Partial Content` with
`Content-Range` so large PDF previews can stream page data without downloading
the entire object through the app server.

Page notes use `GET` and `POST /pages/<page-key>/notes`. Home notes use
`POST /activity/notes`; both return the shared note-card fragment and delete
through the standard confirmation flow at `DELETE /activity/<note-key>`.
Home note creation requires login, but only `SITE:EDIT` may create a Home note
with `everyone` visibility. Page note creation and visibility choices continue
to use the Page edit permission. The server assigns the note scope, validates
`visibility`, and requires either `body` or one `note-file` image.

### Jinja Environment (`jinja.py`)

Configures the Jinja2 template engine with:

**Custom tests:**

| Test | Usage | Description |
|---|---|---|
| `datetime` | `{% if value is datetime %}` | Check if value is a datetime |
| `in_future` | `{% if value is in_future %}` | Date is after today (user timezone) |
| `in_past` | `{% if value is in_past %}` | Date is before today (user timezone) |

**Custom filters:**

| Filter | Usage | Description |
|---|---|---|
| `format_datetime` | `{{ value\|format_datetime }}` | Full datetime in user timezone |
| `format_date` | `{{ value\|format_date }}` | Date only in user timezone |
| `format_time` | `{{ value\|format_time }}` | Time in 12h format |
| `format_phone` | `{{ value\|format_phone }}` | US phone formatting |
| `format_number` | `{{ value\|format_number }}` | Number with commas |
| `format_date_as_input_string` | `{{ value\|format_date_as_input_string }}` | YYYY-MM-DD for form inputs |

**Global variables:**

| Variable | Description |
|---|---|
| `VERSION` | App version string |
| `BUILD_ID` | Build/cache-busting string from `config.constants` |
| `CAPTURE_ERRORS` | Whether Sentry is active |
| `TESTING` | Whether in test mode |
| `render_icon` | Renders a decorative Material Symbol from a semantic icon ID |
| `styles` | Style class strings (from `styles.yaml`) |
| `is_starred` | Function to check if entity is starred by current user |
| `current_user` | Flask-Login current user |
| `Action` | Permission action enum |
| `Resource` | Permission resource enum |

### Error Handling (`errors.py`)

Four registered error handlers:

| Handler | Catches | Behavior |
|---|---|---|
| `handle_datastore_error` | `GoogleAPIError` | 500 with debug context |
| `handle_jinja_error` | `TemplateError` | 500 with Jinja source context (template line, surrounding code) |
| `handle_http_error` | `HTTPException` | 401 redirects to login, 422 returns plain text, others render error template |
| `handle_exception` | `Exception` | Checks if it's a chained Jinja error first, otherwise generic 500 |

In non-production, error pages include full local debug context (frames, local
variables, traceback). In production, the Sentry copy is privacy-reduced before
delivery: request reporting is limited to the route template, endpoint, method,
bounded content metadata, query field structure, and a short exact header
allowlist. Form/JSON/query values, full URLs, route-argument values, filenames,
identity context, and arbitrary headers are omitted; recognized credentials and
payload-bearing context keys are recursively redacted and all context is
bounded. Error messages and stack traces remain diagnostic text. All error
responses include `X-Lagniappe-Error` (used by frontend `request.mjs` to detect
error pages).

## Authentication (`web/auth/`)

The login page refreshes its Flask-WTF token from `GET /token` immediately
before handing an Identity Platform credential to
`POST /users/login-identity`. If that write still receives a CSRF-specific
`400` response, identified by `X-Lagniappe-CSRF: invalid`, the client refreshes
and retries once. Other `400` responses are not retried. The server verifies
the exact Secure Token issuer, project audience, and subject before creating a
Lagniappe session. Popup-free Google Identity Services credentials are first
exchanged through Identity Platform's `accounts:signInWithIdp` endpoint.

### Permission Decorators

Routes are protected by decorator functions that check authentication, authorization, and ETag freshness:

**`@permission(resource, action)`** -- the primary decorator. Flow:

1. Check user is authenticated (401 if not)
2. If route has a `key` parameter, load the entity (404 if not found)
3. Set `g.fingerprint` for ETag generation
4. Check permission via `current_user.has_permission(resource, action)` or `entity.allowed(action)`
5. Only after authorization, if the request's `If-None-Match` header matches the current fingerprint + build ID, return 304
6. If authorized, pass the loaded entity to the route function as `entity=`

The session user, user page, and requested entity are explicit roots in one
fixed `Fetch.direct()` request. The first batch resolves any missing roots; the
second attaches one relation level for every root. This gives request auth the
user's groups and starred entities, the user page's direct relations, and the
requested entity's direct relations without recursively expanding the graph.
The decorator does not accept a route-specific fetch declaration.

If a handler needs more than this auth graph, it declares that dependency at
the point of use:

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

Most handlers use `kwargs["entity"]` directly because the fixed auth graph
already supplies its direct relations. A handler that consumes a two-level
graph re-fetches that same typed entity with a registered nested reason; the
already-attached first level is reused and the missing second level is loaded.
Task routes do this on persistence paths so `Task.save()` can recompute stored
requirements for the task and its list owners; readonly task routes use the
direct auth entity. These reasons describe route behavior, not auth-loader
configuration.
Independent entities likewise use
`Entities.fetch`/`fetch_one` with their own explicit scope. A repository-health
test rejects route-level `Entities.load`,
`Entities.get(load=True)`, and injected-entity use outside `@permission`.

**Other decorators:**

| Decorator | Purpose |
|---|---|
| `@logged_in` | Simple authentication check (no authorization) |
| `@home_permission()` | Home page -- uses route-based or starred fingerprints |

### Agent Access

`/users/agent-login` is an optional form-based login for browser agents or
manual review sessions that cannot use Google confirmation flows. It
is disabled unless `AGENT_ACCESS_ENABLED`, `AGENT_ACCESS_EMAIL`, and
`AGENT_ACCESS_CODE` are present in app settings. A successful code submission
creates or loads the configured user as a normal user account, including its
assigned groups, and then uses the normal Flask-Login session and
group/permission system; it does not bypass authorization. Owners can reassign
the agent user's groups from that user's settings page.

### ETag Flow

The permission decorators integrate with the service worker's ETag caching:

1. Decorator sets `g.fingerprint` (entity's modified timestamp, or a cached hash of the rendered HTML)
2. `after_request` converts it to an `ETag` header using the route fingerprint and tracked `BUILD_ID`
3. On subsequent requests, the service worker sends `If-None-Match`
4. After authorizing the request, the decorator compares -- if match, returns 304 (no body)

## Route Patterns

### Full Page Rendering

For initial page loads (browser navigation):

```python
@pages.route("<key>", methods=["GET"])
@permission(Resource.PAGE, Action.VIEW)
def view(key, **kwargs):
    page = kwargs["entity"]
    return render_template("pages/page.html", page=page)
```

### Partial Rendering

For AJAX requests from the frontend (widget loading, form submissions):

```python
@pages.route("<key>/tasks", methods=["GET"])
@permission(Resource.PAGE, Action.EDIT)
def tasks(key, **kwargs):
    page = kwargs["entity"]
    return get_template_attribute("pages/tasks.html", "task_list")(page)
```

`get_template_attribute` renders a single Jinja macro from a template file, returning just the HTML fragment. This is how widgets load their content -- the frontend's `request.mjs` fetches the fragment and the widget inserts it into the DOM.

### Unified Polling

`POST /poll` accepts a bounded versioned batch of typed subscriptions. It
groups descriptors before invoking type-specific loaders, batches target
entities once, resolves locks only when lock descriptors exist, and reads only
the site fingerprints required by mounted channels in one multi-read. Matching
operation aggregate revisions skip job loads; stale aggregates load only the
operation keys tracked by that browser in batches of 50. Viewer permissions are
checked before returning the common changed/unchanged/unavailable/error
envelope. Entity and collection cursors are durable fingerprints; document
cursors are Redis generations/revisions; deferred operations use
`status_revision`. Large HTML or data remains on focused replacement routes.

The optional request-level `notification_state` cursor is checked through Redis
and returned in `X-Lagniappe-Notification-State`. A `seed: true` miss performs
the single authoritative keys-only notification query; warm document, ingress,
operation, and foreground catch-up polls do no notification Datastore work.
`HEAD /ping` reads only the signed session user key and performs the same warm
Redis peek without activating Flask-Login. Redis misses/errors do not change
the health-check status. See
[SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md).

### Deferred Admin Export

The `/admin` view includes an owner-only Export tab next to Site Settings. Its
`SiteExport` widget loads from `GET /site-export` and starts work with
`POST /site-export`. The POST creates the queued `site_export` metadata record
and starts a durable shared job with a pending notification. Production
dispatches that job to `/process/jobs`, development runs it in a local daemon
thread, and testing runs the `SiteExportAdapter` inline.

In production, `process.deferred_job_process` authenticates the Cloud Tasks OIDC
request, claims the job, and rechecks the actor's current site permission.
`SiteExportAdapter` marks the export record running, calls
`lagniappe.core.tools.site_export.build_site_export()`, and persists the returned
complete metadata only after the builder writes `manifest.json` last. Generic
terminal delivery then completes the notification. The browser's `operation`
subscription observes terminal status and reconciles the admin widget on
success or failure. If the initial production enqueue raises or returns no task
identity, start compensation instead marks both the export record and durable
job failed, completes the pending notification, and returns the enqueue failure
to the request boundary without running the export builder. See
[AI_PIPELINE.md](AI_PIPELINE.md) for the shared job and polling architecture.

### Index Page Access and Collection Fingerprints

Index routes use the access decorator appropriate to the collection. Forms and
users require their corresponding global permission. The task index only
requires authentication because `TaskIndex` applies the current user's task
restrictions to both its initial and lazy-row queries:

```python
@tasks.route("/index", methods=["GET"])
@logged_in
def task_index():
    return responses.index("tasks", index.TaskIndex())
```

`responses.index()` adds the site fingerprint used by collection refresh. This
is separate from HTTP ETag handling: routes decorated with `@permission` or
`@home_permission` also set `g.fingerprint`, which the response hook emits as
an ETag.

### Create/Update Pattern

Entity creation and updates return JSON responses consumed by the frontend's `Core.successfulResponse()`:

```python
# Return JSON with response data
return jsonify({"schema": schema, "submission": submission})

# Return HTML fragment for widget replacement
return get_template_attribute("pages/info.html", "page_info")(page)

# Return error
return "Validation error message", 422

# Trigger page reload
return jsonify({"reload": True})

# Show a modal
return jsonify({"modal": modal_html})
```

## Template Structure

Templates are organized by feature in `web/templates/`:

| Directory | Templates | Purpose |
|---|---|---|
| Root | `common.html`, `nav.html`, `table.html`, `cell.html`, `controls.html`, `badge.html`, `filters.html` | Shared macros and components |
| `layouts/` | `base.html`, `login.html`, `error.html`, `delete.html` | Page layouts |
| `home/` | `home.html`, `projects.html`, `categories.html`, `tasks.html`, `starred.html`, `directory.html`, `notes.html`, `ingress.html` | Home page sections |
| `pages/` | `page.html`, `info.html`, `document.html`, `tasks.html`, `files.html`, `photo.html` | Page entity views |
| `projects/` | `project.html`, `info.html`, `document.html`, `model_tasks.html` | Project entity views |
| `categories/` | `index.html`, `tools.html` | Category index |
| `tasks/` | `index.html` | Task index |
| `files/` | `file.html`, `info.html`, `text.html`, `ingress.html`, `stages.html`, `status/` | File entity views |
| `forms/` | `index.html`, `tools.html`, `builder.html` | Form index and builder |
| `users/` | `index.html`, `tools.html`, `login.html`, `logged_in.html` | User management and auth |
| `search/` | `search.html`, `results.html` | Search page |
| `manual/` | `index.html`, `content/` | User manual |
| `reference/` | Various | Help modal content |
| `delete/` | Per-entity-type | Delete confirmation modals |
| `errors/` | `400.html` - `500.html`, `jinja.html`, `other.html` | Error pages |
| `testing/` | `main.html` | Test page |
| `public/` | `public.html` | Public entity views |

Templates use Jinja macros extensively. The `get_template_attribute` pattern allows routes to render individual macros as HTML fragments for widget content, while full page renders use `render_template` with layout inheritance.
