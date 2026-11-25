"""Hosted E2E environment, Google Cloud commands, and checkpointed state."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from config import APP_DIR, SETTINGS, _atomic_write_text
from runner import cloud_checkpoints
from runner.context import GCLOUD_CLI
from runner.gcloud import activate_repository_gcloud
from runner.process import run_command


STATE_SCHEMA_VERSION = 1
SERVICE = "e2e"
JOB = "lagniappe-e2e"
RUNTIME_ACCOUNT = "lagniappe-e2e-runtime"
INVOKER_ACCOUNT = "lagniappe-e2e-invoker"
ARTIFACT_REPOSITORY = "lagniappe-e2e"
SETTINGS_SECRET = "lagniappe-e2e-settings"
REDIS_CA_SECRET = "lagniappe-e2e-redis-ca"
WORKLOAD_POOL = "lagniappe-e2e"
WORKLOAD_PROVIDER = "github"
STATE_ROOT = APP_DIR / "reports/hosted-e2e"
STATE_PATH = STATE_ROOT / "state.json"
SETUP_PATH = STATE_ROOT / "setup.json"
CONTAINER_RELATIVE_ROOT = Path("runner/hosted_e2e_container")
CONTAINER_ROOT = APP_DIR / CONTAINER_RELATIVE_ROOT
VERSION_RE = re.compile(r"^e2e-[0-9a-f]{16}$")
EXECUTION_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
HOSTED_E2E_ENVIRONMENTS = ("standard",)
DEFAULT_BROWSER_WORKERS = 6
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HostedE2EError(RuntimeError):
    """Raised when a hosted-E2E lifecycle invariant is not satisfied."""


@dataclass(frozen=True)
class HostedE2EEnvironment:
    """Closed lifecycle identity for one hosted test environment."""

    name: str
    job: str
    image_repository: str
    state_filename: str
    result_directory: str
    container_relative_root: Path

    def image_base(self, infrastructure: HostedE2EInfrastructure) -> str:
        registry = infrastructure.image_base.rsplit("/", 1)[0]
        return f"{registry}/{self.image_repository}"

    @property
    def state_path(self) -> Path:
        return STATE_PATH
        return STATE_ROOT / self.state_filename

    @property
    def result_root(self) -> Path:
        return STATE_ROOT / self.result_directory


def _environment(environment="standard") -> HostedE2EEnvironment:
    """Resolve the public environment enum without accepting aliases."""
    definitions = {
        "standard": HostedE2EEnvironment(
            name="standard",
            job=JOB,
            image_repository="runner",
            state_filename=STATE_PATH.name,
            result_directory="results",
            container_relative_root=CONTAINER_RELATIVE_ROOT,
        ),
    }
    try:
        return definitions[environment]
    except (KeyError, TypeError) as error:
        allowed = "|".join(HOSTED_E2E_ENVIRONMENTS)
        raise HostedE2EError(
            f"Hosted E2E environment must be one of {allowed}."
        ) from error


@dataclass(frozen=True)
class HostedE2EInfrastructure:
    project: str
    project_number: str
    region: str
    service: str
    job: str
    runtime_email: str
    invoker_email: str
    artifact_repository: str
    artifact_bucket: str
    settings_secret: str
    redis_ca_secret: str
    workload_pool: str
    workload_provider: str

    @property
    def image_base(self) -> str:
        return (
            f"{self.region}-docker.pkg.dev/{self.project}/"
            f"{self.artifact_repository}/runner"
        )

    @property
    def provider_resource(self) -> str:
        return (
            f"projects/{self.project_number}/locations/global/"
            f"workloadIdentityPools/{self.workload_pool}/providers/"
            f"{self.workload_provider}"
        )


def _gcloud(*arguments, check=True, timeout=600, capture_output=True):
    if not GCLOUD_CLI:
        raise HostedE2EError("The gcloud CLI is required for hosted E2E commands.")
    return run_command(
        [GCLOUD_CLI or "gcloud", *map(str, arguments)],
        check=check,
        timeout=timeout,
        capture_output=capture_output,
    )


def _json_result(result, label):
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise HostedE2EError(f"{label} returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise HostedE2EError(f"{label} did not return a JSON object.")
    return value


def _describe(arguments):
    result = _gcloud(*arguments, "--format=json", check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        normalized = detail.casefold()
        if any(
            marker in normalized
            for marker in ("not_found", "not found", "does not exist", "cannot find")
        ):
            return None
        raise HostedE2EError(detail or "gcloud describe failed.")
    return _json_result(result, "gcloud describe")


def _project_number(project):
    result = _gcloud(
        "projects",
        "describe",
        project,
        "--format=value(projectNumber)",
    )
    value = result.stdout.strip()
    if not value.isdigit():
        raise HostedE2EError("Google Cloud did not return a project number.")
    return value


def _infrastructure(*, project_number=None):
    project = str(SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    configured_project = str(
        (SETTINGS.GCLOUD_CONFIG or {}).get("PROJECT") or ""
    ).strip()
    if not project or configured_project != project:
        raise HostedE2EError(
            "Hosted E2E requires matching app and repository gcloud projects."
        )
    region = str(SETTINGS.APP.get("RESOURCE_REGION") or "").strip()
    if not region:
        raise HostedE2EError("Hosted E2E requires RESOURCE_REGION.")
    digest = hashlib.sha256(
        str(SETTINGS.APP.get("GIBBERISH") or "").encode()
    ).hexdigest()
    if not SETTINGS.APP.get("GIBBERISH"):
        raise HostedE2EError("Hosted E2E requires the configured bucket seed.")
    project_number = str(project_number or _project_number(project))
    return HostedE2EInfrastructure(
        project=project,
        project_number=project_number,
        region=region,
        service=SERVICE,
        job=JOB,
        runtime_email=f"{RUNTIME_ACCOUNT}@{project}.iam.gserviceaccount.com",
        invoker_email=f"{INVOKER_ACCOUNT}@{project}.iam.gserviceaccount.com",
        artifact_repository=ARTIFACT_REPOSITORY,
        artifact_bucket=f"lagniappe-e2e-artifacts-{digest[:20]}",
        settings_secret=SETTINGS_SECRET,
        redis_ca_secret=REDIS_CA_SECRET,
        workload_pool=WORKLOAD_POOL,
        workload_provider=WORKLOAD_PROVIDER,
    )


def _activate(*, adc=False):
    try:
        activate_repository_gcloud(
            ensure_adc=adc,
            ensure_cli_token=True,
            allow_cli_login=False,
            allow_runtime_adc=adc,
            allow_adc_login=False,
        )
    except RuntimeError as error:
        raise HostedE2EError(str(error)) from error


def _deployer_member():
    deployer = str((SETTINGS.GCLOUD_CONFIG or {}).get("ACCOUNT") or "").strip()
    if not deployer:
        return None
    member_kind = (
        "serviceAccount" if deployer.endswith("gserviceaccount.com") else "user"
    )
    return f"{member_kind}:{deployer}"


def _write_json(path: Path, payload: dict, *, owner_only=False):
    checkpoint = cloud_checkpoints.ACTIVE.get()
    if checkpoint and path in checkpoint.paths:
        return checkpoint.write(path, payload)
    return _atomic_write_text(
        path,
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n",
        owner_only=owner_only,
    )


def _load_json(path: Path):
    checkpoint = cloud_checkpoints.ACTIVE.get()
    if checkpoint and path in checkpoint.paths:
        return copy.deepcopy(checkpoint.doc[checkpoint.paths[path]])
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _validate_state_infrastructure(state, infrastructure, *, environment=None):
    selected = _environment(environment) if environment is not None else None
    expected = {
        "project": infrastructure.project,
        "region": infrastructure.region,
        "service": SERVICE,
        "job": selected.job if selected is not None else infrastructure.job,
        "artifact_bucket": infrastructure.artifact_bucket,
    }
    if selected is not None and (not 'environment' not in state):
        expected["environment"] = selected.name
    mismatches = [name for name, value in expected.items() if state.get(name) != value]
    if mismatches:
        raise HostedE2EError(
            "Hosted E2E lifecycle state belongs to different infrastructure "
            f"({', '.join(mismatches)}); restore that configuration before "
            "operating on it."
        )


def _state_ready(infrastructure, *, environment="standard"):
    selected = _environment(environment)
    state = _load_json(selected.state_path)
    if not state or state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise HostedE2EError("No hosted E2E lifecycle state exists.")
    if state.get("status") != "ready":
        raise HostedE2EError(
            f"Hosted E2E state is {state.get('status', 'invalid')!r}, not ready."
        )
    if not re.fullmatch(r"b[0-9a-f]{7}", str(state.get("build_id") or "")):
        raise HostedE2EError("Hosted E2E lifecycle state contains an invalid build ID.")
    version_pattern = VERSION_RE
    if not version_pattern.fullmatch(str(state.get("version") or "")):
        raise HostedE2EError("Hosted E2E lifecycle state contains an invalid version.")
    _validate_state_infrastructure(
        state,
        infrastructure,
        environment=selected.name,
    )
    return state
