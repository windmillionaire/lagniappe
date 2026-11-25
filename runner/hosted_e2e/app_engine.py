"""App Engine candidate configuration, routing checks, and test bucket CORS."""

from __future__ import annotations

import copy
import secrets
import shutil
from pathlib import Path

import yaml

from config import APP_DIR, SETTINGS, _atomic_write_text
from config.constants import APP_HANDLERS, DEFAULT_TEST_PREFIX
from config.hosted_e2e import hosted_test_service_cors_origin
from config.storage import (
    BUCKET_CORS_HEADERS,
    BUCKET_CORS_MAX_AGE_SECONDS,
    BUCKET_CORS_METHODS,
    has_browser_cors_origin,
    storage_bucket_names,
)

from .runtime import DEFAULT_BROWSER_WORKERS, HostedE2EError, SERVICE, _describe, _gcloud


ANCHOR_VERSION = "e2e-anchor"
ANCHOR_REVISION = "2"
ANCHOR_ROOT = APP_DIR / "runner/hosted_e2e_anchor"
APP_SETTINGS_RELATIVE_PATH = Path("config/files/lagniappe_settings.yaml")
REDIS_CA_RELATIVE_PATH = Path("config/files/redis_ca.pem")


def _test_bucket_names():
    settings = dict(SETTINGS.APP)
    settings["PREFIX"] = DEFAULT_TEST_PREFIX
    return tuple(storage_bucket_names(settings).values())


def _ensure_anchor(infrastructure):
    existing = _describe(
        [
            "app",
            "versions",
            "describe",
            ANCHOR_VERSION,
            f"--service={SERVICE}",
            f"--project={infrastructure.project}",
        ]
    )
    existing_variables = (existing or {}).get("envVariables") or {}
    if existing is None:
        _verify_soft_routing_guard(infrastructure)
    if existing_variables.get("HOSTED_E2E_ANCHOR_REVISION") != ANCHOR_REVISION:
        descriptor = {
            "runtime": "python314",
            "service": SERVICE,
            "service_account": infrastructure.runtime_email,
            "entrypoint": "gunicorn -b :$PORT main:app",
            "env_variables": {"HOSTED_E2E_ANCHOR_REVISION": ANCHOR_REVISION},
            "instance_class": "F1",
            "automatic_scaling": {"max_instances": 1, "min_idle_instances": 0},
            "handlers": [{"url": "/.*", "script": "auto", "secure": "always"}],
        }
        descriptor_path = ANCHOR_ROOT / ".hosted-e2e-anchor.yaml"
        _atomic_write_text(descriptor_path, yaml.safe_dump(descriptor, sort_keys=False))
        try:
            _gcloud(
                "app",
                "deploy",
                descriptor_path,
                f"--version={ANCHOR_VERSION}",
                "--no-promote",
                "--quiet",
                timeout=1800,
                capture_output=False,
            )
        finally:
            descriptor_path.unlink(missing_ok=True)
    _gcloud(
        "app",
        "services",
        "set-traffic",
        SERVICE,
        f"--splits={ANCHOR_VERSION}=1",
        "--migrate",
        "--quiet",
    )
    _verify_soft_routing_guard(infrastructure)


def _app_default_hostname(infrastructure):
    app = _describe(["app", "describe", f"--project={infrastructure.project}"])
    hostname = str((app or {}).get("defaultHostname") or "").strip()
    if not hostname:
        raise HostedE2EError("Could not determine the App Engine hostname.")
    return hostname


def _version_url(infrastructure, version):
    hostname = f"{version}-dot-{SERVICE}-dot-{_app_default_hostname(infrastructure)}"
    if len(hostname.split(".", 1)[0]) > 63:
        raise HostedE2EError(
            "Hosted E2E version hostname exceeds the App Engine DNS limit."
        )
    return f"https://{hostname}"


def _verify_soft_routing_guard(infrastructure):
    """Prove deleted E2E hostnames cannot soft-route into production."""
    import requests

    probe_version = "e2e-" + secrets.token_hex(8)
    try:
        response = requests.get(
            f"{_version_url(infrastructure, probe_version)}/users/login",
            allow_redirects=False,
            timeout=30,
        )
    except requests.RequestException as error:
        raise HostedE2EError(
            "Could not verify the production hosted-E2E soft-routing guard."
        ) from error
    if (
        response.status_code != 404
        or response.headers.get("X-Lagniappe-Hosted-E2E-Guard") != "active"
    ):
        raise HostedE2EError(
            "Neither the production App Engine service nor the E2E anchor "
            "exposes the hosted-E2E soft-routing guard. Deploy the current "
            "application normally, then rerun hosted-E2E setup."
        )


def _hosted_app_descriptor(
    infrastructure,
    *,
    version,
    source,
    source_snapshot,
    build_id,
    base_url,
    session_key,
    experiments_workers=DEFAULT_BROWSER_WORKERS,
):
    """Return a test descriptor with production-equivalent static delivery."""
    handlers = copy.deepcopy(APP_HANDLERS)
    if not handlers or not str(handlers[-1].get("static_files") or "").endswith(
        "/404.html"
    ):
        raise HostedE2EError(
            "The canonical App Engine descriptor has no terminal 404 handler."
        )
    # Production's static catch-all returns its 404 document with HTTP 200.
    # Hosted E2E must send unknown routes through Flask so the suite verifies
    # the application's actual error handler and status contract.
    handlers[-1] = {
        "url": "/(.*)$",
        "script": "auto",
        "secure": "always",
        "redirect_http_response_code": 301,
    }
    environment = {
        "FLASK_ENV": "testing",
        "LAGNIAPPE_HOSTED_E2E": "true",
        "LAGNIAPPE_HOSTED_E2E_ROLE": "server",
        "LAGNIAPPE_HOSTED_E2E_BASE_URL": base_url,
        "LAGNIAPPE_HOSTED_E2E_PREFIX": DEFAULT_TEST_PREFIX,
        "LAGNIAPPE_HOSTED_E2E_RUNTIME_SERVICE_ACCOUNT_EMAIL": infrastructure.runtime_email,
        "LAGNIAPPE_HOSTED_E2E_VERSION": version,
        "LAGNIAPPE_HOSTED_E2E_SOURCE": source,
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": source_snapshot,
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": build_id,
        "LAGNIAPPE_HOSTED_E2E_SERVICE": SERVICE,
        "LAGNIAPPE_HOSTED_E2E_CALLER_EMAIL": infrastructure.runtime_email,
        "LAGNIAPPE_HOSTED_E2E_SESSION_KEY": session_key,
        "LAGNIAPPE_HOSTED_E2E_WORKERS": str(experiments_workers),
    }
    return {
        "runtime": "python314",
        "service": SERVICE,
        "service_account": infrastructure.runtime_email,
        "entrypoint": f"gunicorn -t 3600 -w {6 if experiments_workers > 3 else 3} -b :$PORT main:app",
        "instance_class": "B4" if experiments_workers > 3 else "B2",
        "basic_scaling": {"max_instances": 1, "idle_timeout": "15m"},
        # Static build artifacts contain no application or test data. Keep them
        # on App Engine's native static path so isolated browser contexts do not
        # serialize thousands of chunk requests through the Gunicorn workers.
        # Every registered application/testing route remains a dynamic handler
        # and is therefore protected by the hosted request gate in Flask.
        "handlers": handlers,
        "env_variables": environment,
    }


def _change_test_bucket_cors(infrastructure, origin, *, present):
    from google.cloud import storage

    client = storage.Client(project=infrastructure.project)
    service_origin = hosted_test_service_cors_origin(
        infrastructure.project, origin, from_candidate=True
    )
    for bucket_name in _test_bucket_names():
        bucket = client.get_bucket(bucket_name)
        rules = copy.deepcopy(list(bucket.cors or []))
        if present and has_browser_cors_origin(rules, service_origin):
            continue
        if present and not rules:
            rules = [
                {
                    "origin": [],
                    "method": BUCKET_CORS_METHODS,
                    "responseHeader": BUCKET_CORS_HEADERS,
                    "maxAgeSeconds": BUCKET_CORS_MAX_AGE_SECONDS,
                }
            ]
        changed = False
        updated = []
        for rule in rules:
            origins = list(rule.get("origin") or [])
            if present and origin not in origins:
                rule["origin"] = sorted({*origins, origin})
                changed = True
            elif not present and origin in origins:
                remaining = [value for value in origins if value != origin]
                changed = True
                if not remaining:
                    continue
                rule["origin"] = remaining
            updated.append(rule)
        if changed:
            bucket.cors = updated
            bucket.patch(if_metageneration_match=bucket.metageneration)


def _stage_app_runtime_files(source_root, *, repo_root=APP_DIR):
    source_root = Path(source_root)
    repo_root = Path(repo_root)
    runtime_paths = [APP_SETTINGS_RELATIVE_PATH]
    if SETTINGS.APP.get("REDIS_TLS"):
        from config.constants import REDIS_CA_CERT_RELATIVE_PATH

        if Path(REDIS_CA_CERT_RELATIVE_PATH) != REDIS_CA_RELATIVE_PATH:
            raise HostedE2EError(
                "Hosted E2E requires the canonical managed Redis CA path."
            )
        runtime_paths.append(REDIS_CA_RELATIVE_PATH)

    for relative_path in runtime_paths:
        source_path = repo_root / relative_path
        if not source_path.is_file() or not source_path.stat().st_size:
            raise HostedE2EError(f"Hosted E2E runtime file is missing: {relative_path}")
        destination = source_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _wait_hosted_health(state, *, attempts=60):
    import time

    import requests

    expected = {
        "ready": True,
        "service": state["service"],
        "version": state["version"],
        "source": state["source"],
        "source_snapshot": state["source_snapshot"],
        "build_id": state["build_id"],
    }
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(
                f"{state['base_url']}/testing/health",
                timeout=15,
            )
            if response.status_code == 200 and response.json() == expected:
                return
            last_error = HostedE2EError(
                f"health returned HTTP {response.status_code}: {response.text[:200]}"
            )
        except Exception as error:
            last_error = error
        if attempt < attempts - 1:
            time.sleep(2)
    raise HostedE2EError(f"Hosted E2E version did not become ready: {last_error}")


def _hosted_app_version_present(infrastructure, state):
    """Report whether the state-owned version already has exact metadata."""
    existing = _describe(
        [
            "app",
            "versions",
            "describe",
            state["version"],
            f"--service={SERVICE}",
            f"--project={infrastructure.project}",
        ]
    )
    if existing is None:
        return False
    variables = existing.get("envVariables") or {}
    expected = {
        "LAGNIAPPE_HOSTED_E2E_VERSION": state["version"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE": state["source"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": state["source_snapshot"],
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": state["build_id"],
    }
    if "experiments_workers" in state:
        expected["LAGNIAPPE_HOSTED_E2E_WORKERS"] = str(state["experiments_workers"])
    mismatches = [
        name for name, value in expected.items() if variables.get(name) != value
    ]
    if mismatches:
        raise HostedE2EError(
            "The state-owned App Engine version has unexpected deployment "
            f"metadata ({', '.join(mismatches)})."
        )
    return True
