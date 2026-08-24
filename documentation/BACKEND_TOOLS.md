# Backend Tools

`lagniappe/core/tools/` contains application services and provider adapters.
Entities own typed domain state; tools coordinate queries, transactions,
external APIs, durable workflows, and cross-entity effects. Flask routes remain
authorization and transport adapters.

## Ownership map

| Package | Responsibility | Focused guide |
| --- | --- | --- |
| `database/` | Raw Datastore and Cloud Storage operations, migrations, and transactional helpers. | [BACKEND_PERSISTENCE.md](BACKEND_PERSISTENCE.md) |
| `cache/` | Redis search, details, notification, operation, and document projections. | [BACKEND_CACHE.md](BACKEND_CACHE.md) |
| `deferred_jobs/` | Durable job start, dispatch, execution, locks, retry, and recovery. | [BACKEND_JOBS.md](BACKEND_JOBS.md) |
| `ai/` | Prompt construction, Gemini calls, read tools, reports, and deterministic execution. | [AI_PIPELINE.md](AI_PIPELINE.md) |
| `messaging/`, `mentions/`, `notifications/`, `email/notifications/` | User communication and supplementary email. | [BACKEND_COMMUNICATIONS.md](BACKEND_COMMUNICATIONS.md) |
| `polling/` | Versioned poll descriptors, projections, form state, and refresh deltas. | [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md) |
| `files/` | File inspection, extraction, download, and HTML conversion. | This guide |
| `filters/` | Redis JSON filter cache and JSONPath expression building. | [BACKEND_FILTERS.md](BACKEND_FILTERS.md) |
| `services/` | Identity Platform, Places, and Cloud Tasks clients. | This guide |
| `site/` | Site settings, exports, branding images, and recovery snapshots. | [INFRA_CONFIG.md](INFRA_CONFIG.md) |
| `tasks/` | Task ordering, recurrence, postponement, and combination. | [BACKEND_ENTITIES_TASKS.md](BACKEND_ENTITIES_TASKS.md) |
| `hosted_e2e/` | Hosted-test authentication and shared-data leases. | [TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md) |

Root modules are reserved for boundaries used across several domains:
`collaboration.py`, `dates.py`, `diagnostics.py`, and `ingress.py`. Put compact
shared identifiers in `core/definitions/identifiers.py`; do not grow a generic
utility bucket.

## Service design

A focused service normally has four layers:

```text
route or entity method
  -> domain service (authorization and orchestration)
  -> concrete persistence/provider module
  -> post-commit projection or delivery effect
```

Keep these rules intact:

- Raw persistence belongs in `tools/database/`; domain services should not
  spread Datastore query and transaction code through route modules.
- Properties own entity-bound values and pure transitions. Transactions across
  records, provider calls, retries, and delivery belong to services.
- Redis is disposable. A cache projection may accelerate a read, but it must
  name its durable authority and reconstruction path.
- Provider calls use shared runtime credentials and focused adapters. Do not
  create a second client or authentication path inside a feature module.
- Work that crosses an HTTP request or may be delivered more than once needs a
  durable idempotency boundary.
- Import concrete modules from packages whose `__init__.py` is only a marker.

## File tools

`tools/files/` separates file behavior by capability:

| Module | Purpose |
| --- | --- |
| `validate.py` | CSV parsing and schema suggestions. |
| `extract.py` | Stored-text extraction and Document AI OCR. |
| `ooxml.py` | `.docx` and `.xlsx` text extraction. |
| `downloads.py` | Bounded external image download. |
| `html.py` | HTML sanitization, extraction, and plain-text conversion. |
| `utility.py` | Encoding and MIME detection. |
| `constants.py` | MIME families and supported processing modes. |

Any code that materializes file bytes must choose a `FileConsumer` from
`core/definitions/file_consumers.py`. The consumer declares the size limit and
read behavior before a direct-upload object is downloaded. Provider-side
Storage copies do not materialize the object; MIME sampling reads only an 8 KiB
prefix; application extraction and AI-inline consumers use their declared
bounded limits.

Durable CSV workflow state lives in `tools/ingress.py` and
`database/ingress.py`, not in the general file utilities. See
[BACKEND_INGRESS.md](BACKEND_INGRESS.md).

## External services

`tools/services/task_queue.py` creates deterministic OIDC-authenticated Cloud
Tasks and deletes known task names. Shared deferred work targets
`/process/jobs`; ingress, filter-cache refresh, notification email, and task
uncompletion retain focused process routes. Production accepts a dispatch only
when the provider returns a task identity.

`tools/services/identity_platform.py` owns server-side account and token
operations; see [AUTHENTICATION.md](AUTHENTICATION.md). `places.py` owns Places
autocomplete/detail calls and uses the requesting user's validated location
when present. Autocomplete uses a 2-second connect/4-second read deadline;
details use 3/7 seconds. Expected credential, transport, HTTP, and provider-
shape failures are captured once without response content and degrade to an
empty result rather than failing the request.

## Cross-domain modules

- `dates.py` converts between UTC storage and the session user's timezone.
- `diagnostics.py` provides opt-in local timing and profiling decorators.
- `ingress.py` owns the durable CSV state machine and row mutation planner.
- `collaboration.py` contains shared collaboration rules used by document and
  communication workflows.

When adding a tool, choose the narrowest package that owns its durable or
provider boundary and add a façade export only when callers need stable shared
vocabulary across that subsystem.
