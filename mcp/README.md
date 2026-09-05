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

Build from the repository root with `mcp/cloudbuild.yaml` and its explicit
`mcp/gcloudignore` upload allowlist. That build pushes an image; deploying a Cloud
Run revision remains a separate manual step from deploying App Engine.

See [API workflows](../documentation/AI_EXTERNAL_API.md),
[deployment](../documentation/INFRA_DEPLOYMENT.md#remote-mcp-pilot), and
[the developer environment](../documentation/INFRA_RUNNER.md#mcp-service-environment).
