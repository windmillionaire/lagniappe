FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv-runtime

FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS builder
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /workspace
COPY --from=uv-runtime /uv /usr/local/bin/uv
COPY clients/lagniappe_mcp/pyproject.toml clients/lagniappe_mcp/uv.lock clients/lagniappe_mcp/README.md clients/lagniappe_mcp/
RUN uv sync --project clients/lagniappe_mcp --locked --group test --no-install-project --no-editable
COPY clients/lagniappe_mcp/src clients/lagniappe_mcp/src
RUN uv sync --project clients/lagniappe_mcp --locked --group test --no-editable --no-build-isolation --offline

FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /workspace/clients/lagniappe_mcp/.venv /workspace/clients/lagniappe_mcp/.venv
COPY clients/lagniappe_mcp_remote /app/lagniappe_mcp_remote
USER 65532:65532
ENTRYPOINT ["/workspace/clients/lagniappe_mcp/.venv/bin/python", "-m", "lagniappe_mcp_remote.hosted"]
