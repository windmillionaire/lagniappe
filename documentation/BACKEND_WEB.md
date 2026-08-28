# Web Application

`lagniappe/web/` is the Flask boundary between backend entities and browser
surfaces. It owns application startup, blueprints, route handlers, Jinja,
sessions, security headers, and response conventions.

Read [BACKEND_WEB_PERMISSIONS.md](BACKEND_WEB_PERMISSIONS.md) before changing
permission decorators, route fetch scopes, ETags, or polling authorization.

## Application startup

The Flask application is created in `lagniappe/web/__init__.py`.
`web/start/initialize_app()` initializes, in order:

1. cache and database services;
2. AI services and the entity registry;
3. Jinja configuration and error handlers;
4. blueprints; and
5. Flask-Login.

Production error reporting starts only when `CAPTURE_ERRORS` is enabled. Both
server and browser reporting apply final sanitization to request and context
data; see [the privacy contract](../ERROR_REPORTING_PRIVACY.md).

Global application behavior includes:

- Flask-WTF CSRF protection, except for authenticated process callbacks;
- Secure, HttpOnly, SameSite=Lax session cookies;
- HSTS, frame, content-type, referrer, and CSP headers;
- ETag emission when a route sets `g.fingerprint`;
- `X-Lagniappe-Invalidate-Cache` for an already-loaded signed-in user whose
  cache must be cleared; and
- the versioned `/l/poll` state endpoint.

Flask-Login resolves a session email to a `User` entity. Jinja receives the
lazy `current_user` global from `web/start/jinja.py`, avoiding an eager user
load on static and health-check requests.

## Blueprints

Blueprint registration lives in `web/start/blueprints.py`.

| Blueprint | Prefix | Responsibility |
| --- | --- | --- |
| `home` | `/` | Home, site settings, search, sync, and shared activity. |
| `projects` | `/projects` | Projects and model tasks. |
| `files` | `/files` | Files, uploads, and ingress. |
| `categories` | `/categories` | Category index and management. |
| `forms` | `/forms` | Form index, builder, and schema operations. |
| `users` | `/users` | Login, users, groups, and permissions. |
| `pages` | `/pages` | Page views and notes. |
| `tasks` | `/tasks` | Task index and task operations. |
| `process` | `/process` | Authenticated background callbacks. |
| `manual` | `/manual` | User manual. |
| `reference` | `/reference` | Help fragments loaded into modals. |
| `filters` | `/filters` | Filter management. |
| `assets` | `/assets` | Documents, images, and form submissions. |
| `testing` | `/testing` | Test-environment routes. |

Private asset responses support one `Range: bytes=...` request and return `206
Partial Content`, allowing PDF preview code to stream data through Flask.

## Anonymous public pages

Anonymous requests to `/` take a session-only fast path to `/public/`; they do
not construct the authenticated Home or load an entity. Authenticated requests
continue to use `/` as Home. The public directory always offers a sign-in link
and renders an empty state when it has no content.

The directory is a server-rendered, JavaScript-free set of collapsed native
`details` groups. Discoverable Pages appear only when site discovery is on and
the Page is active, public, and has not opted out. A Page may explicitly select
one of its attached Categories for grouping; otherwise it appears under
`Public Pages`. This opt-in prevents unrelated internal Category names from
becoming public. The optional public manual appears as one separate group in
its authored section order.

Directory cards use only the public ID, optional public title and description,
and explicitly selected Category label. They never load or excerpt document
content. Category and Page labels are sorted case-insensitively. The canonical
directory is indexable only when site discovery is on and it has public
content; otherwise it emits `noindex, follow` in both HTML and the
`X-Robots-Tag` header.

`/pages/public/<public_id>` is a dedicated server-rendered document surface.
It publishes a trusted canonical URL, robots policy, description, Open Graph,
and Twitter card metadata without exposing the Page's internal description or
photo. The public title/description override is optional; otherwise the page
name and a document excerpt are used. A selected sharing image must be a
page-owned image that is currently embedded in the document. The same image is
already visible in document layout, so public rendering does not add a second
hero image.

Embedded private images are rewritten to the anonymous, revocable
`/pages/public/<public_id>/images/<asset>` route. That route serves only image
assets still referenced by a currently public document. Unpublishing the page
or removing the image reference makes the URL return 404.

`/robots.txt` always blocks the private application and explicitly allows the
public directory, public page, and static asset families. When live site discovery is enabled it
also advertises `/sitemap.xml`; the sitemap otherwise returns 404. Public page
responses use both an HTML robots tag and `X-Robots-Tag`, combining the site
switch with the page opt-out. These controls affect crawler guidance, not
whether a public link can be opened or shared.

The public navbar initializes a small dynamic sharing module. It uses the Web
Share API where available, then the Clipboard API, a synchronous copy fallback,
and finally a selectable URL. It does not load the authenticated lifecycle or
a third-party sharing library.

## Jinja environment

`web/start/jinja.py` configures the template environment.

Custom tests:

- `datetime`
- `in_future`
- `in_past`

Formatting filters:

- `format_datetime`, `format_date`, and `format_time`
- `format_phone` and `format_number`
- `format_date_as_input_string`

Important globals include `VERSION`, `BUILD_ID`, `CAPTURE_ERRORS`, `TESTING`,
`render_icon`, `styles`, `is_starred`, `current_user`, `Action`, and `Resource`.
Semantic styles and icons come from generated maps described in
[INFRA_BUILD_STYLES.md](INFRA_BUILD_STYLES.md).

## Route conventions

Initial navigation renders a page template:

```python
@pages.route("<key>")
@permission(Resource.PAGE, Action.VIEW)
def view(key, **kwargs):
    return render_template("pages/page.html", page=kwargs["entity"])
```

Focused updates usually render one macro:

```python
@pages.route("<key>/tasks")
@permission(Resource.PAGE, Action.EDIT)
def tasks(key, **kwargs):
    return get_template_attribute("pages/tasks.html", "task_list")(
        kwargs["entity"]
    )
```

`get_template_attribute()` is the standard bridge between route handlers and
replaceable widgets. Templates define the DOM contract; frontend code fetches
the fragment and reinitializes its owning component. See
[FRONTEND_TEMPLATES_ATTRIBUTES.md](FRONTEND_TEMPLATES_ATTRIBUTES.md) and
[FRONTEND_VIEWS_LIFECYCLE.md](FRONTEND_VIEWS_LIFECYCLE.md).

Mutation routes return one of a small set of response shapes:

- JSON data for the owning component;
- an HTML fragment for replacement;
- `422` with a safe validation message;
- `{"reload": true}` for navigation-wide invalidation; or
- `{"modal": "..."}` for a server-rendered modal.

Use the narrowest response that represents the mutation. Deferred work returns
the operation envelope described in [BACKEND_JOBS.md](BACKEND_JOBS.md).

## Error handling

`web/start/errors.py` handles `GoogleAPIError`, `TemplateError`,
`HTTPException`, and uncaught exceptions. Authentication failures redirect as
appropriate; validation failures remain plain `422` responses; other failures
render the focused error template.

Local environments include traceback context. Production reporting keeps route
shape, endpoint, method, bounded content metadata, query-field structure, and
a short header allowlist while removing submitted values, identity data,
filenames, credentials, and payload-bearing context. Error responses include
`X-Lagniappe-Error` so the request wrapper can distinguish application errors
from ordinary HTML.

## Template organization

Templates live under `lagniappe/web/templates/`:

| Location | Responsibility |
| --- | --- |
| root macros | Common controls, navigation, tables, cells, badges, and filters. |
| `layouts/` | Base, login, error, and delete layouts. |
| entity folders | Page, project, file, form, user, category, and task surfaces. |
| `home/` | Home sections, notes, search entry, and ingress status. |
| `search/` | Search page and results. |
| `manual/`, `reference/` | User manual and help fragments. |
| `delete/`, `errors/` | Confirmation and failure surfaces. |
| `public/`, `testing/` | Public entity and test-only pages. |

Prefer a feature-local macro over route-assembled HTML. When a macro or its
required DOM changes, update template-contract evidence; see
[TESTING_TEMPLATE_CONTRACTS.md](TESTING_TEMPLATE_CONTRACTS.md).
