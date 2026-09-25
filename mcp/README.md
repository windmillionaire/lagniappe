# Lagniappe remote MCP service

This directory owns the Cloud Run MCP service: its HTTP server, API adapter,
file transfers, pinned dependencies, Dockerfile and Cloud Build definition.
`src/lagniappe_mcp/server.py` is the entry point; `presentation.py` handles MCP
result serialization. The service is independent of the Flask application and
uses its own Python 3.14 / uv environment and lockfile.

Users connect to their site's Cloud Run `/mcp` URL and authorize through the
Lagniappe website. Terminal uploads use the remote preparation and finalization
tools plus an ordinary HTTP client. No local MCP package or helper is required.
The direct REST API and its downloadable skill remain available separately.

Questions and task retrieval use `answer_question` guidance and plan-free read
tools. `start_plan` creates a durable Plan for requested workspace changes or
an explicitly saved answer. One compact contract advertises all allowed actions;
load selected schemas with get_plan_contract or get_guidelines. Reuse the same
plan for mixed requests and revisions until execution begins. Mutations require
browser approval. Files and instructions are individually optional, but publishing
requires at least one. Classify uploads with file_usage; only organize files need
summary and attachment actions, while evidence files support answers directly.
The app and MCP service use contract version 10 with no previous starter aliases.

The API owns proposal and file-usage validation for both REST and MCP clients.
Before submitting, the adapter reads the summary contract to verify the current
submission target, then forwards the candidate and its supplied contract version
unchanged. API validation codes and field paths survive the adapter's bounded,
credential-safe error projection. `get_plan_contract` defaults to `summary`,
matching REST; request selected actions or `view="full"` when schemas are needed.
The adapter still validates tool envelopes, URLs, transport extensions and schemas
it exposes. Its bounded remote-schema subset supports `format: date`; other
format names remain rejected on schema reads. A schema for an unused action does
not gate proposal submission.

Tests live in `testing/tests_unit/test_033*.py`; live API and OAuth workflows
live in `testing/tests_e2e/013_agent_api/`. The normal repository runner selects
the isolated service environment automatically for the MCP unit tests:

```bash
venv/bin/python run.py test unit
```

Use a test's full path or nodeid for focused runs. The tests are not shipped to
Cloud Run and the production image does not contain pytest or the build backend.
The internal Python build metadata is for reproducible container installation;
there is no public wheel release, local server command or client installer.

Select external AI/MCP in normal setup or `./setup.sh ai`. Normal installation,
update and deployment prepare its cloud resources, build only changed service
inputs, publish App Engine, then activate the matching Cloud Run revision.
`./setup.sh mcp` retries or reconciles that lifecycle. `MCP_VERSION` records the
desired source fingerprint; actual Cloud Run readiness determines success.
The Cloud Build context uses `mcp/gcloudignore` to exclude app settings and tests.

See [API workflows](../documentation/AI_EXTERNAL_API.md),
[deployment](../documentation/INFRA_DEPLOYMENT.md#remote-mcp-service), and
[the developer environment](../documentation/INFRA_RUNNER.md#mcp-service-environment).
