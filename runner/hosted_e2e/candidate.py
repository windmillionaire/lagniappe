"""Build the runner image and create or resume the hosted test candidate."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from config import APP_DIR, SETTINGS, File, _atomic_write_text
from config.constants import DEFAULT_TEST_PREFIX
from runner import cloud_checkpoints

from .app_engine import (
    _change_test_bucket_cors,
    _hosted_app_descriptor,
    _hosted_app_version_present,
    _stage_app_runtime_files,
    _verify_soft_routing_guard,
    _version_url,
    _wait_hosted_health,
)
from .preflight import (
    _committed_source_tree,
    _require_committed_production_build,
    _run_create_preflight,
    require_clean_source,
)
from .provisioning import _require_current_setup
from .runtime import (
    DEFAULT_BROWSER_WORKERS,
    HostedE2EError,
    SERVICE,
    STATE_ROOT,
    STATE_SCHEMA_VERSION,
    VERSION_RE,
    _activate,
    _deployer_member,
    _describe,
    _environment,
    _gcloud,
    _infrastructure,
    _json_result,
    _load_json,
    _validate_state_infrastructure,
    _write_json,
)


RUNNER_GCLOUDIGNORE_COPY = "root.gcloudignore"
CLOUD_BUILD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$",
    re.IGNORECASE,
)
CLOUD_BUILD_PENDING_STATUSES = {"STATUS_UNKNOWN", "QUEUED", "WORKING", "PENDING"}


def _operator_build_staging_dir(infrastructure):
    """Select the operator's provisioned build bucket after a direct ownership check."""
    name = f"{infrastructure.project}_cloudbuild"
    uri = f"gs://{name}"
    bucket = _describe(
        ["storage", "buckets", "describe", uri, "--raw", f"--project={infrastructure.project}"]
    )
    if (
        not bucket
        or bucket.get("name") != name
        or str(bucket.get("projectNumber") or "") != infrastructure.project_number
    ):
        raise HostedE2EError(
            f"Cloud Build source staging requires {uri} to exist and belong to "
            f"project {infrastructure.project} ({infrastructure.project_number})."
        )
    return f"{uri}/source"


def _build_runner_image(
    infrastructure,
    source,
    source_root,
    *,
    environment="standard",
):
    """Start a resumable image build from the exported committed tree."""
    selected = _environment(environment)
    container_root = Path(source_root) / selected.container_relative_root
    canonical_ignore = Path(source_root) / ".gcloudignore"
    if not canonical_ignore.is_file():
        raise HostedE2EError("The committed source has no canonical .gcloudignore.")
    staged_ignore = container_root / RUNNER_GCLOUDIGNORE_COPY
    if staged_ignore.exists() or staged_ignore.is_symlink():
        raise HostedE2EError(
            "The runner image's staged root .gcloudignore path is not clean."
        )
    shutil.copyfile(canonical_ignore, staged_ignore)
    if (
        staged_ignore.is_symlink()
        or not staged_ignore.is_file()
        or staged_ignore.read_bytes() != canonical_ignore.read_bytes()
    ):
        raise HostedE2EError("The runner image's staged root .gcloudignore is invalid.")
    image = f"{selected.image_base(infrastructure)}:{source}"
    # Old outcomes stay outside the image. Export only placement hints from the
    # exact committed evidence; they cannot supply a result for the new run.
    from runner.e2e_inventory import duration_estimates
    timings = container_root / "durations.json"
    if timings.exists() or timings.is_symlink():
        raise HostedE2EError("The runner image's staged duration hints path is not clean.")
    timings.write_text(json.dumps(duration_estimates(Path(source_root))), encoding="utf-8")
    staging_args = []
    if cloud_checkpoints.ACTIVE.get() is not None:
        staging_dir = _operator_build_staging_dir(infrastructure)
        print(f"Using verified Cloud Build source staging at {staging_dir}.", flush=True)
        staging_args.append(f"--gcs-source-staging-dir={staging_dir}")
    result = _gcloud(
        "builds",
        "submit",
        source_root,
        *staging_args,
        f"--config={container_root / 'cloudbuild.yaml'}",
        f"--ignore-file={container_root / 'gcloudignore'}",
        f"--substitutions=_IMAGE={image}",
        f"--project={infrastructure.project}",
        "--async",
        "--format=json",
        "--quiet",
        timeout=600,
    )
    payload = _json_result(result, "Cloud Build submission")
    cloud_build_id = str(payload.get("id") or "").strip()
    if not CLOUD_BUILD_ID_RE.fullmatch(cloud_build_id):
        raise HostedE2EError("Cloud Build did not return a valid build ID.")
    return image, cloud_build_id


def _wait_runner_image_build(
    infrastructure,
    cloud_build_id,
    *,
    timeout=3600,
    poll_interval=5,
):
    """Wait for one recorded Cloud Build, reporting provider state changes."""
    if not CLOUD_BUILD_ID_RE.fullmatch(str(cloud_build_id or "")):
        raise HostedE2EError("Hosted E2E state contains an invalid Cloud Build ID.")
    deadline = time.monotonic() + timeout
    previous_status = None
    while True:
        payload = _describe(
            [
                "builds",
                "describe",
                cloud_build_id,
                f"--project={infrastructure.project}",
            ]
        )
        if payload is None:
            raise HostedE2EError(
                f"Recorded Cloud Build {cloud_build_id} no longer exists."
            )
        status = str(payload.get("status") or "STATUS_UNKNOWN").upper()
        if status != previous_status:
            print(f"Cloud Build {cloud_build_id}: {status}", flush=True)
            previous_status = status
        if status == "SUCCESS":
            return payload
        if status not in CLOUD_BUILD_PENDING_STATUSES:
            failure_info = payload.get("failureInfo") or {}
            detail = str(
                payload.get("statusDetail") or failure_info.get("detail") or ""
            ).strip()
            suffix = f" ({detail})" if detail else ""
            log_url = str(payload.get("logUrl") or "").strip()
            if log_url:
                suffix += f" Logs: {log_url}"
            raise HostedE2EError(
                f"Cloud Build {cloud_build_id} ended with {status}{suffix}."
            )
        if time.monotonic() >= deadline:
            raise HostedE2EError(
                f"Cloud Build {cloud_build_id} did not finish within {timeout} seconds."
            )
        time.sleep(poll_interval)


def _sync_settings_secret(infrastructure):
    redis_ca_path = None
    if SETTINGS.APP.get("REDIS_TLS"):
        from config.constants import REDIS_CA_CERT_RELATIVE_PATH

        configured_path = str(SETTINGS.APP.get("REDIS_CA_CERT") or "").strip()
        if configured_path != REDIS_CA_CERT_RELATIVE_PATH:
            raise HostedE2EError(
                "Hosted E2E requires the canonical managed Redis CA path."
            )
        redis_ca_path = APP_DIR / REDIS_CA_CERT_RELATIVE_PATH
        if not redis_ca_path.is_file() or not redis_ca_path.stat().st_size:
            raise HostedE2EError("Hosted E2E Redis CA certificate is missing.")
    _gcloud(
        "secrets",
        "versions",
        "add",
        infrastructure.settings_secret,
        f"--data-file={File.APP_SETTINGS_YAML.value}",
        f"--project={infrastructure.project}",
        "--quiet",
    )
    if redis_ca_path is not None:
        _gcloud(
            "secrets",
            "versions",
            "add",
            infrastructure.redis_ca_secret,
            f"--data-file={redis_ca_path}",
            f"--project={infrastructure.project}",
            "--quiet",
        )


def _update_job(infrastructure, state, *, environment="standard"):
    selected = _environment(environment)
    job_service_account = infrastructure.runtime_email
    configured_job = state.get("job", selected.job)
    if configured_job != selected.job:
        raise HostedE2EError(
            "Hosted E2E lifecycle state names the wrong environment job."
        )
    job_environment = {
        "GOOGLE_CLOUD_PROJECT": infrastructure.project,
        "LAGNIAPPE_HOSTED_E2E": "true",
        "LAGNIAPPE_HOSTED_E2E_ROLE": "runner",
        "LAGNIAPPE_HOSTED_E2E_ENVIRONMENT": selected.name,
        "LAGNIAPPE_HOSTED_E2E_BASE_URL": state["base_url"],
        "LAGNIAPPE_HOSTED_E2E_VERSION": state["version"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE": state["source"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": state["source_snapshot"],
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": state["build_id"],
        "LAGNIAPPE_HOSTED_E2E_SERVICE": SERVICE,
        "LAGNIAPPE_HOSTED_E2E_JOB": selected.job,
        "LAGNIAPPE_HOSTED_E2E_ARTIFACT_BUCKET": infrastructure.artifact_bucket,
        "LAGNIAPPE_HOSTED_E2E_WORKERS": str(state.get("experiments_workers", 3)),
    }
    secret_argument = "--clear-secrets"
    job_image = state["image"]
    job_environment.update(
        {
            "FLASK_ENV": "testing",
            "LAGNIAPPE_HOSTED_E2E_PREFIX": DEFAULT_TEST_PREFIX,
            "LAGNIAPPE_HOSTED_E2E_RUNTIME_SERVICE_ACCOUNT_EMAIL": infrastructure.runtime_email,
            "LAGNIAPPE_HOSTED_E2E_CALLER_EMAIL": infrastructure.runtime_email,
        }
    )
    secret_mounts = [
        "/var/run/secrets/lagniappe-settings/lagniappe_settings.yaml="
        f"{infrastructure.settings_secret}:latest"
    ]
    if SETTINGS.APP.get("REDIS_TLS"):
        secret_mounts.append(
            "/var/run/secrets/lagniappe-redis-ca/redis_ca.pem="
            f"{infrastructure.redis_ca_secret}:latest"
        )
    secret_argument = f"--set-secrets={','.join(secret_mounts)}"
    env_argument = ",".join(f"{key}={value}" for key, value in job_environment.items())
    exists = _describe(
        [
            "run",
            "jobs",
            "describe",
            selected.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
        ]
    )
    action = "update" if exists else "create"
    _gcloud(
        "run",
        "jobs",
        action,
        selected.job,
        f"--image={job_image}",
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        f"--service-account={job_service_account}",
        f"--set-env-vars={env_argument}",
        secret_argument,
        "--args=",
        "--tasks=1",
        "--parallelism=1",
        "--max-retries=0",
        "--task-timeout=7200s",
        "--cpu=4" if state.get("experiments_workers", 3) > 3 else "--cpu=2",
        "--memory=8Gi" if state.get("experiments_workers", 3) > 3 else "--memory=4Gi",
        "--quiet",
        timeout=1800,
    )
    _gcloud(
        "run",
        "jobs",
        "add-iam-policy-binding",
        selected.job,
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        f"--member=serviceAccount:{infrastructure.invoker_email}",
        "--role=roles/run.viewer",
        "--quiet",
    )
    _gcloud(
        "run",
        "jobs",
        "add-iam-policy-binding",
        selected.job,
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        f"--member=serviceAccount:{infrastructure.invoker_email}",
        "--role=roles/run.jobsExecutorWithOverrides",
        "--quiet",
    )
    deployer_member = _deployer_member()
    if deployer_member:
        _gcloud(
            "run",
            "jobs",
            "add-iam-policy-binding",
            selected.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
            f"--member={deployer_member}",
            "--role=roles/run.jobsExecutorWithOverrides",
            "--quiet",
        )


def _resumable_create_state(
    previous,
    infrastructure,
    *,
    source,
    source_snapshot,
    build_id,
    environment="standard",
    experiments_workers=DEFAULT_BROWSER_WORKERS,
):
    """Return interrupted exact-source state, or reject an unsafe replacement."""
    selected = _environment(environment)
    if not previous or previous.get("status") == "torn-down":
        return None
    if previous.get("schema_version") != STATE_SCHEMA_VERSION:
        raise HostedE2EError("The previous hosted E2E lifecycle state is invalid.")
    if previous.get("status") not in {"creating", "failed"}:
        raise HostedE2EError(
            "The previous hosted E2E lifecycle has not been torn down; "
            "inspect its status and tear it down first."
        )
    _validate_state_infrastructure(
        previous,
        infrastructure,
        environment=selected.name,
    )
    expected = {
        "source": source,
        "source_snapshot": source_snapshot,
        "build_id": build_id,
    }
    mismatches = [
        name for name, value in expected.items() if previous.get(name) != value
    ]
    if mismatches:
        raise HostedE2EError(
            "The interrupted hosted E2E lifecycle belongs to a different "
            f"committed build ({', '.join(mismatches)}); tear it down first."
        )
    if previous.get("experiments_workers", 3) != experiments_workers:
        raise HostedE2EError("The interrupted lifecycle has a different worker capacity; tear it down first.")
    version = str(previous.get("version") or "")
    version_pattern = VERSION_RE
    if not version_pattern.fullmatch(version):
        raise HostedE2EError("The interrupted lifecycle has an invalid version.")
    if previous.get("base_url") != _version_url(infrastructure, version):
        raise HostedE2EError("The interrupted lifecycle has an invalid version URL.")
    expected_image = f"{selected.image_base(infrastructure)}:{source}"
    if previous.get("image") not in {None, expected_image}:
        raise HostedE2EError("The interrupted lifecycle has an unexpected image.")
    cloud_build_id = previous.get("cloud_build_id")
    if previous.get("image_ready") and cloud_build_id is None:
        raise HostedE2EError(
            "The interrupted lifecycle completed its image without recording "
            "a Cloud Build ID."
        )
    if cloud_build_id is not None and not CLOUD_BUILD_ID_RE.fullmatch(
        str(cloud_build_id)
    ):
        raise HostedE2EError("The interrupted lifecycle has an invalid Cloud Build ID.")
    return dict(previous)


def create(
    *,
    base_ref: str | None = None,
    environment: str = "standard",
    experiments_workers: int = DEFAULT_BROWSER_WORKERS,
) -> dict[str, object]:
    """Deploy one committed production build as a test app and runner."""
    selected = _environment(environment)
    if type(experiments_workers) is not int or not 1 <= experiments_workers <= 6:
        raise HostedE2EError("--workers must be between 1 and 6")
    source = require_clean_source()
    build_id = _require_committed_production_build(source)
    _run_create_preflight(source, base_ref=base_ref)
    from testing.utility.test_evidence import behavior_snapshot

    source_snapshot, _source_paths = behavior_snapshot(APP_DIR)
    _activate(adc=True)
    infrastructure = _infrastructure()
    _require_current_setup(infrastructure)
    _verify_soft_routing_guard(infrastructure)
    state_path = selected.state_path
    previous = _load_json(state_path)
    state = _resumable_create_state(
        previous,
        infrastructure,
        source=source,
        source_snapshot=source_snapshot,
        build_id=build_id,
        environment=selected.name,
        experiments_workers=experiments_workers,
    )
    if state is None:
        version_prefix = "e2e-"
        version = version_prefix + secrets.token_hex(8)
        base_url = _version_url(infrastructure, version)
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "creating",
            "created_at": datetime.now(UTC).isoformat(),
            "project": infrastructure.project,
            "region": infrastructure.region,
            "service": SERVICE,
            "job": selected.job,
            "environment": selected.name,
            "version": version,
            "source": source,
            "source_snapshot": source_snapshot,
            "build_id": build_id,
            "base_url": base_url,
            "artifact_bucket": infrastructure.artifact_bucket,
            "image": f"{selected.image_base(infrastructure)}:{source}",
            "experiments_workers": experiments_workers,
        }
    else:
        state["status"] = "creating"
        state["resumed_at"] = datetime.now(UTC).isoformat()
        state.setdefault("image", f"{selected.image_base(infrastructure)}:{source}")
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(state_path, state, owner_only=True)

    try:
        with _committed_source_tree(source) as source_root:
            if not state.get("image_ready"):
                cloud_build_id = state.get("cloud_build_id")
                if cloud_build_id is None:
                    image, cloud_build_id = _build_runner_image(
                        infrastructure,
                        source,
                        source_root,
                    )
                    state["image"] = image
                    state["cloud_build_id"] = cloud_build_id
                    _write_json(state_path, state, owner_only=True)
                _wait_runner_image_build(
                    infrastructure,
                    cloud_build_id,
                )
                state["image_ready"] = True
                _write_json(state_path, state, owner_only=True)

            if not state.get("settings_synced"):
                _sync_settings_secret(infrastructure)
                state["settings_synced"] = True
                _write_json(state_path, state, owner_only=True)

            _change_test_bucket_cors(
                infrastructure,
                state["base_url"],
                present=True,
            )
            state["cors_added"] = True
            _write_json(state_path, state, owner_only=True)

            if _hosted_app_version_present(infrastructure, state):
                state["app_deployed"] = True
                _write_json(state_path, state, owner_only=True)
            else:
                _stage_app_runtime_files(source_root)
                descriptor = _hosted_app_descriptor(
                    infrastructure,
                    version=state["version"],
                    source=source,
                    source_snapshot=source_snapshot,
                    build_id=build_id,
                    base_url=state["base_url"],
                    session_key=secrets.token_urlsafe(48),
                    experiments_workers=experiments_workers,
                )
                descriptor_path = source_root / ".hosted-e2e-app.yaml"
                _atomic_write_text(
                    descriptor_path,
                    yaml.safe_dump(descriptor, sort_keys=False),
                    owner_only=True,
                )
                try:
                    _gcloud(
                        "app",
                        "deploy",
                        descriptor_path,
                        f"--version={state['version']}",
                        "--no-promote",
                        "--quiet",
                        f"--project={infrastructure.project}",
                        timeout=2400,
                        capture_output=False,
                    )
                    state["app_deployed"] = True
                    _write_json(state_path, state, owner_only=True)
                finally:
                    descriptor_path.unlink(missing_ok=True)

        _wait_hosted_health(state)
        _update_job(infrastructure, state)
        state["job_updated"] = True
        state["status"] = "ready"
        _write_json(state_path, state, owner_only=True)
        return state
    except Exception:
        state["status"] = "failed"
        _write_json(state_path, state, owner_only=True)
        raise
