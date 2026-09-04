FROM node:24-bookworm-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS node-runtime

FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv-runtime

FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS mcp-builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /workspace

COPY --from=uv-runtime /uv /usr/local/bin/uv
COPY clients/lagniappe_mcp/pyproject.toml clients/lagniappe_mcp/uv.lock clients/lagniappe_mcp/README.md clients/lagniappe_mcp/
RUN uv sync --project clients/lagniappe_mcp --locked --group test --no-install-project --no-editable
COPY clients/lagniappe_mcp/src clients/lagniappe_mcp/src
RUN uv sync --project clients/lagniappe_mcp --locked --group test --no-editable --no-build-isolation --offline

FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git procps \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

COPY requirements.txt requirements-dev.txt requirements-installer.txt ./
RUN python -m venv venv \
    && venv/bin/pip install --no-cache-dir -r requirements-dev.txt \
    && venv/bin/python -m playwright install --with-deps chromium

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
COPY --from=mcp-builder /workspace/clients/lagniappe_mcp/.venv /workspace/clients/lagniappe_mcp/.venv
COPY runner/hosted_e2e_container/root.gcloudignore .gcloudignore

ENTRYPOINT ["/workspace/venv/bin/python", "-m", "testing.utility.hosted_e2e_job"]
