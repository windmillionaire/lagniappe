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
tools. `start_ask` is reserved for a user-requested saved answer. Create/Organize
retain browser approval; their compact contracts advertise all allowed actions
and load selected schemas through `get_plan_contract`. `get_plan` returns
permission-rechecked execution receipts, and submission can revise the current
title/brief while retaining the original. See the API guide for exact shapes.

Create is for new content; Organize handles existing-record updates as well as
uploaded files. Remote updates need no file, unlike UI Organize. The Organize
starter returns a compact contract, with selected action schemas fetched on
demand. `complete_task` is a reviewed plan action, not a top-level MCP tool.
When files are uploaded, every file still needs inspection, summary and placement.

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
