FROM node:24-bookworm-slim AS node-runtime

FROM python:3.14-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
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

ENTRYPOINT ["/workspace/venv/bin/python", "-m", "testing.utility.hosted_e2e_job"]
