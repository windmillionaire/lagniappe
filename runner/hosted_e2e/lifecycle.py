"""Inspect hosted candidate resources and tear them down after testing."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

from config import APP_DIR

from .app_engine import (
    ANCHOR_VERSION,
    _change_test_bucket_cors,
    _verify_soft_routing_guard,
    _version_url,
)
from .runtime import (
    EXECUTION_RE,
    HostedE2EError,
    SERVICE,
    VERSION_RE,
    _activate,
    _describe,
    _environment,
    _gcloud,
    _infrastructure,
    _load_json,
    _validate_state_infrastructure,
    _write_json,
)


def _execution_is_terminal(execution: dict[str, object]) -> bool:
    """Return True when Cloud Run reports a confirmed terminal execution state."""
    status = execution.get("status")
    status = status if isinstance(status, dict) else {}
    if execution.get("completionTime") or status.get("completionTime"):
        return True
    conditions = status.get("conditions")
    if not isinstance(conditions, list):
        return False
    for condition in conditions:
        if not isinstance(condition, dict) or condition.get("type") != "Completed":
            continue
        cond_status = str(condition.get("status") or "")
        if cond_status in {"True", "False"}:
            return True
    return False


def _active_job_executions(infrastructure, *, job=None):
    job = job or infrastructure.job
    result = _gcloud(
        "run",
        "jobs",
        "executions",
        "list",
        f"--job={job}",
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        "--format=json(name,metadata.name,completionTime,status.completionTime,status.conditions)",
    )
    try:
        executions = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise HostedE2EError(
            "Cloud Run execution listing returned invalid JSON."
        ) from error
    if not isinstance(executions, list):
        raise HostedE2EError("Cloud Run execution listing was not a JSON list.")

    active = []
    for execution in executions:
        if not isinstance(execution, dict):
            raise HostedE2EError("Cloud Run returned an invalid hosted execution.")
        if _execution_is_terminal(execution):
            continue
        name = execution.get("name")
        metadata = execution.get("metadata")
        if not name and isinstance(metadata, dict):
            name = metadata.get("name")
        if isinstance(name, str) and "/" in name:
            name = name.rsplit("/", 1)[-1]
        if (
            not isinstance(name, str)
            or not name.startswith(job + "-")
            or not EXECUTION_RE.fullmatch(name)
        ):
            raise HostedE2EError(
                "Cloud Run returned an unidentified active hosted execution."
            )
        active.append(name)
    return tuple(sorted(set(active)))


def _clear_local_result_artifacts(*, environment="standard"):
    """Remove downloaded result bundles after a successful lifecycle teardown."""
    result_root = _environment(environment).result_root
    if not result_root.exists() and not result_root.is_symlink():
        return False
    if result_root.is_symlink() or result_root.is_file():
        result_root.unlink()
    else:
        shutil.rmtree(result_root)
    print(f"Removed local hosted E2E artifacts: {result_root}")
    return True


def teardown(
    *, force: bool = False, environment: str = "standard"
) -> dict[str, object]:
    """Remove the hosted resources. Each E2E runner owns its test-data cleanup."""
    selected = _environment(environment)
    (APP_DIR / ".hosted-e2e-app.yaml").unlink(missing_ok=True)
    _activate(adc=True)
    infrastructure = _infrastructure()
    state = _load_json(selected.state_path)
    if not state:
        raise HostedE2EError("No hosted E2E lifecycle state exists.")
    _validate_state_infrastructure(
        state,
        infrastructure,
        environment=selected.name,
    )
    version = str(state.get("version") or "")
    base_url = str(state.get("base_url") or "")
    version_pattern = VERSION_RE
    if not version_pattern.fullmatch(version) or version == ANCHOR_VERSION:
        raise HostedE2EError("Refusing to tear down an invalid App Engine version.")
    if base_url != _version_url(infrastructure, version):
        raise HostedE2EError(
            "Refusing to tear down lifecycle state with an unexpected version URL."
        )
    _verify_soft_routing_guard(infrastructure)

    job = _describe(
        [
            "run",
            "jobs",
            "describe",
            selected.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
        ]
    )
    active_executions = (
        _active_job_executions(infrastructure, job=selected.job) if job else ()
    )
    if active_executions and not force:
        raise HostedE2EError(
            "Cloud Run still has active hosted E2E executions: "
            f"{', '.join(active_executions)}. Wait for them or use --force."
        )
    if force:
        for execution in active_executions:
            _gcloud(
                "run",
                "jobs",
                "executions",
                "cancel",
                execution,
                f"--region={infrastructure.region}",
                f"--project={infrastructure.project}",
                "--no-async",
                "--quiet",
            )

    if job is not None:
        _gcloud(
            "run",
            "jobs",
            "delete",
            selected.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
            "--quiet",
        )
    app_version = _describe(
        [
            "app",
            "versions",
            "describe",
            version,
            f"--service={SERVICE}",
            f"--project={infrastructure.project}",
        ]
    )
    if app_version is not None:
        _gcloud(
            "app",
            "versions",
            "delete",
            version,
            f"--service={SERVICE}",
            f"--project={infrastructure.project}",
            "--quiet",
            timeout=1800,
        )
    if base_url.startswith("https://"):
        _change_test_bucket_cors(infrastructure, base_url, present=False)
    state["status"] = "torn-down"
    state["torn_down_at"] = datetime.now(UTC).isoformat()
    _write_json(selected.state_path, state, owner_only=True)
    _clear_local_result_artifacts(environment=selected.name)
    return state


def status(*, environment: str = "standard") -> dict[str, object]:
    """Return local lifecycle state plus live App Engine/job presence."""
    selected = _environment(environment)
    _activate(adc=False)
    infrastructure = _infrastructure()
    state = _load_json(selected.state_path) or {"status": "absent"}
    if state.get("status") != "absent":
        _validate_state_infrastructure(
            state,
            infrastructure,
            environment=selected.name,
        )
    version = state.get("version")
    app_version = None
    version_pattern = VERSION_RE
    if isinstance(version, str) and version_pattern.fullmatch(version):
        app_version = _describe(
            [
                "app",
                "versions",
                "describe",
                version,
                f"--service={SERVICE}",
                f"--project={infrastructure.project}",
            ]
        )
    job = _describe(
        [
            "run",
            "jobs",
            "describe",
            selected.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
        ]
    )
    result = {
        **state,
        "app_version_present": app_version is not None,
        "job_present": job is not None,
    }
    return result
