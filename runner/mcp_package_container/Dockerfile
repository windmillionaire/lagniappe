# syntax=docker/dockerfile:1.6

FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /workspace

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git procps \
    && rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460 \
    https://github.com/astral-sh/uv/releases/download/0.12.9/uv-x86_64-unknown-linux-gnu.tar.gz /tmp/uv.tar.gz
RUN tar --extract --gzip --file /tmp/uv.tar.gz --directory /tmp \
    && install -m 0755 /tmp/uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv \
    && rm -rf /tmp/uv.tar.gz /tmp/uv-x86_64-unknown-linux-gnu

ADD --checksum=sha256:31d517b7afebf55d3b597d613c735389068a973a54712a50641845cf2cb2bb1d \
    https://github.com/pypa/pipx/releases/download/1.17.2/pipx.pyz /opt/pipx/pipx.pyz
RUN chmod 0755 /opt/pipx/pipx.pyz \
    && ln -s /opt/pipx/pipx.pyz /usr/local/bin/pipx

ADD --checksum=sha256:35a82c153d83959de09c2cb84ac70ba69d05788aeeb08d4a95ca68e39f86680e \
    https://github.com/openai/codex/releases/download/rust-v0.153.0/codex-x86_64-unknown-linux-musl.tar.gz /tmp/codex.tar.gz
RUN tar --extract --gzip --file /tmp/codex.tar.gz --directory /tmp \
    && install -m 0755 /tmp/codex-x86_64-unknown-linux-musl /usr/local/bin/codex \
    && rm -f /tmp/codex.tar.gz /tmp/codex-x86_64-unknown-linux-musl \
    && uv --version \
    && pipx --version \
    && codex --version

COPY clients/lagniappe_mcp/pyproject.toml clients/lagniappe_mcp/uv.lock clients/lagniappe_mcp/README.md clients/lagniappe_mcp/
RUN uv sync --project clients/lagniappe_mcp --locked --group test --no-install-project --no-editable
COPY clients/lagniappe_mcp/src clients/lagniappe_mcp/src
RUN uv sync --project clients/lagniappe_mcp --locked --group test --no-editable --no-build-isolation --offline

COPY requirements.txt requirements-dev.txt requirements-installer.txt ./
RUN python -m venv venv \
    && venv/bin/pip install --no-cache-dir -r requirements-dev.txt

COPY . .
COPY runner/mcp_package_container/root.gcloudignore .gcloudignore

ENTRYPOINT ["/workspace/venv/bin/python", "-m", "testing.utility.hosted_e2e_job"]
