# Documentation Overview

All project documentation lives in `documentation/`. This page is the index.

For installation and local setup, see the [README](../README.md). For
contribution expectations, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Architecture and core concepts

Start here to understand how the system works.

| Document | Covers |
|---|---|
| [BACKEND_ENTITIES.md](BACKEND_ENTITIES.md) | Context-aware property system, mixins, entity types, EntityRegistry, indexes, task scheduling. The most important backend doc. |
| [FRONTEND_VIEWS.md](FRONTEND_VIEWS.md) | Core/Entity/EntityIndex view hierarchy, ViewComponent lifecycle, widget contract and loader, reconciliation cycle. The most important frontend doc. |
| [FRONTEND_OVERVIEW.md](FRONTEND_OVERVIEW.md) | Entry points (`main.mjs`, `login.mjs`), view registry, shared utilities, style system (YAML to CSS/Python pipeline). |

## Frontend

Working on browser-side code in `src/`.

| Document | Covers |
|---|---|
| [FRONTEND_ELEMENTS.md](FRONTEND_ELEMENTS.md) | FormElement/BaseForm lifecycle, Renderer, BaseElement, form field types, schema properties, primitives. |
| [FRONTEND_COMBOBOX.md](FRONTEND_COMBOBOX.md) | Combobox system — SelectBox, FacetsBox, LocationBox, SearchBox, Dropdown, Submitter mixin, Results. |
| [FRONTEND_EDITOR.md](FRONTEND_EDITOR.md) | TipTap rich text editor — CollaborativeDocument (Yjs), IndependentDocument, toolbar, custom extensions, UserManager. |
| [FRONTEND_BUILDER.md](FRONTEND_BUILDER.md) | Form builder — drag-and-drop, panels, settings, conditions system, AI schema generation. |
| [FRONTEND_SERVICE_WORKER.md](FRONTEND_SERVICE_WORKER.md) | Service worker caching — static (cache-first), cacheable (network-first + ETag), quota management, push notifications. |
| [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md) | Document collaboration, form edit detection, offline submission replay, and durable deferred-form locks. |
| [FRONTEND_NAVIGATION.md](FRONTEND_NAVIGATION.md) | Template authoring for the nav system — `lp-show`, `lp-component`, `data-widget`, toggle bars, entity tabs. |
| [TEMPLATES_ATTRIBUTES.md](TEMPLATES_ATTRIBUTES.md) | Canonical `lp-*` template attribute reference and the `data-*` attributes frontend code reads from templates. |

## Backend

Working on server-side code in `lagniappe/`.

| Document | Covers |
|---|---|
| [BACKEND_WEB.md](BACKEND_WEB.md) | Flask app initialization, blueprints, Jinja environment, error handling, permission decorators, route patterns, deferred responses, template structure. |
| [BACKEND_TOOLS.md](BACKEND_TOOLS.md) | Database (Datastore + Cloud Storage), Redis cache, Vertex AI, durable deferred jobs, file processing, messaging (FCM), task queue (Cloud Tasks), dates, utilities. |
| [AI_PIPELINE.md](AI_PIPELINE.md) | End-to-end AI context, tool, generation, durable-job, deterministic-application, and browser-reconciliation architecture. |
| [BACKEND_DEFINITIONS.md](BACKEND_DEFINITIONS.md) | Permission enums, filter definitions, entity attributes, ordering, asset types, exceptions. |
| [BACKEND_FILTERS.md](BACKEND_FILTERS.md) | End-to-end filter system — Condition, Filter entity, FilterCache (Redis JSON), FilterExpression (JSONPath), value alignment. |
| [BACKEND_INGRESS.md](BACKEND_INGRESS.md) | CSV import pipeline — stage state machine, column mapping, fuzzy matching, background processing, progress updates. |

## Infrastructure and testing

Build, configuration, installation, and test workflows.

| Document | Covers |
|---|---|
| [INFRA_BUILD.md](INFRA_BUILD.md) | Rollup bundles (login, icons, main), production vs dev, custom plugins, chunk splitting. |
| [INFRA_CONFIG.md](INFRA_CONFIG.md) | Runtime-safe configuration plus the local runner boundary for GCloud switching, deployment, dev/test servers, and upgrades. |
| [INFRA_SETUP.md](INFRA_SETUP.md) | Installation flow (GCP, Firebase, Redis, admin, AI defaults, optional modes), plus upgrades. |
| [MAINTAINER_PULL_REQUESTS.md](MAINTAINER_PULL_REQUESTS.md) | Maintainer review and local integration workflow for source-only contributor PRs and production delivery builds. |
| [DATA_MIGRATIONS.md](DATA_MIGRATIONS.md) | Authoring, testing, releasing, running, auditing, and retiring persisted-data migrations. |
| [TESTING.md](TESTING.md) | Test suites, commands, fixtures, managed test server, traceability tools. |
| [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md) | Practical guide for adding or reviewing tests. |
| [TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md) | Agent workflow for reviewing annotated or bare tests. |
| [TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md) | Agent workflow for reviewing source annotation quality. |
| [TESTING_TRACEABILITY_TOOL.md](TESTING_TRACEABILITY_TOOL.md) | Source/test annotation contract, current-result evidence, and reporter behavior. |
| [TESTING_TEMPLATE_CONTRACTS.md](TESTING_TEMPLATE_CONTRACTS.md) | Jinja macro, DOM contract, and selector-evidence tracking. |
| [REPORTS_BROWSER_REVIEW.md](REPORTS_BROWSER_REVIEW.md) | Browser review workflow for curated UI reports with screenshots. |
| [STYLE_CANDIDATES.md](STYLE_CANDIDATES.md) | Review guide for advisory style-traceability candidate findings. |

## Quick reference

| I want to... | Read | Key files |
|---|---|---|
| Understand how the app initializes | [FRONTEND_OVERVIEW](FRONTEND_OVERVIEW.md) | `src/script/main.mjs`, `src/script/shared/index.mjs` |
| Add a new entity type | [BACKEND_ENTITIES](BACKEND_ENTITIES.md) | `lagniappe/core/entities/`, `lagniappe/core/properties/` |
| Add a property to an entity | [BACKEND_ENTITIES](BACKEND_ENTITIES.md) | `lagniappe/core/properties/`, `lagniappe/core/mixins/` |
| Add a new route | [BACKEND_WEB](BACKEND_WEB.md) | `lagniappe/web/routes/`, `lagniappe/web/auth/auth.py` |
| Add a new widget | [FRONTEND_VIEWS](FRONTEND_VIEWS.md) | `src/script/widgets/loader.mjs`, `src/script/widgets/` |
| Add a form element type | [FRONTEND_ELEMENTS](FRONTEND_ELEMENTS.md) | `src/script/elements/loader.mjs`, `src/script/elements/` |
| Work on the rich text editor | [FRONTEND_EDITOR](FRONTEND_EDITOR.md) | `src/script/elements/editor/` |
| Work on the form builder | [FRONTEND_BUILDER](FRONTEND_BUILDER.md) | `src/script/views/builder/` |
| Work on search/combobox | [FRONTEND_COMBOBOX](FRONTEND_COMBOBOX.md) | `src/script/elements/combobox/` |
| Work on the filter system | [BACKEND_FILTERS](BACKEND_FILTERS.md) | `lagniappe/core/entities/filter.py`, `lagniappe/core/tools/filters/` |
| Work on CSV import | [BACKEND_INGRESS](BACKEND_INGRESS.md) | `lagniappe/core/tools/ingress.py`, `lagniappe/core/properties/file_ingress.py` |
| Work on task scheduling | [BACKEND_ENTITIES](BACKEND_ENTITIES.md) | `lagniappe/core/properties/task_scheduling.py`, `lagniappe/core/tools/dates.py` |
| Work on permissions | [BACKEND_DEFINITIONS](BACKEND_DEFINITIONS.md) | `lagniappe/core/definitions/permissions.py`, `lagniappe/web/auth/auth.py` |
| Change styles or icons | [FRONTEND_OVERVIEW](FRONTEND_OVERVIEW.md), [INFRA_BUILD](INFRA_BUILD.md), [STYLE_CANDIDATES](STYLE_CANDIDATES.md) | `src/style/styles.yaml`, `src/style/icons.yaml` |
| Work on caching/ETags | [FRONTEND_SERVICE_WORKER](FRONTEND_SERVICE_WORKER.md), [BACKEND_TOOLS](BACKEND_TOOLS.md) | `src/script/sw.template.mjs`, `lagniappe/core/tools/cache/` |
| Work on real-time sync/collaboration | [SYNC_ARCHITECTURE](SYNC_ARCHITECTURE.md), [FRONTEND_EDITOR](FRONTEND_EDITOR.md) | `src/script/shared/sync.mjs`, `src/script/elements/editor/collaborative.mjs`, `lagniappe/core/tools/cache/sync.py`, `lagniappe/web/routes/home/sync.py` |
| Work on AI features | [AI_PIPELINE](AI_PIPELINE.md), [BACKEND_TOOLS](BACKEND_TOOLS.md) | `lagniappe/core/tools/ai/`, `lagniappe/core/tools/deferred_jobs.py`, `lagniappe/core/tools/deferred_job_adapters.py` |
| Work on durable background jobs | [AI_PIPELINE](AI_PIPELINE.md), [BACKEND_ENTITIES](BACKEND_ENTITIES.md), [BACKEND_TOOLS](BACKEND_TOOLS.md) | `lagniappe/core/tools/deferred_jobs.py`, `lagniappe/core/tools/task_queue.py`, `lagniappe/web/routes/process/` |
| Author a template | [FRONTEND_NAVIGATION](FRONTEND_NAVIGATION.md), [BACKEND_WEB](BACKEND_WEB.md) | `lagniappe/web/templates/` |
| Build the frontend | [INFRA_BUILD](INFRA_BUILD.md) | `build/rollup.config.mjs`, `build/utility.mjs` |
| Review and integrate a pull request | [MAINTAINER_PULL_REQUESTS](MAINTAINER_PULL_REQUESTS.md) | `.github/workflows/ci.yml`, `.github/CODEOWNERS`, `run.py` |
| Deploy the app | [INFRA_CONFIG](INFRA_CONFIG.md) | `runner/deploy.py` |
| Set up a new instance | [INFRA_SETUP](INFRA_SETUP.md) | `setup.sh`, `setup.cmd`, `installer/` |
| Back up or restore production data | [INFRA_SETUP](INFRA_SETUP.md#disaster-recovery-backups), [INFRA_CONFIG](INFRA_CONFIG.md#data-disaster-recovery-runpy) | `runner/data_recovery.py`, `run.py` |
| Add or run a data migration | [DATA_MIGRATIONS](DATA_MIGRATIONS.md) | `lagniappe/core/tools/database/migrations.py`, `lagniappe/web/routes/home/site.py` |
| Change entity saves, relation writes, or delete cascades | [BACKEND_ENTITIES](BACKEND_ENTITIES.md) | `lagniappe/core/entities/__init__.py`, `lagniappe/core/mixins/related.py`, `lagniappe/core/tools/database/utility.py` |
| Write tests | [TESTING](TESTING.md), [TESTING_WRITING_TESTS](TESTING_WRITING_TESTS.md) | `testing/tests_e2e/`, `testing/tests_js/`, `testing/tests_unit/`, `testing/definitions/` |
| Understand the config system | [INFRA_CONFIG](INFRA_CONFIG.md) | `config/__init__.py`, `config/constants.py` |
