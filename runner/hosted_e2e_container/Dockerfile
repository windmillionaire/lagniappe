FROM python:3.14-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY requirements.txt requirements-dev.txt requirements-installer.txt ./
RUN python -m venv venv \
    && venv/bin/pip install --no-cache-dir -r requirements-dev.txt \
    && venv/bin/python -m playwright install --with-deps chromium

COPY . .

ENTRYPOINT ["/workspace/venv/bin/python", "-m", "testing.utility.hosted_e2e_job"]
