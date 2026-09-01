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
| `http/` | Shared user-directed and fixed-provider outbound HTTP policy. | This guide |
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
| `html.py` | Named HTML safety policies, Markdown rendering, extraction, and plain-text conversion. |
| `utility.py` | Encoding and MIME detection. |
| `constants.py` | MIME families and supported processing modes. |

### Executable HTML policies

`files/html.py` uses `nh3` for reusable tag, attribute, URL-scheme, comment,
and active-content filtering. `sanitize_html()` is the narrow semantic policy
for Markdown and file/report previews. Static Form content and anonymous public
documents use separate named policies so their page-owned images cannot widen
the narrow policy.

Policy producers return `SafeHTML`, an ephemeral runtime provenance marker.
Storage, JSON, formatting, concatenation, and parser round-trips are ordinary
strings and must pass the correct named policy again before an executable
server-template sink. BeautifulSoup passes in this module perform only
structural transformations such as task-list reconstruction and owned-image
canonicalization; they are not the security allowlist.

Any code that materializes file bytes must choose a `FileConsumer` from
`core/definitions/file_consumers.py`. The consumer declares the size limit and
read behavior before a direct-upload object is downloaded. Provider-side
Storage copies do not materialize the object; MIME sampling reads only an 8 KiB
prefix; application extraction and AI-inline consumers use their declared
bounded limits.

DOCX/XLSX fallback extraction applies a second, OOXML-specific boundary after
the 30 MiB compressed-file check. It preflights the ZIP central directory and
every member before parsing, rejects encrypted, ambiguous, traversal, ZIP64,
unsupported-compression, excessive-expansion, and unsafe relationship shapes,
then streams only the document/workbook XML parts through an entity- and
DTD-rejecting parser.

| OOXML boundary | Limit |
| --- | ---: |
| Central directory / members / member name | 4 MiB / 4,096 / 1,024 bytes |
| Uncompressed member / archive | 64 MiB / 256 MiB |
| Large-member compression ratio | 1,000:1 |
| Parsed XML / depth / elements / elapsed time | 64 MiB / 128 / 1,000,000 / 5 seconds |
| Worksheets / rows / cells | 256 / 100,000 / 250,000 |
| Shared strings / retained characters | 100,000 / 4,000,000 |
| Output text | 200,000 characters |

Unsafe archive, XML, relationship, coordinate, or shared-string structures fail
the extraction. Safe traversal ceilings return `OOXMLExtractionResult` with a
truncation reason once useful text exists; the AI summary prompt includes that
reason and never exceeds its 200,000-character extracted-context ceiling.

Durable CSV workflow state lives in `tools/ingress.py` and
`database/ingress.py`, not in the general file utilities. See
[BACKEND_INGRESS.md](BACKEND_INGRESS.md).

## External services

### Outbound HTTP boundary

Runtime code uses `tools/http/` for application-owned HTTP. It returns an
immutable `OutboundResult` with one of `ok`, `rejected`, `timeout`,
`http_error`, `too_large`, or `wrong_type`; neither body bytes nor the final URL
appear in its representation. Diagnostics may include only outcome,
scheme/host/port, HTTP status, size, and booleans describing URL structure.
They never include a path, query, fragment, credentials, response content, or
transport exception text.

User-directed profiles validate URLs up front and at every redirect, resolve a
hostname once per hop, reject the complete answer set if any address is not
global unicast, and try at most four validated addresses within one operation
deadline. Connections are pinned to the selected IP while the canonical Host,
TLS SNI, and certificate hostname remain the original host. Environment
proxies and automatic redirects are disabled. Every response is streamed
through the decoded-byte limit and closed, including redirects and failures.

| Profile | Scheme and accepted body | Limit | Redirects | Connect/read/deadline |
| --- | --- | ---: | ---: | --- |
| HTML metadata | Public HTTP/HTTPS; HTML or XHTML | 256 KiB | 5 | 0.5s / 1s / 2s |
| Bookmark image | Public HTTP/HTTPS; verified JPEG, PNG, GIF, WebP, or BMP | 10 MiB | 5 | 1s / 2s / 6s |
| Google profile image | Public HTTPS; the same verified raster formats | 10 MiB | 5 | 1s / 2s / 4s |
| Places autocomplete | Fixed `places.googleapis.com`; JSON | 1 MiB | 0 | 2s / 4s / 6s |
| Places details | Fixed `places.googleapis.com`; JSON | 1 MiB | 0 | 3s / 7s / 10s |

All current profiles make one application attempt. A trusted-provider profile
may add retries only by naming allowed methods, transient statuses, a finite
attempt count, and every backoff interval. User-directed metadata remains
synchronous and best-effort; stored URL and frontend payload contracts are
unchanged.

Some provider transports remain deliberately owned by their existing adapters
and are audited by the runtime source-inventory test:

| Owner | Transport rationale |
| --- | --- |
| `services/identity_platform.py` | Fixed Google Identity Toolkit endpoints plus Google-auth token verification; adapter operations retain their explicit deadlines. |
| `email/ai.py` | Fixed Resend API calls and provider-issued attachment downloads, bounded by the Resend adapter's timeout and attachment policy. |
| `deferred_jobs/scheduler.py` | Google-auth `AuthorizedSession` for the fixed Cloud Scheduler API. |
| `ai/core.py` | The Google Gen AI SDK owns network calls; direct `httpx` use is limited to classifying SDK transport failures. |
| Runtime credential and process/test-token adapters | Google-auth owns metadata/credential and token-verification traffic. |

Do not add a direct runtime `requests`, `urllib.request`, or `httpx` import for a
new feature. Extend the shared boundary, or document and add a narrowly owned
provider adapter to the audited inventory.

`tools/services/task_queue.py` creates deterministic OIDC-authenticated Cloud
Tasks and deletes known task names. Shared deferred work targets
`/process/jobs`; ingress, filter-cache refresh, notification email, and task
uncompletion retain focused process routes. Production accepts a dispatch only
when the provider returns a task identity.

`tools/services/identity_platform.py` owns server-side account and token
operations; see [AUTHENTICATION.md](AUTHENTICATION.md). `places.py` owns Places
autocomplete/detail calls and uses the requesting user's validated location
when present. Autocomplete uses 2-second connect/4-second read limits within a
6-second operation deadline; details use 3/7 seconds within 10 seconds.
Expected credential, transport, HTTP, size, media, JSON, and provider-shape
failures are captured once without response content or URLs and degrade to an
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
