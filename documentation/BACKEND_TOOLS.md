# Backend Tools

The tools layer (`lagniappe/core/tools/`) provides infrastructure services used by entities and routes. It wraps Google Cloud services (Datastore, Cloud Storage, Vertex AI, Cloud Tasks), Redis caching, and various utility functions.

## Database (`tools/database/`)

Wraps Google Cloud Datastore and Cloud Storage for entity persistence and file storage.

### Data Services (`core.py`)

The `DataServices` singleton manages connections to Datastore and Cloud
Storage. Both clients receive the same project-bound Application Default
Credentials object used by the other runtime Google clients.

**KINDS enum** maps entity types to Datastore kind strings (all prefixed with `CONFIG.PREFIX`). Multiple entity types share kinds:

| Kind | Entities |
|---|---|
| `instances` | page, task |
| `models` | project, category, form, model_task, group, public_group |
| `users` | user |
| `files` | file, ingress |
| `filters` | filter |
| `history` | task_history, form_history, document_history |
| `activity` | note, notification |
| `analytics` | owner analytics records |
| `ai_observability` | bounded AI generation summaries |
| `site` | site-level records |
| `jobs` | durable deferred jobs |
| `job_locks` | target-scoped deferred-job ownership |

### Key and Entity Operations (`get.py`, `utility.py`)

**Key resolution** (`get.py`): `datastore_key(identifier)` accepts a Datastore Key, an entity with a `.key`, or a urlsafe string and returns a Datastore Key. `urlsafe_key(identifier)` converts to a urlsafe string.

**Entity retrieval** (`get.py`):

| Function | Description |
|---|---|
| `entity(identifier)` | Fetch a single entity by key or urlsafe string |
| `entities(*keys)` | Bulk-fetch by keys |
| `reserved(kind)` | Get reserved/system entities |

**Entity creation** (`utility.py`):

| Function | Description |
|---|---|
| `create_key(entity_kind, parent)` | Allocate a new Datastore key, optionally with a parent |
| `create_named_key(entity_kind, identifier, parent)` | Create a deterministic complete key |
| `create_entity(key)` | Create an empty Datastore entity for a key |
| `save(*entities)` | Batch-save entities with deduplication |
| `save_mutations(writes)` | Commit full and property-masked entity writes |
| `save_raw(*entities)` | Persist raw migration rows without typed save hooks |
| `delete_entities(entities)` | Delete typed durable rows and update site fingerprints |
| `delete_blobs(private_paths, public_paths)` | Run post-commit storage cleanup and collect provider errors |
| `initialize()` | Create default reserved entities if absent and report whether this was a truly fresh database |

**Query system** (`filter.py`): `Filter` and `Query` classes wrap Datastore queries with a composable filter builder. Supports `eq`, `any_of`, `all_of`, and compound filters.

### Site data migrations (`migrations.py`)

The owner-only **Apply Updates** action runs registered, idempotent raw-row
migrations from an append-only, version-pinned catalog in chunks of 100. Raw
writes preserve business timestamps and avoid constructing typed properties
from malformed persisted data. A transform mutates a copy and writes only after
validation; deterministic cleanup is recorded as a successful repair, while
unrecoverable rows remain unchanged and include a repair-surface link.

Each migration has a durable `site/data-migration:<id>` ledger record with its
completion version/build and five latest attempts. A transactional
`site/data-migrations-control` lease prevents concurrent runs. Execution stops
at the first failed catalog entry and resumes there on retry; completed
entries stay complete across later builds. Truly fresh databases baseline the
bundled catalog during startup without running transforms. Migration-ledger,
lease, and fresh-install baseline transactions retry their complete
read/check/write body after bounded Datastore contention, so concurrent
application workers cannot turn an ordinary startup race into a failed
initialization. **Refresh Cache** is rejected until the complete catalog is
current. See the
[data migration workflow](DATA_MIGRATIONS.md) for catalog authoring, failure
recovery, compatibility, and retirement rules.

### Assets (`assets.py`)

Cloud Storage file operations:

| Function | Description |
|---|---|
| `save_file(file, path, content_type, visibility)` | Upload a file to the appropriate bucket |
| `download_file(path, visibility, start, end)` | Download file bytes, optionally using inclusive byte offsets for range responses |
| `file_size(path, visibility)` | Read file byte size from storage metadata |
| `get_text(path, visibility, encoding)` | Download as text |
| `save_text(text, path, content_type, visibility)` | Upload text content |
| `copy_file(source_path, source_visibility, destination_path, destination_visibility)` | Server-side copy between buckets |
| `list_files(prefix, visibility)` | List objects under a bucket prefix |
| `get_signed_url(path, expires_in)` | Generate a time-limited signed URL for private files through IAM Credentials `signBlob` |
| `delete_file(path, visibility)` | Delete a file |
| `upload_site_image(filename, image_data)` | Upload site branding images to the public bucket |
| `create_site_export(data)` / `update_site_export(id, updates)` / `site_exports()` | Site-level metadata records for generated exports |

Buckets are addressed by visibility name: **public** (site images, public assets), **private** (user uploads and documents), **history** (document history), and **export** (exploded archive output).

#### File-consumer byte contracts

General uploads and Cloud Storage copies are not capped by an application
materialization limit. Any path that inspects file bytes must instead declare a
`FileConsumer` from `lagniappe/core/definitions/file_consumers.py` before it
can read a full direct-upload object. The current capability table is:

| Consumer | Limit | Read behavior |
|---|---:|---|
| Storage copy | None | Provider-side copy; application does not read the object |
| MIME detection | 8 KiB | Inclusive prefix range only |
| AI autofill attachment | 30 MiB | Inline prompt bytes |
| AI report input | None | Stored through multipart or provider-side direct-upload copy; the application does not read the full object |
| CSV ingress | 30 MiB | Full text parse and row projection |
| OOXML extraction | 30 MiB | Full ZIP package extraction |
| Text preview | 30 MiB | Full decoded text fallback |
| Image fingerprinting | 100 MiB | Full local-image checksum fallback |
| Site image processing | 100 MiB | PIL decode and generated variants |

`DirectUploadFile.read()` and `seek()` reject calls without a named consumer.
Consumer checks use the verified Cloud Storage blob size for direct uploads and
seek-based metadata for multipart/in-memory streams, so rejection occurs before
the object is downloaded. `read_sample()` is independently capped at 8 KiB.
Asset persistence skips the file-like seek for direct uploads so the existing
server-side copy path remains large-file capable.

These limits require no datastore migration. Durable File assets use their
stored size metadata (falling back to Cloud Storage metadata where necessary),
and temporary direct uploads are reloaded and generation-checked before use.

### Site Export (`site_export.py`)

Builds owner-started, static HTML archives under the export bucket. The builder writes text objects directly with `save_text`, copies file/document assets with server-side storage copy operations, and writes `manifest.json` last so a completed metadata record always points at a complete archive. Export metadata lives in `KINDS.site` records with `type=site_export`, not as a content entity.

The archive root is `html/YYYY-MM-DD/YYYYMMDDTHHMMSSZ-<short-id>/` and includes `index.html`, category/page/project pages, form schema JSON, copied files, `assets/archive.css`, `README.txt`, and `manifest.json`.

## Cache (`tools/cache/`)

Redis-backed caching layer for search indexing, notification projection, sync
state, rate limiting, and filter results. Page/component ETag fingerprints
remain durable Datastore records rather than Redis values.

### Initialization (`core.py`)

The `Cache` singleton connects to Redis Cloud and creates a RediSearch full-text
index with weighted fields. `REDIS_TLS` enables verified transport using the
CA bundle named by `REDIS_CA_CERT`; setup and runtime share the same connection
option builder, and the JSON cache reuses this client rather than opening a
second connection pool.

| Field | Weight | Purpose |
|---|---|---|
| `name` | 4 | Entity name (highest priority) |
| `desc` | 1 | Description |
| `doc` | 0.5 | Document content |
| `values` | 0.25 | Form submission values |
| `kind` | tag | Entity type filter |
| `type` | tag | Subtype filter |
| `requires` | tag | Permission-based access control |

### Cache Keys (`keys.py`)

Three key enums:

- **`Keys`**: Core keys (search indexes, entity hashes, importing state, filter cache, rate limits)
- **`Search`**: Per-entity-type hash keys (`{prefix}{kind}:{urlsafe_key}`)
- **`Sync`**: Per-widget/entity sync registrations and cached state

`Keys.NOTIFICATIONS` and `Keys.NOTIFICATION_EPOCH` are per-user and expire
after 30 minutes of inactivity. The first is a versioned membership hash; the
second is the independently watched mutation epoch used to prevent a cold seed
from publishing stale membership.

### Writing (`add.py`)

`update(*entities)` writes entity data to the hash cache and parent JSON filter
indexes. For each entity, it calls `entity.to_cache` to get the cache
representation, writes it as a Redis hash, and stores entity details in the
hash lookup. Search hashes store `details_key` and optional `parent_key`
pointers, not embedded details. The hash lookup also stores parent references
as `parent_key`; `get_details_by_hash()` hydrates those pointers back into a
`parent` detail block for callers. Page/task updates also refresh parent JSON
indexes used by saved filters.

### Details (`details.py`)

`get_details_by_hash(hashes)` loads entity details from the Redis hash lookup.
Redis stores parent references as `parent_key`; this helper hydrates those
pointers back into `parent` detail blocks for callers. Search-result hydration
also lives here so query code does not need to know the detail storage format.

### Notification projection (`notifications.py`)

The notification projection stores only schema version, generation UUID,
revision, and notification-key membership. Count is derived from membership;
notification bodies stay in Datastore. Warm peeks are Redis-only and slide the
30-minute expiration of both the state and epoch keys.

Cold population watches both keys, records the epoch, performs one keys-only
ancestor query, and writes a new generation. Any concurrent committed
notification mutation increments the watched epoch, so optimistic transaction
retry reruns the query instead of publishing stale membership. Post-commit
notification effects upsert/remove keys and advance the revision once per
logical mutation. When state is absent they advance only the epoch; they never
query Datastore. `/l/notifications` runs its list keys query inside the same
watched repair and reuses those keys to fetch bodies.

Redis errors are rebuildable provider failures: they are captured after the
durable mutation and cannot roll it back. `/l/ping` similarly omits the optional
notification-state header on Redis error while preserving its server-health
response.

### Querying (`query.py`)

`search(query, user)` runs a full-text search against the Redis index with permission filtering. Results are filtered by the user's `requires` tags so users only see entities they have access to. Name relevance outweighs all secondary fields combined, and an optional weighted query clause boosts categories, projects, and pages when every normalized query term occurs in the entity name. Per-kind document scores remain a broader relevance multiplier. Search results are hydrated through `get_details_by_hash()` before being returned, so parent display data comes from the current entity hash details rather than a duplicated search-row blob.

`entity_search(query, kind, user)` and `kind_search(kind, user)` provide kind-filtered search.

### Utilities (`utility.py`)

| Function | Description |
|---|---|
| `check_hash(hash)` | Check if a hash is already in use |

Ingress execution state is durable database state managed by
`core/tools/ingress.py`; Redis is not an authority for import progress.

### Collaborative documents (`documents.py`)

Revisioned collaborative-document state and expiring presence. One isolated
Redis string key per document stores compact checkpoints and bounded Yjs deltas
under optimistic transactions. Presence sets reference expiring client-detail
hash fields; no browser-routing or broadcast registrations are stored.

| Function | Description |
|---|---|
| `poll_document(...)` | Refresh presence and return a snapshot or the deltas after a known revision |
| `apply_document_update(...)` | Append a Yjs delta and accept a checkpoint only from the current generation/revision |
| `update_document_asset(...)` | Refresh durable document metadata without replacing the live generation |
| `close_presence(client_id, sync_ids)` | Remove a page-scoped client from its document presence sets |
| `clear_document(sync_id)` | Drop externally invalidated live document state |

## AI (`tools/ai/`)

Google Vertex AI integration for text generation, image generation, and structured output.

### Core (`core.py`)

The `GenAI` singleton wraps the Google GenAI client. It resolves primary,
utility, and image models from the live Datastore `site/ai` settings before
each top-level generation, falling back to deployed `CONFIG` values. A text
generation pins that resolved model across retries, tool calls, and any
structured final pass. It provides `generate_content(prompt, *, validator=None)` and
`generate_image(prompt, aspect_ratio=None)` methods, configures safety settings
(block only high-severity content), and supports Google Search grounding.

### Text-generation observability (`observability.py`)

AI generation observability is an operator-controlled, owner-only diagnostic
dataset. It is disabled by default. Setup explicitly asks whether to enable
`AI_OBSERVABILITY` during AI configuration and preserves that choice on later
runs and recovery. While enabled, every `GenAI.generate_content` call is
sampled. Gemini/Imagen image-generation calls are not sampled, although the
text-based image aspect-ratio selection is a normal `generate_content` call.

Each call writes one best-effort version-1 summary to the separately prefixed
`<PREFIX>ai_observability` Datastore kind. A random UUID is both the named key
and correlation ID. The allowlisted record includes only controlled prompt
contract identity, runtime model/location/tier, application-visible provider
call and response counts, token totals, bounded traffic/error categories,
tool-call counts and known names, cache/file/result-size aggregates, validation
or repair outcome, duration, and optional deferred job type/version/attempt.
It never stores prompts, tool arguments/results, generated text, error messages,
file content, user/entity/report/file/job identifiers, or authored values.
Persistence and retention failures are logged without changing AI results or
exceptions.

After each successful summary write, the app makes one keys-only deletion of at
most 500 records older than 30 days. This is activity-driven retention rather
than a strict Datastore TTL: stale records may remain until another enabled text
generation occurs. Owners can inspect and clear the AI dataset independently on
the Analytics page. The dashboard queries at most the latest 1,000 summaries in
the selected period. Counts cover only provider boundaries visible to the
application; retries performed internally by the Google GenAI SDK are not
observable and must not be inferred from these summaries.

### Prompt Builder (`prompt.py`)

The `Prompt` class builds structured prompts with:

- **Context blocks**: Key-value context (entity data, schema, etc.)
- **Instruction blocks**: Task-specific instructions
- **Output format**: JSON, HTML, TEXT, or IMAGE with format-specific rules
- **Examples**: Few-shot examples
- **File attachments**: Binary content (images, documents) for multimodal prompts

It also tracks Google Search/function tools, provider response schemas, thinking
and service tiers, tool/file limits, and stable-instructions-before-context
ordering. `preview()` renders the system instruction and built prompt text; it
does not render provider configuration, attachment parts, future tool results,
or the structured-final request. See [AI_PIPELINE.md](AI_PIPELINE.md) for the
context-placement and prompt-transparency architecture.

### Workspace Collection Semantics

AI prompts treat categories as collection scopes, pages as durable subject
collections within those scopes, files as individual source artifacts, and
tasks as actions or occurrences concerning a page subject. Organize considers
the complete upload batch before proposing pages, clusters files by the most
specific stable subject a person would browse for later, and avoids deriving a
page name from each document, account, provider, date, or identifier. Each
distinct cluster resolves to its own specific existing or new page. A broadly
related category-level or overview page is not used as a catch-all for multiple
clusters unless the user explicitly requests a single page.

A category default page form is conservative and optional. AI may propose one
only when the request or evidence unambiguously defines the category's pages as
repeated instances of one type with a small stable schema that applies to
essentially every page. Owner-, context-, or domain-oriented categories with
different page subjects have no default form. This restriction does not prevent
a specific page from using its own close-fitting page form.

Generated pages follow the same distinction. When no page form is attached,
the page-generation prompt omits `form_schema` and the result must provide
`name` and `description` directly; no phantom submission is created. When a
real page form is attached, its schema and submission are used. Generated
top-level `name` and `description` values are canonical; the corresponding
default form fields fall back only when a top-level value is absent, and the
resolved values are written consistently to both projections.

### Function Tools (`functions.py`, `function_definitions/`)

AI function declarations are registered in `functions.py` and enabled per prompt
with `Prompt.enable_tools(...)`. Organize/Create use the shared read-only
context tool set from `organize.py`; Ask extends that set with
`get_task_history`, which returns task completion rows via `TaskHistory.to_ai()`
including the name and description saved for each completion, completion dates,
submission values, and attached file metadata.
Ask also exposes `get_filter_schema` and `query_workspace_filter` for structured
queries over a project's tasks or a category's pages. Schema discovery derives
the allowed field, comparator, choice, model-task, and attached-form values from
the existing filter definitions. Queries synchronously warm the existing shared
parent cache, compile only validated definitions, recheck each result with the
Ask user's view permission, and return a bounded array of `entity.to_ai(user)`
records. The cache remains permission-neutral; user scoping happens on results.

Ask report generation is owned by the durable `AskReportAdapter`. The UI creates
a pending report and deferred job; the adapter selects the initial or revision
prompt, generates and validates the response, and checkpoints the proposal
before `ReportAdapter.apply()` publishes it. Publication clears stale execution
results and sets the report to `complete` for answers without actions or `ready`
for reviewed follow-up actions. Ask validation requires a non-empty summary,
confidence from 0 to 1, optional string HTML, and the same deterministic action
validation used by Organize/Create. Invalid model output is given one
schema-aware repair pass. If an Ask repair still has unresolved workspace
references or malformed action data, only the unsafe actions become review
items while valid actions and the usable answer are preserved. The retained
answer is prefaced
with an explicit notice that its workspace changes are suggestions and have
not been applied. Ask prompts keep internal entity hash tokens out of summaries
and HTML answers, using readable names and links instead. Organize likewise
keeps executable hashes out of its summary, issues, labels, and reasons; repair
responses describe the resulting plan without exposing validation mechanics.
The shared Ask/Organize context tools also include `get_form_instances`, a
read-only form usage lookup that returns viewable pages/tasks using a form,
their edit permission flags, completion state, URLs, and compact submission
data. Use it when a report needs exact page/task rows for reviewed batch
submission updates.

### Single-form Autofill (`ai/autofill.py`)

Page and task autofill share `autofill_prompt_data()`. For task targets, the
helper resolves compact parent-page context: name, description, document, and
category name/description. It does not include the task's history, prior
completions, sibling tasks, completed page tasks, or parent-page files. The
target contributes its own name, description, current submission, form schema,
and directly attached files. Page targets likewise contribute only page files.
Each visible stored attachment is included up front through its full
`File.to_ai()` projection, whether or not it has a summary.

Before making a provider call, a deferred autofill checks every readable
attached file whose summary option is enabled. It waits in the summarizing
phase and checks again after 60 seconds while any such summary is pending;
dependency-only checks do not consume the provider retry allowance. A failed
summary stops autofill with an actionable message so the user can fix or remove
the file and run it again. Files without summarization enabled do not block
autofill.

Google Search remains available for focused missing public facts. Autofill does
not expose entity search/lookup, page/category detail, page-task, or task-history
functions. When the target has stored attachments, `get_file` is the only
function tool and is capped at two rounds: use a supplied summary first, fetch
extracted text only for a specific unresolved field, and request the original
file only if the extracted text is insufficient. With no stored attachments,
Autofill has no function tools. One-off request attachments are already sent
inline and do not enable `get_file`. This behavior is recorded as Autofill
prompt observability contract version 2; version 3 identifies the
explicit submission-output contract. Autofill keeps its dynamic field ids in
the prompt's actual form schema and does not attach an untyped provider response
schema, which can cause compliant models to collapse the result to `{}`.
Application form validation keeps only real field ids and normalizes their
values. When `get_file` is available but the supplied summary is sufficient, a
no-tool JSON response is accepted directly without a structured-final provider
round.

Page-info, task-form, and category-tool Create Page submits persist the target
and the user's partial submission, create a pending notification, and start a
shared `DeferredJob`; production delivers it to `/process/jobs`. The worker
reloads the target and user, rechecks current edit/AI permission, rebuilds the
shared context, applies the generated submission, and sends a terminal
operation status for the exact source/destination widget. Optional
one-off prompt attachments use direct-upload records so they remain available
across retries; terminal job cleanup deletes the temporary object after success
or failure.

Existing page/task targets also acquire a durable `form-autofill` lock in the
same transaction as the job. While it is active, form submit/quick-edit/default
routes reject conflicting mutations. The unified `/l/poll` contract returns an
active `form-lock` independently of fingerprint drift, allowing the browser to
disable the form and replace the complete submit/autofill-context action area
with progress on reload or in another tab. Forms do not register with document
sync. Target editors may read the bounded operation status even when a
different editor started the job. CreatePage autofill explicitly skips the
target lock because the new Page is not an already-mounted shared edit surface;
it retains deferred idempotency, status, and form-revision drift protection.

### Report Runner (`report_runner.py`)

Stored AI report proposals are executed deterministically by `run_report()`.
Ask and Organize proposals can include reviewed edit actions in addition to
creation and file attachment actions:

| Action | Behavior |
|---|---|
| `add_form_to_page` | Attaches an existing or report-created page form to an existing page without requiring a category reference. It checks page edit permission, rejects task forms, records the previous form, and restores that form on undo. |
| `add_category` | Adds an existing category to an existing page without changing the page's primary category. The runner checks edit permission on both page and category, and undo removes only categories the report actually added. |
| `move_page` | Moves an existing page to an existing category after checking edit permission on both. Existing form and submission data are preserved. |
| `move_task` | Moves an existing task to `to_page` after checking edit permission on both. Form, submission, project/model, completion, and files are preserved. |
| `move_file` | Moves an existing file attachment from one exact source page/task to one exact target page/task after checking edit permission on both endpoints. |
| `rename_entity` | Changes only the `name` of an exact editable entity. It does not require a form or submission, and undo restores the previous name. |
| `update_submission_fields` | Applies exact reviewed `{page/task, schema_id, new_value}` rows to existing pages/tasks. Values validate through the target's current form field; unknown fields or values rejected by validation do not persist. |
| `update_form_schema` | Applies bounded additive schema operations only: optional `add_field` and missing select/radio `add_select_option`. Form saving continues to use normal schema/version history. |
| `delete_page` | Records a manual post-run cleanup suggestion. The runner does not delete the page; the report result renders the normal page delete control so the existing modal, permission checks, and cascade behavior handle deletion. |

Completed-task evidence is represented as `create_task` actions with
`completed_on`. When no exact task target is supplied, the runner reuses only
one editable task with the same page, model task, and canonical stable name;
date/installment wording is removed from that name, while ambiguous matches
remain separate. The newest event stays on the live task and older dated events
become task history. Exact `task` and `task_action` references remain overrides.
`undo_report()` reverses completed executions by restoring move parents,
previous schema/submission field values, removing report-created file links, and
deleting created entities while preserving the report's uploaded input files.

Execution is submitted as a dedicated `report-execution` `DeferredJob`; the
request returns after durable queueing and the worker calls `run_report()`.
The job reloads the report and actor, rechecks current permission and the
reviewed proposal fingerprint, renews its lease while saving, and publishes the
same notification/status completion contract as report generation. The
versioned per-action recovery ledger remains stored in `report.result` and is
the authority for mutation recovery. Each run records the proposal fingerprint,
a deterministic idempotency key for every action, its before-state, any
preallocated output keys, attempt count, expected committed state, and
`pending`, `applying`, `complete`, `skipped`, or `failed` status. Action output
and the report's `complete` checkpoint are saved in the same entity mutation
batch.

A failed report can be retried from the first non-complete action. The runner
validates the completed prefix and reconciles an interrupted `applying` action
before calling its handler again; create actions reuse their preallocated key.
Permission is checked again at recovery time. Completed-task actions that reuse
a live Task are checkpointed as mutations, so retry validates the Task state
and undo restores its previous fields and relationships instead of treating it
as a no-op create.

`undo_report()` can compensate either a complete report or the completed
prefix of a failed report. Reverse actions have their own applying/complete
checkpoints, so an interrupted undo resumes safely. Successful undo retains
the ledger with `status=undone`; it is not silently discarded. The report page
offers **Retry Proposal**, **Undo Completed Actions**, and **Resume Undo** for
the corresponding states.

Only current versioned ledgers are recoverable. Proposal execution uses its own
deferred-job adapter around the ledger rather than reusing the generation
checkpoint contract; undo is a separate synchronous action.

The provider response schema declares the structural fields of each
`update_submission_fields` row, including its page/task reference, `schema_id`,
and heterogeneous `new_value`. It is intentionally not rebuilt from individual
forms: the final report schema is fixed before read-only tool discovery
finishes. Exact form membership and value semantics remain runtime validation
owned by the resolved entity's current form. Workflows that need a form-shaped
dynamic generation contract should use a separate target-aware completion
stage, as Organize does for new page/task submissions.

### Organize Pipeline (`ai/organize.py`)

An Organize submission containing instructions but no uploaded files is handled
by Ask. The report is stored and queued as an Ask report; ordinary uploads and
non-empty signed-upload manifests continue through Organize.

The Organize request stores signed direct-upload metadata on the pending report
and returns before copying uploaded objects into permanent `File` assets. The
shared `OrganizeReportAdapter` finalizes those records one at a time. It retains
each temporary object while copying and saving the attached `File` plus its
updated `report.upload_manifest` checkpoint, then deletes the temporary source.
A retried process can therefore repeat an interrupted copy, skips files that
were already checkpointed, and cleans up temporary sources left behind after a
completed checkpoint. Report deletion cleans up temporary objects that never
reached a checkpoint.

After ingestion, Organize uses two configured models across up to three
generation stages. First, the utility model generates and saves each missing
file summary together with up to two nonempty, deduplicated, independently
searchable terms.
Each saved term is then searched through the permission-filtered Redis index for
at most five category, page, or form candidates, including the ordinary search
snippets. This retrieval adds no model call. Those bounded results are embedded
beside that file's summary. Second, the primary model considers the complete
batch, clusters files by stable subject, chooses or creates workspace structure,
and returns the
structural proposal JSON with exact report file refs assigned to page/task
actions; it does not generate form values. Third, when that structural proposal
selects one or more page/task forms, the same primary model runs one more JSON
call to fill them using compact context containing the report intent,
deduplicated schemas, per-record relationships, and the saved summaries assigned
to each record. Organize skips this third generation call when there are no
form-backed targets.

Planning starts with the per-file retrieval candidates instead of being required
to call `list_workspace_resources` on every run. It can batch `get_entity` calls
for plausible results whose names, parents, and snippets are not sufficient, and
can still use the inventory, category-page scan, or workspace search tools when
the bounded prefetch misses relevant structure. Retrieval candidates do not add
per-entity edit checks to the prepass.

Large report files are not rejected at intake. When the utility summarizer can
read the provider-hosted file, Organize still attempts a normal summary. If a
file above the large-asset threshold is unsupported or does not yield a
summary, the prepass saves `File too large to summarize.` as its summary and
continues. Planning still receives the file's name, type, size classification,
and executable report reference so it can place and preserve the attachment.

Page file upload also supports a synchronous summary prepass when several files
are submitted together. Whenever summarization is requested, that HTTP route
requires `AI.CREATE` before creating the `File` entities or starting summary
generation. Ordinary single-file summarization uses the deferred file-summary
adapter, which checks the same tier again at worker authorization time. A
provider rejection for a PDF that exceeds its supported page limit is stored as
a clear file-summary error and treated as an expected input limit rather than
an application exception.

Planning validation performs narrow deterministic repairs before asking the
model to rewrite a rejected proposal. In particular, otherwise complete
`create_form` and additive `update_form_schema` fields receive stable IDs,
titles, and safe default text-input subtypes locally. An `add_form_to_page`
action missing its form reference is linked locally when exactly one compatible
earlier page-form creation exists. Validation also compares the complete report
file manifest with executable attachment actions. If any upload lacks a valid
`attach_file_to_page` or `attach_file_to_task` action and target, the proposal
enters model repair; a repair that still omits a file falls back to a safe
review-only report rather than exposing an executable partial organization.
Planning prompts instruct the model to read the page/task form guidelines
before creating a form and the schema-evolution guidelines before updating one;
successful tool provenance is not currently retained or verified. The provider
response schema is a typed union of action-specific variants. Each
variant permits only its own data fields and requires its executable references;
for example, `add_category` requires both a page and category reference and
cannot receive task-completion or submission-update fields. Form creation and
additive schema updates also use typed nested variants. The application
validates the returned proposal before execution, and the provider schema
prevents many malformed cross-action shapes from being generated in the first
place. If the model's repair still contains unsafe action references or omits a
required page/form or page/category reference, only those actions become
`needs_review` items and the remaining valid plan is preserved. If the repaired
plan is still structurally invalid, Organize returns one accurately labeled
review-only proposal instead of preserving unexecuted claims or exposing
validator text as a failed report. Recovered invalid model output is kept in AI
debug diagnostics without an application exception. A repair that still fails
validation but can be converted to a safe review result remains a handled
diagnostic and is not reported to Sentry; only failures that cannot produce a
valid fallback are captured as application errors.
Review-only reports are labeled **Needs review**, remain revisable, and do not
show an Execute button until the proposal contains an executable action.

The completion prompt uses JSON response MIME without a provider response
schema. Submission keys are dynamic form field ids; declaring `submission` as
an untyped object in the provider schema causes compliant models to return an
empty object. The application validator supplies the strict boundary by keeping
only ids from each resolved form schema.

The completion call does not reread original files or use web/workspace tools.
Its action-keyed output is filtered to exact schema ids. Partial submissions are
retained. When no fields are supported, the record, form, and attachments remain
in the proposal with an empty submission and a visible reason.
`generate_organize_report()` owns planning, completion, and final strict
validation so callers cannot publish an unfinished structural plan.

When the report executes, created page/task submissions pass through the normal
`ai_submission()` field validators before persistence. This normalizes field
types and removes unknown schema keys just like interactive autofill.

Run the synthetic medical/receipt role-separation corpus against the configured
live model with:

```bash
venv/bin/python -m testing.utility.organize_submission_eval --runs 3
```

This command is the live-provider quality evaluation. Deterministic Organize
checkpoint publication and proposal application belong to the deferred-adapter
unit suite:

```bash
venv/bin/python run.py test testing/tests_unit/test_023_deferred_jobs.py::test_organize_resumes_plan_checkpoint_without_second_planning_call
```

Browser coverage instead starts reports through the public tools UI, observes
the durable job lifecycle, and verifies the rendered terminal result. It does
not call the provider or proposal-completion helper directly.

### Guidelines (`guidelines/`)

Modular prompt guidelines organized by concern:

| Module | Purpose |
|---|---|
| `organize.py` | Shared planning, action, tool, and preflight policy bundles |
| `context.py` | Entity context formatting |
| `forms.py` | Form schema generation rules |
| `pages.py` | Page content generation rules |
| `project.py` | Project creation rules |
| `category.py` | Category creation rules |
| `scheduling.py` | Task scheduling rules |
| `schema_evolution.py` | Bounded additive form schema update rules |
| `images.py` | Image prompt construction rules |
| `output.py` | JSON/HTML/text output formatting rules |
| `summary.py` | Summarization guidelines |

### Generation Functions

| Function | Input | Output |
|---|---|---|
| `generate_schema(prompt)` | Built schema prompt | JSON form schema |
| `generate_ai_text(prompt)` | Built text prompt | HTML text |
| `generate_ai_image(prompt)` | Built image prompt | `BytesIO` image buffer |
| `generate_category(prompt)` | Built category prompt | Category JSON |
| `generate_project(prompt)` | Built project prompt | Project JSON |
| `generate_pages(prompt)` | Built page-generation prompt | Page JSON array |
| `generate_schedule(prompt)` | Built scheduling prompt | Schedule JSON |
| `summarize_file(file)` | File | Starts a deferred file-summary job |
| `generate_summary(file, ...)` | File and summary options | Immediate utility-model summary result |
| `generate_autofilled_submission(prompt)` | Built form prompt | Submission JSON |

## Files (`tools/files/`)

File processing utilities for uploads, text extraction, and CSV parsing.

| Module | Purpose |
|---|---|
| `validate.py` | `process_csv()` parses CSV files, `create_schema()` generates form schemas from CSV headers |
| `extract.py` | `get_file_text()` extracts text from uploaded files, `ocr_file()` uses Document AI for image/PDF OCR |
| `ooxml.py` | Lightweight `.docx`/`.xlsx` text extraction for AI summary fallback without storing a File text asset |
| `utility.py` | `determine_encoding()`, `determine_mimetype()`, `htmlize()` |
| `constants.py` | MIME type categorizations (document AI, image, preview, text, code) and encoding options |

Durable CSV import orchestration lives in `core/tools/ingress.py`, not in the
file utility package. `IngressMutationPlanner` validates and projects rows,
commits one resumable row mutation at a time, and advances the persisted
Ingress cursor/status through transaction-guarded database helpers.

## Filters (`tools/filters/`)

| Module | Purpose |
|---|---|
| `build.py` | `FilterExpression` -- builds JSONPath expressions from filter definitions |
| `cache.py` | `FilterCache` -- caches filter results in Redis as JSON, keyed by entity hash + access level |

## Standalone Tools

### `dates.py`

Timezone-aware date utilities. All dates are stored as UTC in Datastore. Conversion functions use the user's timezone from the Flask session:

| Function | Description |
|---|---|
| `user_timezone()` | Get user's timezone from session (falls back to UTC) |
| `utc_datetime_to_user_date_string(dt)` | Format as YYYY-MM-DD in user timezone |
| `user_date_string_to_utc_datetime(s)` | Parse user-local date string to UTC datetime |

Also includes task scheduling helpers for recurring date calculations.

### `task_queue.py`

Google Cloud Tasks carries authenticated HTTP POST requests to internal
`process` routes. The shared deferred-job registry sends production work to
`/process/jobs` and delayed feedback to `/process/jobs/feedback`; in development
it runs shared jobs in local daemon threads. In testing, most adapters remain
pending for deterministic test-controlled execution, while adapters explicitly
marked synchronous (currently site export) run inline. Ingress, cache refresh,
and scheduled task uncompletion retain their specialized process routes. A
production shared-job dispatch is accepted only when `create_task()` returns a
task identity. An explicitly disabled production queue fails the job, runs
adapter failure/cleanup compensation, completes its pending notification, and
propagates the configuration error. A transient provider exception instead
leaves the transactionally created job and notification pending; the scheduled
reconciler can redispatch that durable intent without repeating the browser
request.

| Function | Description |
|---|---|
| `task_name(task_id)` | Build the deterministic fully qualified task name used for cancellation and per-attempt deduplication. |
| `create_task(endpoint, payload=None, delay_seconds=0, *, task_id=None, dispatch_deadline_seconds=None)` | Create an OIDC-authenticated POST with optional schedule, stable task ID, and delivery deadline. |
| `delete_task(task_name)` | Delete a scheduled task by name; an already-missing task is treated as success. |

**Use cases:**

| Task | Endpoint | Triggered By |
|---|---|---|
| Filter cache update | `process.update_cache` | Filter creation or entity changes |
| CSV import execution | `process.ingress` | Import start |
| Task uncompletion | `process.uncomplete_task` | Task schedule creates new task |
| Shared deferred jobs | `process.deferred_job_process` (`/process/jobs`) | Report generation/revision, page/task autofill, page generation, site export, file OCR, and file summary |
| Long-running feedback | `process.deferred_job_feedback` (`/process/jobs/feedback`) | Production deferred jobs that start with a pending notification |
| Deferred-job recovery | `process.deferred_job_reconcile` (`/process/jobs/reconcile`) | Five-minute Cloud Scheduler OIDC request while recovery-required jobs exist; redelivers missing/expired work, completes terminal delivery, and self-pauses when empty |

See [BACKEND_ENTITIES.md](BACKEND_ENTITIES.md) for the durable job record and
[AI_PIPELINE.md](AI_PIPELINE.md) for the lease, retry, checkpoint, context, and
browser-delivery architecture.

### `site_image.py`

Generates site branding images (favicon, PWA icons, OpenGraph image) from an uploaded image. Uses PIL for resizing, background removal via flood fill, and icon generation at multiple sizes.

### `location.py`

Google Places API integration. It refreshes and reuses the shared ADC access
token, then queries the Places API for autocomplete suggestions and place
details. Includes user location from the session for biased results.

### `external.py`

External URL metadata extraction. `get_link_attributes(url)` fetches a URL and extracts OpenGraph/meta tags (title, description, image) using BeautifulSoup. Used by the bookmark form element.

### `utility.py`

General utilities: `short_hash(value)` (SHA-256, first 12 chars), `short_uuid()`, `strip_tags(html)` (BeautifulSoup text extraction), `download_image(url)`.
