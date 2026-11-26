FROM node:26.13.1-bookworm-slim@sha256:0042e17d232a87a2cd485be1da7900fca4d10a4ad11b29e9285da1d2e54798c9 AS node-runtime

FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv-runtime

FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS mcp-builder

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /workspace

COPY --from=uv-runtime /uv /usr/local/bin/uv
COPY mcp/pyproject.toml mcp/uv.lock mcp/README.md mcp/
RUN uv sync --project mcp --locked --group test --no-install-project --no-editable
COPY mcp/src mcp/src
RUN uv sync --project mcp --locked --group test --no-editable --no-build-isolation --offline

FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git procps libatomic1 \
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
COPY runner/hosted_e2e_container/durations.json /opt/lagniappe-e2e-durations.json
RUN rm runner/hosted_e2e_container/durations.json
ENV LAGNIAPPE_E2E_DURATIONS=/opt/lagniappe-e2e-durations.json
COPY --from=mcp-builder /workspace/mcp/.venv /workspace/mcp/.venv
COPY runner/hosted_e2e_container/root.gcloudignore .gcloudignore

# Cloud Run mounts each secret as a directory. Keep those directories separate
# and expose the application's fixed config paths without embedding secret data.
RUN mkdir -p config/files \
    && ln -s /var/run/secrets/lagniappe-settings/lagniappe_settings.yaml config/files/lagniappe_settings.yaml \
    && ln -s /var/run/secrets/lagniappe-redis-ca/redis_ca.pem config/files/redis_ca.pem

ENTRYPOINT ["/workspace/venv/bin/python", "-m", "testing.utility.hosted_e2e_job"]
