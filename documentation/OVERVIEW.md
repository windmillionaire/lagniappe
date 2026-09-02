# Documentation

These guides explain the current Lagniappe architecture and development
workflows. Start with the narrowest guide that owns the code you are changing,
then follow its links for adjacent contracts. Installation commands for users
begin in the [README](../README.md).

## First reads

| Area | Start here |
| --- | --- |
| Backend entities | [BACKEND_ENTITIES.md](BACKEND_ENTITIES.md) |
| Flask routes and templates | [BACKEND_WEB.md](BACKEND_WEB.md) |
| Frontend application | [FRONTEND_OVERVIEW.md](FRONTEND_OVERVIEW.md) |
| Views and widgets | [FRONTEND_VIEWS.md](FRONTEND_VIEWS.md) |
| Synchronization | [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md) |
| Configuration and setup | [INFRA_CONFIG.md](INFRA_CONFIG.md), [INFRA_SETUP.md](INFRA_SETUP.md) |
| Tests | [TESTING.md](TESTING.md), [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md) |

## AI

| Guide | Covers |
| --- | --- |
| [AI_PIPELINE.md](AI_PIPELINE.md) | End-to-end AI request, job, application, and browser flow. |
| [AI_CONTEXT.md](AI_CONTEXT.md) | Context assembly, prompt inputs, tool schemas, and privacy boundaries. |
| [AI_WORKFLOWS.md](AI_WORKFLOWS.md) | Autofill, summarize, create, organize, and form-generation workflows. |
| [AI_EMAIL.md](AI_EMAIL.md) | Inbound email webhooks, attachment retrieval, reports, review, and feedback. |
| [AI_EXTERNAL_API.md](AI_EXTERNAL_API.md) | REST API keys and permission-bounded external Ask, Create, and Organize plans. |

## Backend

| Guide | Covers |
| --- | --- |
| [BACKEND_ENTITIES.md](BACKEND_ENTITIES.md) | Entity composition, registry, relationships, lifecycle, and fetch model. |
| [BACKEND_ENTITIES_PROPERTIES.md](BACKEND_ENTITIES_PROPERTIES.md) | Property descriptors, contexts, validation, serialization, and forms. |
| [BACKEND_ENTITIES_MUTATIONS.md](BACKEND_ENTITIES_MUTATIONS.md) | Save/delete invariants, indexes, history, cascades, and notifications. |
| [BACKEND_ENTITIES_TASKS.md](BACKEND_ENTITIES_TASKS.md) | Task ownership, requirements, scheduling, recurrence, and combined tasks. |
| [BACKEND_PERSISTENCE.md](BACKEND_PERSISTENCE.md) | Datastore access, explicit fetch scopes, queries, batching, and transactions. |
| [BACKEND_CACHE.md](BACKEND_CACHE.md) | Redis projections, fingerprints, documents, invalidation, and failure policy. |
| [BACKEND_JOBS.md](BACKEND_JOBS.md) | Durable deferred jobs, leases, adapters, callbacks, and operation state. |
| [BACKEND_COMMUNICATIONS.md](BACKEND_COMMUNICATIONS.md) | Email, notifications, push, and user-facing communication boundaries. |
| [BACKEND_TOOLS.md](BACKEND_TOOLS.md) | Ownership map for the `lagniappe/core/tools/` packages. |
| [BACKEND_DEFINITIONS.md](BACKEND_DEFINITIONS.md) | Shared enums, permissions, attributes, ordering, asset types, and exceptions. |
| [BACKEND_FILTERS.md](BACKEND_FILTERS.md) | Filter entities, JSONPath expressions, cache records, and value alignment. |
| [BACKEND_INGRESS.md](BACKEND_INGRESS.md) | CSV staging, mapping, matching, processing, and progress. |
| [BACKEND_WEB.md](BACKEND_WEB.md) | Flask startup, blueprints, Jinja, route responses, errors, and templates. |
| [BACKEND_WEB_PERMISSIONS.md](BACKEND_WEB_PERMISSIONS.md) | Route authorization, fetch scope, ETags, collection state, and polling. |
| [AUTHENTICATION.md](AUTHENTICATION.md) | Identity Platform, sessions, account rules, verification, and safe failures. |
| [DATA_MIGRATIONS.md](DATA_MIGRATIONS.md) | Migration catalog, authoring, execution ledger, tests, and recovery. |

## Frontend

| Guide | Covers |
| --- | --- |
| [FRONTEND_OVERVIEW.md](FRONTEND_OVERVIEW.md) | Entry points, view registry, shared services, and source layout. |
| [FRONTEND_VIEWS.md](FRONTEND_VIEWS.md) | View hierarchy, components, widgets, ownership, and routing to focused guides. |
| [FRONTEND_VIEWS_LIFECYCLE.md](FRONTEND_VIEWS_LIFECYCLE.md) | Initialization, suspension, teardown, widget loading, and replacement. |
| [FRONTEND_VIEWS_RECONCILIATION.md](FRONTEND_VIEWS_RECONCILIATION.md) | Poll-driven refresh, edit watching, deferred operations, and notifications. |
| [FRONTEND_ELEMENTS.md](FRONTEND_ELEMENTS.md) | Element registry, field classes, renderers, parsing, and validation. |
| [FRONTEND_FORMS.md](FRONTEND_FORMS.md) | Form lifecycle, submission, uploads, optimistic state, and offline commands. |
| [FRONTEND_COMBOBOX.md](FRONTEND_COMBOBOX.md) | Select, facet, location, search, dropdown, and results controls. |
| [FRONTEND_EDITOR.md](FRONTEND_EDITOR.md) | TipTap editors, Yjs collaboration, toolbar, extensions, and users. |
| [FRONTEND_BUILDER.md](FRONTEND_BUILDER.md) | Form builder panels, drag-and-drop, settings, conditions, and AI generation. |
| [FRONTEND_SERVICE_WORKER.md](FRONTEND_SERVICE_WORKER.md) | Cache strategies, ETags, quotas, protocol, and connectivity. |
| [FRONTEND_NAVIGATION.md](FRONTEND_NAVIGATION.md) | Navigation layout, toggles, tabs, activation, and template patterns. |
| [FRONTEND_TEMPLATES_ATTRIBUTES.md](FRONTEND_TEMPLATES_ATTRIBUTES.md) | Canonical `lp-*` and JavaScript-consumed `data-*` attributes. |

## Synchronization

| Guide | Covers |
| --- | --- |
| [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md) | Polling coordinator, subscriptions, cursors, connectivity, and service boundaries. |
| [SYNC_DOCUMENTS.md](SYNC_DOCUMENTS.md) | Collaborative document generations, revisions, updates, awareness, and recovery. |
| [SYNC_OFFLINE.md](SYNC_OFFLINE.md) | Offline document deltas, mutation queues, conflicts, and form locks. |

## Infrastructure

| Guide | Covers |
| --- | --- |
| [INFRA_CONFIG.md](INFRA_CONFIG.md) | Configuration sources, validation, secrets, browser protocol, and runtime access. |
| [INFRA_SETUP.md](INFRA_SETUP.md) | Installer phases, focused commands, reruns, and setup ownership. |
| [INFRA_SETUP_CLOUD.md](INFRA_SETUP_CLOUD.md) | GCP, Identity Platform, OAuth, domains, email, Redis, and integrations. |
| [INFRA_SETUP_DEVELOPMENT.md](INFRA_SETUP_DEVELOPMENT.md) | Local dependencies, environment, frontend, tests, and emulator assumptions. |
| [INFRA_SETUP_RECOVERY.md](INFRA_SETUP_RECOVERY.md) | Recovery state, validation, repair, and safe reruns. |
| [INFRA_DATA_LIFECYCLE.md](INFRA_DATA_LIFECYCLE.md) | Backup, archive, validation, restore, and destructive-action safeguards. |
| [INFRA_RUNNER.md](INFRA_RUNNER.md) | `run.py` command boundary, project selection, locks, and subprocess behavior. |
| [INFRA_DEPLOYMENT.md](INFRA_DEPLOYMENT.md) | App Engine deployment, release candidates, traffic, and verification. |
| [INFRA_BUILD.md](INFRA_BUILD.md) | Rollup entries, chunks, modes, cache generation, and release builds. |
| [INFRA_BUILD_STYLES.md](INFRA_BUILD_STYLES.md) | CSS ownership, style/icon registries, generated maps, Biome, and Ruff. |
| [INFRA_BUILD_STYLE_REVIEW.md](INFRA_BUILD_STYLE_REVIEW.md) | Reviewing advisory style extraction findings. |

## Testing and review

| Guide | Covers |
| --- | --- |
| [TESTING.md](TESTING.md) | Suites, commands, markers, strict checks, layout, and evidence. |
| [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md) | Test design and placement; read before adding or reshaping tests. |
| [TESTING_SERVER.md](TESTING_SERVER.md) | Managed local server, seed packs, agent login, browser review, and teardown. |
| [TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md) | Cloud Run test job, exact-source candidate, artifacts, evidence, and teardown. |
| [TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md) | Reviewing a test and the source claims it makes. |
| [TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md) | Reviewing source annotations and meaningful coverage. |
| [TESTING_TRACEABILITY_TOOL.md](TESTING_TRACEABILITY_TOOL.md) | Annotation schema, reporter modes, evidence, checks, and manifests. |
| [TESTING_TEMPLATE_CONTRACTS.md](TESTING_TEMPLATE_CONTRACTS.md) | Macro, DOM, selector, and route evidence tracking. |
| [TESTING_BROWSER_REVIEW.md](TESTING_BROWSER_REVIEW.md) | Curated browser-review reports, screenshots, specs, and agent workflow. |

Release-note summaries are stored under [`documentation/releases/`](releases/).

## Common changes

| Change | Read first |
| --- | --- |
| Add an entity or property | [BACKEND_ENTITIES.md](BACKEND_ENTITIES.md), [BACKEND_ENTITIES_PROPERTIES.md](BACKEND_ENTITIES_PROPERTIES.md) |
| Change saves, relations, or deletion | [BACKEND_ENTITIES_MUTATIONS.md](BACKEND_ENTITIES_MUTATIONS.md) |
| Add a route or template fragment | [BACKEND_WEB.md](BACKEND_WEB.md), [BACKEND_WEB_PERMISSIONS.md](BACKEND_WEB_PERMISSIONS.md) |
| Add a view, widget, or field | [FRONTEND_VIEWS.md](FRONTEND_VIEWS.md), [FRONTEND_ELEMENTS.md](FRONTEND_ELEMENTS.md) |
| Change offline or collaborative state | [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md), [SYNC_OFFLINE.md](SYNC_OFFLINE.md) |
| Add background work | [BACKEND_JOBS.md](BACKEND_JOBS.md) |
| Change styles or icons | [INFRA_BUILD_STYLES.md](INFRA_BUILD_STYLES.md) |
| Add a persisted-data transform | [DATA_MIGRATIONS.md](DATA_MIGRATIONS.md) |
| Change setup or deployment | [INFRA_SETUP.md](INFRA_SETUP.md), [INFRA_DEPLOYMENT.md](INFRA_DEPLOYMENT.md) |
| Add or review tests | [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md) |
