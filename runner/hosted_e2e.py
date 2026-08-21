"""Provision and operate the isolated Google-hosted E2E environment."""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import time
import xml.etree.ElementTree as ElementTree

import yaml

from config import APP_DIR, File, SETTINGS, _atomic_write_text
from config.constants import (
    APP_HANDLERS,
    DEFAULT_TEST_PREFIX,
    RUNTIME_BUCKET_ROLES,
    RUNTIME_PROJECT_ROLES,
)
from config.storage import (
    BUCKET_CORS_HEADERS,
    BUCKET_CORS_MAX_AGE_SECONDS,
    BUCKET_CORS_METHODS,
    storage_bucket_names,
)
from runner.context import GCLOUD_CLI, GIT_CLI
from runner.gcloud import activate_repository_gcloud
from runner.process import run_command


STATE_SCHEMA_VERSION = 1
SERVICE = "e2e"
ANCHOR_VERSION = "e2e-anchor"
ANCHOR_REVISION = "2"
JOB = "lagniappe-e2e"
RUNTIME_ACCOUNT = "lagniappe-e2e-runtime"
INVOKER_ACCOUNT = "lagniappe-e2e-invoker"
ARTIFACT_REPOSITORY = "lagniappe-e2e"
SETTINGS_SECRET = "lagniappe-e2e-settings"
REDIS_CA_SECRET = "lagniappe-e2e-redis-ca"
WORKLOAD_POOL = "lagniappe-e2e"
WORKLOAD_PROVIDER = "github"
GITHUB_ENVIRONMENT = "hosted-e2e"
STATE_ROOT = APP_DIR / "reports/hosted-e2e"
STATE_PATH = STATE_ROOT / "state.json"
SETUP_PATH = STATE_ROOT / "setup.json"
CONTAINER_RELATIVE_ROOT = Path("runner/hosted_e2e_container")
CONTAINER_ROOT = APP_DIR / CONTAINER_RELATIVE_ROOT
RUNNER_GCLOUDIGNORE_COPY = "root.gcloudignore"
ANCHOR_ROOT = APP_DIR / "runner/hosted_e2e_anchor"
APP_SETTINGS_RELATIVE_PATH = Path("config/files/lagniappe_settings.yaml")
REDIS_CA_RELATIVE_PATH = Path("config/files/redis_ca.pem")
HOSTED_APIS = (
    "appengine.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com",
)
VERSION_RE = re.compile(r"^e2e-[0-9a-f]{16}$")
EXECUTION_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
BUILD_ID_RE = re.compile(r"^b[0-9a-f]{7}$")
BUILD_METADATA_PATH = Path("lagniappe/web/static/build.json")
BUILD_CONSTANTS_PATH = Path("config/constants.py")
BUILD_SERVICE_WORKER_PATH = Path("lagniappe/web/static/sw.js")
CLOUD_BUILD_IDENTITY_RETRY_DELAYS = (2, 4, 8, 16)
CLOUD_BUILD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$",
    re.IGNORECASE,
)
CLOUD_BUILD_PENDING_STATUSES = {"STATUS_UNKNOWN", "QUEUED", "WORKING", "PENDING"}


# @testable infrastructure
class HostedE2EError(RuntimeError):
    """Raised when a hosted-E2E lifecycle invariant is not satisfied."""


# @testable infrastructure
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

    # @testable infrastructure
    @property
    def image_base(self) -> str:
        return (
            f"{self.region}-docker.pkg.dev/{self.project}/"
            f"{self.artifact_repository}/runner"
        )

    # @testable infrastructure
    @property
    def provider_resource(self) -> str:
        return (
            f"projects/{self.project_number}/locations/global/"
            f"workloadIdentityPools/{self.workload_pool}/providers/"
            f"{self.workload_provider}"
        )


# @testable infrastructure
def _gcloud(*arguments, check=True, timeout=600, capture_output=True):
    if not GCLOUD_CLI:
        raise HostedE2EError("The gcloud CLI is required for hosted E2E commands.")
    return run_command(
        [GCLOUD_CLI, *map(str, arguments)],
        check=check,
        timeout=timeout,
        capture_output=capture_output,
    )


# @testable infrastructure
def _git(*arguments, check=True, repo_root=None):
    result = run_command(
        [GIT_CLI, *map(str, arguments)],
        check=False,
        timeout=60,
        cwd=repo_root or APP_DIR,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise HostedE2EError(detail or "Git command failed.")
    return result


# @testable infrastructure
def _json_result(result, label):
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise HostedE2EError(f"{label} returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise HostedE2EError(f"{label} did not return a JSON object.")
    return value


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_provider_describe_distinguishes_absence_from_operational_errors
# @features hosted-e2e
# @dimensions provider-errors deletion-safety
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


# @testable infrastructure
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


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_cloud_build_identity_waits_for_first_setup_propagation
# @tests tests_tooling/test_009_hosted_e2e.py::test_cloud_build_identity_rejects_legacy_cloud_build_account
# @features hosted-e2e
# @dimensions first-setup api-propagation build-identity
def _cloud_build_service_account(infrastructure):
    """Return the build identity after bounded first-enable propagation."""
    expected_account = (
        f"{infrastructure.project_number}-compute@developer.gserviceaccount.com"
    )
    for attempt in range(len(CLOUD_BUILD_IDENTITY_RETRY_DELAYS) + 1):
        result = _gcloud(
            "builds",
            "get-default-service-account",
            f"--project={infrastructure.project}",
            "--format=value(serviceAccountEmail)",
            check=False,
        )
        value = result.stdout.strip().rsplit("/", 1)[-1]
        if result.returncode == 0 and value == expected_account:
            return value
        if attempt < len(CLOUD_BUILD_IDENTITY_RETRY_DELAYS):
            time.sleep(CLOUD_BUILD_IDENTITY_RETRY_DELAYS[attempt])
    raise HostedE2EError(
        "Google Cloud did not return the Compute Engine default Cloud Build "
        "identity after waiting for first-time API propagation."
    )


# @testable infrastructure
def _infrastructure(*, project_number=None):
    project = str(SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    configured_project = str((SETTINGS.GCLOUD_CONFIG or {}).get("PROJECT") or "").strip()
    if not project or configured_project != project:
        raise HostedE2EError(
            "Hosted E2E requires matching app and repository gcloud projects."
        )
    region = str(SETTINGS.APP.get("RESOURCE_REGION") or "").strip()
    if not region:
        raise HostedE2EError("Hosted E2E requires RESOURCE_REGION.")
    digest = hashlib.sha256(str(SETTINGS.APP.get("GIBBERISH") or "").encode()).hexdigest()
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


# @testable infrastructure
def _write_json(path: Path, payload: dict, *, owner_only=False):
    return _atomic_write_text(
        path,
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n",
        owner_only=owner_only,
    )


# @testable infrastructure
def _load_json(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_e2e_requires_a_clean_committed_source
# @features hosted-e2e
# @dimensions lifecycle source-integrity generated-assets
def require_clean_source(repo_root=APP_DIR):
    """Return HEAD when authored and runtime source exactly match the commit."""
    status = run_command(
        [
            GIT_CLI,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude)lagniappe/web/static/**",
        ],
        cwd=Path(repo_root),
        check=False,
        timeout=60,
    )
    if status.returncode != 0:
        raise HostedE2EError("Could not inspect the Git working tree.")
    if status.stdout.strip():
        raise HostedE2EError(
            "Hosted E2E versions require a clean working tree so the app, "
            "runner image, and evidence all identify one committed source."
        )
    head = run_command(
        [GIT_CLI, "rev-parse", "HEAD"],
        cwd=Path(repo_root),
        check=False,
        timeout=60,
    )
    source = head.stdout.strip().casefold()
    if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise HostedE2EError("Hosted E2E requires a committed Git HEAD.")
    return source


# @testable false
# @covered-by runner/hosted_e2e.py::_require_committed_production_build
# @reason shared fail-closed Git object reader for committed build metadata
def _committed_text(source, relative_path, *, repo_root=APP_DIR):
    result = run_command(
        [GIT_CLI, "show", f"{source}:{Path(relative_path).as_posix()}"],
        cwd=Path(repo_root),
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise HostedE2EError(
            f"The committed production build is missing {relative_path}: "
            f"{detail or 'Git could not read the file.'}"
        )
    return result.stdout


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_e2e_requires_a_committed_production_build
# @features hosted-e2e traceability
# @dimensions source-integrity build-metadata shared-build
def _require_committed_production_build(
    source,
    *,
    repo_root=APP_DIR,
    expected_version=None,
):
    """Validate and return the production build ID stored in ``source``."""
    metadata_text = _committed_text(
        source,
        BUILD_METADATA_PATH,
        repo_root=repo_root,
    )
    try:
        metadata = json.loads(metadata_text)
    except json.JSONDecodeError as error:
        raise HostedE2EError(
            f"{BUILD_METADATA_PATH} is not valid JSON in the committed source."
        ) from error
    if not isinstance(metadata, dict):
        raise HostedE2EError(
            f"{BUILD_METADATA_PATH} must contain a JSON object."
        )
    if metadata.get("mode") != "production":
        raise HostedE2EError(
            "Hosted E2E create requires an already committed production "
            "frontend build. Run `npm run build`, stage the generated output, "
            "and commit it first."
        )

    constants = _committed_text(
        source,
        BUILD_CONSTANTS_PATH,
        repo_root=repo_root,
    )
    match = re.search(
        r'^BUILD_ID\s*=\s*"([^"]+)"\s*$',
        constants,
        flags=re.MULTILINE,
    )
    build_id = match.group(1) if match else ""
    if not BUILD_ID_RE.fullmatch(build_id):
        raise HostedE2EError(
            f"{BUILD_CONSTANTS_PATH} does not contain a valid production build ID."
        )
    if metadata.get("build_id") != build_id:
        raise HostedE2EError(
            f"{BUILD_METADATA_PATH} and {BUILD_CONSTANTS_PATH} do not identify "
            "the same committed build."
        )

    configured_version = (
        SETTINGS.APP.get("VERSION") if expected_version is None else expected_version
    )
    expected_version = (
        str(configured_version).strip() if configured_version is not None else ""
    )
    metadata_version = metadata.get("version")
    metadata_version = (
        str(metadata_version).strip() if metadata_version is not None else ""
    )
    if not expected_version or metadata_version != expected_version:
        raise HostedE2EError(
            f"{BUILD_METADATA_PATH} does not match configured version "
            f"{expected_version or '<missing>'}."
        )

    service_worker = _committed_text(
        source,
        BUILD_SERVICE_WORKER_PATH,
        repo_root=repo_root,
    )
    if build_id not in service_worker:
        raise HostedE2EError(
            f"{BUILD_SERVICE_WORKER_PATH} does not contain committed build ID "
            f"{build_id}."
        )
    return build_id


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_committed_source_export_ignores_generated_worktree_churn
# @features hosted-e2e
# @dimensions source-integrity generated-assets deployment-source
@contextmanager
def _committed_source_tree(source, *, repo_root=APP_DIR):
    """Yield a temporary source tree exported from one exact Git commit."""
    with tempfile.TemporaryDirectory(prefix="lagniappe-hosted-e2e-") as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "source.tar"
        source_root = temporary_root / "source"
        source_root.mkdir()
        result = run_command(
            [
                GIT_CLI,
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                source,
            ],
            cwd=Path(repo_root),
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise HostedE2EError(
                detail or "Could not export the committed hosted-E2E source."
            )
        shutil.unpack_archive(archive_path, source_root, format="tar")
        yield source_root


# @testable infrastructure
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


# @testable infrastructure
def _ensure_service_account(infrastructure, account, display_name):
    email = f"{account}@{infrastructure.project}.iam.gserviceaccount.com"
    if _describe(["iam", "service-accounts", "describe", email]) is None:
        _gcloud(
            "iam",
            "service-accounts",
            "create",
            account,
            f"--display-name={display_name}",
            f"--project={infrastructure.project}",
        )
    return email


# @testable infrastructure
def _project_role(infrastructure, member, role):
    _gcloud(
        "projects",
        "add-iam-policy-binding",
        infrastructure.project,
        f"--member={member}",
        f"--role={role}",
        "--condition=None",
        "--quiet",
    )


# @testable infrastructure
def _remove_project_role(infrastructure, member, role):
    policy = _json_result(
        _gcloud(
            "projects",
            "get-iam-policy",
            infrastructure.project,
            "--format=json",
        ),
        "project IAM policy",
    )
    present = any(
        binding.get("role") == role
        and member in binding.get("members", [])
        and not binding.get("condition")
        for binding in policy.get("bindings", [])
        if isinstance(binding, dict)
    )
    if not present:
        return
    _gcloud(
        "projects",
        "remove-iam-policy-binding",
        infrastructure.project,
        f"--member={member}",
        f"--role={role}",
        "--condition=None",
        "--quiet",
    )


# @testable infrastructure
def _service_account_role(email, member, role):
    _gcloud(
        "iam",
        "service-accounts",
        "add-iam-policy-binding",
        email,
        f"--member={member}",
        f"--role={role}",
        "--condition=None",
        "--quiet",
    )


# @testable infrastructure
def _deployer_member():
    deployer = str((SETTINGS.GCLOUD_CONFIG or {}).get("ACCOUNT") or "").strip()
    if not deployer:
        return None
    member_kind = "serviceAccount" if deployer.endswith("gserviceaccount.com") else "user"
    return f"{member_kind}:{deployer}"


# @testable infrastructure
def _test_bucket_names():
    settings = dict(SETTINGS.APP)
    settings["PREFIX"] = DEFAULT_TEST_PREFIX
    return tuple(storage_bucket_names(settings).values())


# @testable infrastructure
def _ensure_artifact_bucket(infrastructure):
    uri = f"gs://{infrastructure.artifact_bucket}"
    if _describe(["storage", "buckets", "describe", uri]) is None:
        _gcloud(
            "storage",
            "buckets",
            "create",
            uri,
            f"--location={infrastructure.region}",
            "--uniform-bucket-level-access",
            "--public-access-prevention",
        )
    lifecycle = {"rule": [{"action": {"type": "Delete"}, "condition": {"age": 7}}]}
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        dir=STATE_ROOT,
        delete=False,
    ) as stream:
        json.dump(lifecycle, stream)
        lifecycle_path = Path(stream.name)
    try:
        _gcloud(
            "storage",
            "buckets",
            "update",
            uri,
            f"--lifecycle-file={lifecycle_path}",
            "--uniform-bucket-level-access",
            "--public-access-prevention",
        )
    finally:
        lifecycle_path.unlink(missing_ok=True)


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_ci_invoker_can_only_read_the_result_bucket
# @features hosted-e2e
# @dimensions identity least-privilege artifact-download
def _grant_ci_result_access(infrastructure, invoker_member):
    """Let the CI invoker read only the dedicated hosted-result bucket."""
    _gcloud(
        "storage",
        "buckets",
        "add-iam-policy-binding",
        f"gs://{infrastructure.artifact_bucket}",
        f"--member={invoker_member}",
        "--role=roles/storage.objectViewer",
        "--quiet",
    )


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_anchor_redeploys_only_when_its_contract_is_stale
# @features hosted-e2e
# @dimensions anchor reconciliation soft-routing deletion-safety
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


# @testable infrastructure
def _derive_github_repository():
    result = _git("config", "--get", "remote.origin.url", check=False)
    value = result.stdout.strip()
    match = re.search(r"github\.com(?::|/)([^/\s]+/[^/\s]+?)(?:\.git)?$", value)
    return match.group(1) if match else None


# @testable infrastructure
def _ensure_workload_identity(infrastructure, github_repository):
    pool_args = [
        "iam",
        "workload-identity-pools",
        "describe",
        infrastructure.workload_pool,
        "--location=global",
        f"--project={infrastructure.project}",
    ]
    if _describe(pool_args) is None:
        _gcloud(
            "iam",
            "workload-identity-pools",
            "create",
            infrastructure.workload_pool,
            "--location=global",
            "--display-name=Lagniappe hosted E2E",
            f"--project={infrastructure.project}",
        )
    else:
        _gcloud(
            "iam",
            "workload-identity-pools",
            "update",
            infrastructure.workload_pool,
            "--location=global",
            "--display-name=Lagniappe hosted E2E",
            "--no-disabled",
            f"--project={infrastructure.project}",
        )

    provider_args = [
        "iam",
        "workload-identity-pools",
        "providers",
        "describe",
        infrastructure.workload_provider,
        f"--workload-identity-pool={infrastructure.workload_pool}",
        "--location=global",
        f"--project={infrastructure.project}",
    ]
    workflow_prefix = (
        f"{github_repository}/.github/workflows/hosted-e2e.yml@"
    )
    condition = (
        f"assertion.repository=='{github_repository}' && "
        f"assertion.workflow_ref.startsWith('{workflow_prefix}') && "
        f"assertion.environment=='{GITHUB_ENVIRONMENT}'"
    )
    provider_action = (
        "create-oidc" if _describe(provider_args) is None else "update-oidc"
    )
    provider_command = [
        "iam",
        "workload-identity-pools",
        "providers",
        provider_action,
        infrastructure.workload_provider,
        f"--workload-identity-pool={infrastructure.workload_pool}",
        "--location=global",
        "--issuer-uri=https://token.actions.githubusercontent.com",
        (
            "--attribute-mapping=google.subject=assertion.sub,"
            "attribute.repository=assertion.repository,"
            "attribute.workflow_ref=assertion.workflow_ref,"
            "attribute.environment=assertion.environment"
        ),
        f"--attribute-condition={condition}",
        f"--project={infrastructure.project}",
    ]
    if provider_action == "update-oidc":
        provider_command.append("--no-disabled")
    _gcloud(*provider_command)

    principal_set = (
        "principalSet://iam.googleapis.com/"
        f"projects/{infrastructure.project_number}/locations/global/"
        f"workloadIdentityPools/{infrastructure.workload_pool}/"
        f"attribute.repository/{github_repository}"
    )
    _service_account_role(
        infrastructure.invoker_email,
        principal_set,
        "roles/iam.workloadIdentityUser",
    )


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_runtime_identity_roles_include_deployer_signing
# @features hosted-e2e
# @dimensions identity runtime-impersonation
def _grant_runtime_identity_roles(infrastructure, runtime_member, deployer_member):
    """Grant only the runtime impersonation roles required by hosted tests."""
    for role in (
        "roles/iam.serviceAccountTokenCreator",
        "roles/iam.serviceAccountUser",
    ):
        _service_account_role(
            infrastructure.runtime_email,
            runtime_member,
            role,
        )
        if deployer_member:
            _service_account_role(
                infrastructure.runtime_email,
                deployer_member,
                role,
            )

    cloud_run_agent = (
        f"service-{infrastructure.project_number}@serverless-robot-prod."
        "iam.gserviceaccount.com"
    )
    _service_account_role(
        infrastructure.runtime_email,
        f"serviceAccount:{cloud_run_agent}",
        "roles/iam.serviceAccountTokenCreator",
    )


# @testable infrastructure
def setup(github_repository=None):
    """Provision stable least-privilege resources and the inert service anchor."""
    _activate(adc=False)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    infrastructure = _infrastructure()
    github_repository = github_repository or _derive_github_repository()
    if not github_repository or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", github_repository
    ):
        raise HostedE2EError(
            "Pass --github-repository OWNER/REPOSITORY; it could not be derived."
        )

    _gcloud("services", "enable", *HOSTED_APIS, f"--project={infrastructure.project}")
    _ensure_service_account(infrastructure, RUNTIME_ACCOUNT, "Lagniappe E2E runtime")
    _ensure_service_account(infrastructure, INVOKER_ACCOUNT, "Lagniappe E2E CI invoker")

    runtime_member = f"serviceAccount:{infrastructure.runtime_email}"
    invoker_member = f"serviceAccount:{infrastructure.invoker_email}"
    for role in RUNTIME_PROJECT_ROLES:
        _project_role(infrastructure, runtime_member, role)
    # Visibility and execution are granted only on the exact job once it exists.
    for role in (
        "roles/run.viewer",
        "roles/run.invoker",
        "roles/run.jobsExecutor",
        "roles/run.jobsExecutorWithOverrides",
    ):
        _remove_project_role(infrastructure, invoker_member, role)
    deployer_member = _deployer_member()
    _grant_runtime_identity_roles(
        infrastructure,
        runtime_member,
        deployer_member,
    )

    if _describe(
        [
            "artifacts",
            "repositories",
            "describe",
            infrastructure.artifact_repository,
            f"--location={infrastructure.region}",
            f"--project={infrastructure.project}",
        ]
    ) is None:
        _gcloud(
            "artifacts",
            "repositories",
            "create",
            infrastructure.artifact_repository,
            "--repository-format=docker",
            f"--location={infrastructure.region}",
            f"--project={infrastructure.project}",
        )
    cloud_build_member = f"serviceAccount:{_cloud_build_service_account(infrastructure)}"
    _gcloud(
        "artifacts",
        "repositories",
        "add-iam-policy-binding",
        infrastructure.artifact_repository,
        f"--location={infrastructure.region}",
        f"--project={infrastructure.project}",
        f"--member={cloud_build_member}",
        "--role=roles/artifactregistry.writer",
        "--quiet",
    )

    _ensure_artifact_bucket(infrastructure)
    _grant_ci_result_access(infrastructure, invoker_member)
    for bucket_name in (*_test_bucket_names(), infrastructure.artifact_bucket):
        for role in RUNTIME_BUCKET_ROLES:
            _gcloud(
                "storage",
                "buckets",
                "add-iam-policy-binding",
                f"gs://{bucket_name}",
                f"--member={runtime_member}",
                f"--role={role}",
                "--quiet",
            )
    if deployer_member:
        _gcloud(
            "storage",
            "buckets",
            "add-iam-policy-binding",
            f"gs://{infrastructure.artifact_bucket}",
            f"--member={deployer_member}",
            "--role=roles/storage.objectAdmin",
            "--quiet",
        )
    for secret_name in (
        infrastructure.settings_secret,
        infrastructure.redis_ca_secret,
    ):
        if _describe(
            [
                "secrets",
                "describe",
                secret_name,
                f"--project={infrastructure.project}",
            ]
        ) is None:
            _gcloud(
                "secrets",
                "create",
                secret_name,
                "--replication-policy=automatic",
                f"--project={infrastructure.project}",
            )
        _gcloud(
            "secrets",
            "add-iam-policy-binding",
            secret_name,
            f"--member={runtime_member}",
            "--role=roles/secretmanager.secretAccessor",
            f"--project={infrastructure.project}",
            "--quiet",
        )
    _ensure_workload_identity(infrastructure, github_repository)
    _ensure_anchor(infrastructure)

    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "configured_at": datetime.now(timezone.utc).isoformat(),
        "github_repository": github_repository,
        **asdict(infrastructure),
        "provider_resource": infrastructure.provider_resource,
    }
    _write_json(SETUP_PATH, payload)
    return payload


# @testable infrastructure
def _app_default_hostname(infrastructure):
    app = _describe(["app", "describe", f"--project={infrastructure.project}"])
    hostname = str((app or {}).get("defaultHostname") or "").strip()
    if not hostname:
        raise HostedE2EError("Could not determine the App Engine hostname.")
    return hostname


# @testable infrastructure
def _version_url(infrastructure, version):
    hostname = (
        f"{version}-dot-{SERVICE}-dot-{_app_default_hostname(infrastructure)}"
    )
    if len(hostname.split(".", 1)[0]) > 63:
        raise HostedE2EError(
            "Hosted E2E version hostname exceeds the App Engine DNS limit."
        )
    return f"https://{hostname}"


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_soft_routing_guard_preflight_requires_marker
# @features hosted-e2e
# @dimensions soft-routing deletion-safety production-preflight
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


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_descriptor_preserves_native_static_handlers
# @features hosted-e2e
# @dimensions authentication static-assets performance zero-traffic deployment-binding deterministic-topology
def _hosted_app_descriptor(
    infrastructure,
    *,
    version,
    source,
    source_snapshot,
    build_id,
    base_url,
    session_key,
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
    }
    return {
        "runtime": "python314",
        "service": SERVICE,
        "service_account": infrastructure.runtime_email,
        "entrypoint": "gunicorn -t 3600 -w 4 -b :$PORT main:app",
        "instance_class": "B2",
        "basic_scaling": {"max_instances": 1, "idle_timeout": "15m"},
        # Static build artifacts contain no application or test data. Keep them
        # on App Engine's native static path so isolated browser contexts do not
        # serialize thousands of chunk requests through the Gunicorn workers.
        # Every registered application/testing route remains a dynamic handler
        # and is therefore protected by the hosted request gate in Flask.
        "handlers": handlers,
        "env_variables": environment,
    }


# @testable infrastructure
def _change_test_bucket_cors(infrastructure, origin, *, present):
    from google.cloud import storage

    client = storage.Client(project=infrastructure.project)
    for bucket_name in _test_bucket_names():
        bucket = client.get_bucket(bucket_name)
        rules = copy.deepcopy(list(bucket.cors or []))
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
                origins.append(origin)
                changed = True
            if not present and origin in origins:
                origins = [value for value in origins if value != origin]
                changed = True
            if origins:
                rule["origin"] = sorted(set(origins))
                updated.append(rule)
        if changed:
            bucket.cors = updated
            bucket.patch()


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_runner_image_uses_the_exported_commit
# @features hosted-e2e
# @dimensions image-boundary deployment-source
def _build_runner_image(infrastructure, source, source_root):
    """Start a resumable image build from the exported committed tree."""
    container_root = Path(source_root) / CONTAINER_RELATIVE_ROOT
    canonical_ignore = Path(source_root) / ".gcloudignore"
    if not canonical_ignore.is_file():
        raise HostedE2EError("The committed source has no canonical .gcloudignore.")
    shutil.copyfile(
        canonical_ignore,
        container_root / RUNNER_GCLOUDIGNORE_COPY,
    )
    image = f"{infrastructure.image_base}:{source}"
    result = _gcloud(
        "builds",
        "submit",
        source_root,
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


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_runner_image_build_waits_for_recorded_cloud_build
# @features hosted-e2e
# @dimensions build-resume provider-status failure-recovery
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
                payload.get("statusDetail")
                or failure_info.get("detail")
                or ""
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


# @testable false
# @covered-by runner/hosted_e2e.py::create
# @reason App Engine receives only the same canonical runtime files as normal deploy
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
            raise HostedE2EError(
                f"Hosted E2E runtime file is missing: {relative_path}"
            )
        destination = source_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


# @testable infrastructure
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
    raise HostedE2EError(
        f"Hosted E2E version did not become ready: {last_error}"
    )


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_settings_and_redis_ca_use_separate_secret_versions
# @features hosted-e2e
# @dimensions secrets redis-tls image-boundary
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


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_job_grants_only_job_scoped_ci_permissions
# @features hosted-e2e
# @dimensions identity least-privilege invocation-overrides
def _update_job(infrastructure, state):
    environment = {
        "FLASK_ENV": "testing",
        "GOOGLE_CLOUD_PROJECT": infrastructure.project,
        "LAGNIAPPE_HOSTED_E2E": "true",
        "LAGNIAPPE_HOSTED_E2E_ROLE": "runner",
        "LAGNIAPPE_HOSTED_E2E_BASE_URL": state["base_url"],
        "LAGNIAPPE_HOSTED_E2E_PREFIX": DEFAULT_TEST_PREFIX,
        "LAGNIAPPE_HOSTED_E2E_RUNTIME_SERVICE_ACCOUNT_EMAIL": infrastructure.runtime_email,
        "LAGNIAPPE_HOSTED_E2E_VERSION": state["version"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE": state["source"],
        "LAGNIAPPE_HOSTED_E2E_SOURCE_SNAPSHOT": state["source_snapshot"],
        "LAGNIAPPE_HOSTED_E2E_BUILD_ID": state["build_id"],
        "LAGNIAPPE_HOSTED_E2E_SERVICE": SERVICE,
        "LAGNIAPPE_HOSTED_E2E_CALLER_EMAIL": infrastructure.runtime_email,
        "LAGNIAPPE_HOSTED_E2E_JOB": infrastructure.job,
        "LAGNIAPPE_HOSTED_E2E_ARTIFACT_BUCKET": infrastructure.artifact_bucket,
    }
    env_argument = ",".join(f"{key}={value}" for key, value in environment.items())
    secret_mounts = [
        "/workspace/config/files/lagniappe_settings.yaml="
        f"{infrastructure.settings_secret}:latest"
    ]
    if SETTINGS.APP.get("REDIS_TLS"):
        secret_mounts.append(
            "/workspace/config/files/redis_ca.pem="
            f"{infrastructure.redis_ca_secret}:latest"
        )
    exists = _describe(
        [
            "run",
            "jobs",
            "describe",
            infrastructure.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
        ]
    )
    action = "update" if exists else "create"
    _gcloud(
        "run",
        "jobs",
        action,
        infrastructure.job,
        f"--image={state['image']}",
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        f"--service-account={infrastructure.runtime_email}",
        f"--set-env-vars={env_argument}",
        f"--set-secrets={','.join(secret_mounts)}",
        "--tasks=1",
        "--parallelism=1",
        "--max-retries=0",
        "--task-timeout=7200s",
        "--cpu=2",
        "--memory=4Gi",
        "--quiet",
        timeout=1800,
    )
    _gcloud(
        "run",
        "jobs",
        "add-iam-policy-binding",
        infrastructure.job,
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
        infrastructure.job,
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
            infrastructure.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
            f"--member={deployer_member}",
            "--role=roles/run.jobsExecutorWithOverrides",
            "--quiet",
        )


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_create_resumes_only_the_same_committed_lifecycle
# @features hosted-e2e
# @dimensions lifecycle resume source-integrity failure-recovery
def _resumable_create_state(
    previous,
    infrastructure,
    *,
    source,
    source_snapshot,
    build_id,
):
    """Return interrupted exact-source state, or reject an unsafe replacement."""
    if not previous or previous.get("status") == "torn-down":
        return None
    if previous.get("schema_version") != STATE_SCHEMA_VERSION:
        raise HostedE2EError("The previous hosted E2E lifecycle state is invalid.")
    if previous.get("status") not in {"creating", "failed"}:
        raise HostedE2EError(
            "The previous hosted E2E lifecycle has not been torn down; "
            "inspect its status and tear it down first."
        )
    _validate_state_infrastructure(previous, infrastructure)
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
    version = str(previous.get("version") or "")
    if not VERSION_RE.fullmatch(version):
        raise HostedE2EError("The interrupted lifecycle has an invalid version.")
    if previous.get("base_url") != _version_url(infrastructure, version):
        raise HostedE2EError("The interrupted lifecycle has an invalid version URL.")
    expected_image = f"{infrastructure.image_base}:{source}"
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
        raise HostedE2EError(
            "The interrupted lifecycle has an invalid Cloud Build ID."
        )
    return dict(previous)


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_app_resume_requires_exact_deployment_metadata
# @features hosted-e2e
# @dimensions lifecycle resume deployment-source failure-recovery
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
    mismatches = [
        name for name, value in expected.items() if variables.get(name) != value
    ]
    if mismatches:
        raise HostedE2EError(
            "The state-owned App Engine version has unexpected deployment "
            f"metadata ({', '.join(mismatches)})."
        )
    return True


# @testable infrastructure
def create():
    """Deploy one committed production build as a test app and runner."""
    source = require_clean_source()
    build_id = _require_committed_production_build(source)
    from testing.utility.traceability_common import behavior_snapshot

    source_snapshot, _source_paths = behavior_snapshot(APP_DIR)
    _activate(adc=True)
    infrastructure = _infrastructure()
    setup_state = _load_json(SETUP_PATH)
    if not setup_state or setup_state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise HostedE2EError("Run `run.py hosted-e2e setup` first.")
    _validate_state_infrastructure(setup_state, infrastructure)
    _verify_soft_routing_guard(infrastructure)
    previous = _load_json(STATE_PATH)
    state = _resumable_create_state(
        previous,
        infrastructure,
        source=source,
        source_snapshot=source_snapshot,
        build_id=build_id,
    )
    if state is None:
        version = "e2e-" + secrets.token_hex(8)
        base_url = _version_url(infrastructure, version)
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "creating",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project": infrastructure.project,
            "region": infrastructure.region,
            "service": SERVICE,
            "job": infrastructure.job,
            "version": version,
            "source": source,
            "source_snapshot": source_snapshot,
            "build_id": build_id,
            "base_url": base_url,
            "artifact_bucket": infrastructure.artifact_bucket,
            "image": f"{infrastructure.image_base}:{source}",
        }
    else:
        state["status"] = "creating"
        state["resumed_at"] = datetime.now(timezone.utc).isoformat()
        state.setdefault("image", f"{infrastructure.image_base}:{source}")
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(STATE_PATH, state, owner_only=True)

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
                    _write_json(STATE_PATH, state, owner_only=True)
                _wait_runner_image_build(infrastructure, cloud_build_id)
                state["image_ready"] = True
                _write_json(STATE_PATH, state, owner_only=True)

            if not state.get("settings_synced"):
                _sync_settings_secret(infrastructure)
                state["settings_synced"] = True
                _write_json(STATE_PATH, state, owner_only=True)

            _change_test_bucket_cors(
                infrastructure,
                state["base_url"],
                present=True,
            )
            state["cors_added"] = True
            _write_json(STATE_PATH, state, owner_only=True)

            if _hosted_app_version_present(infrastructure, state):
                state["app_deployed"] = True
                _write_json(STATE_PATH, state, owner_only=True)
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
                    _write_json(STATE_PATH, state, owner_only=True)
                finally:
                    descriptor_path.unlink(missing_ok=True)

        _wait_hosted_health(state)
        _update_job(infrastructure, state)
        state["job_updated"] = True
        state["status"] = "ready"
        _write_json(STATE_PATH, state, owner_only=True)
        return state
    except Exception:
        state["status"] = "failed"
        _write_json(STATE_PATH, state, owner_only=True)
        raise


# @testable infrastructure
def _validate_state_infrastructure(state, infrastructure):
    expected = {
        "project": infrastructure.project,
        "region": infrastructure.region,
        "service": SERVICE,
        "job": infrastructure.job,
        "artifact_bucket": infrastructure.artifact_bucket,
    }
    mismatches = [
        name for name, value in expected.items() if state.get(name) != value
    ]
    if mismatches:
        raise HostedE2EError(
            "Hosted E2E lifecycle state belongs to different infrastructure "
            f"({', '.join(mismatches)}); restore that configuration before "
            "operating on it."
        )


# @testable infrastructure
def _state_ready(infrastructure):
    state = _load_json(STATE_PATH)
    if not state or state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise HostedE2EError("No hosted E2E lifecycle state exists.")
    if state.get("status") != "ready":
        raise HostedE2EError(
            f"Hosted E2E state is {state.get('status', 'invalid')!r}, not ready."
        )
    if not re.fullmatch(r"b[0-9a-f]{7}", str(state.get("build_id") or "")):
        raise HostedE2EError("Hosted E2E lifecycle state contains an invalid build ID.")
    if not VERSION_RE.fullmatch(str(state.get("version") or "")):
        raise HostedE2EError("Hosted E2E lifecycle state contains an invalid version.")
    _validate_state_infrastructure(state, infrastructure)
    return state


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_execute_recovers_failed_execution_name_from_gcloud_stderr
# @features hosted-e2e
# @dimensions execution-name failure-recovery
def _execution_name(payload, *output):
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if isinstance(name, str) and "/" in name:
        name = name.rsplit("/", 1)[-1]
    if isinstance(name, str) and EXECUTION_RE.fullmatch(name):
        return name
    patterns = (
        r"\bexecutions/(?P<name>lagniappe-e2e-[a-z0-9-]*[a-z0-9])\b",
        r"\bExecution\s+\[?(?P<name>lagniappe-e2e-[a-z0-9-]*[a-z0-9])\]?",
        r"\bexecutions\s+describe\s+(?P<name>lagniappe-e2e-[a-z0-9-]*[a-z0-9])\b",
    )
    for value in output:
        for pattern in patterns:
            match = re.search(pattern, value or "")
            if match and EXECUTION_RE.fullmatch(match.group("name")):
                return match.group("name")
    return None


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_execution_wait_reports_progress_and_failure
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_execution_wait_recognizes_success
# @features hosted-e2e
# @dimensions execution-status progress failure-reporting success
def _wait_for_execution(
    infrastructure,
    execution,
    *,
    timeout=9000,
    poll_interval=5,
    report_interval=30,
    report=True,
    monotonic=time.monotonic,
    sleep=time.sleep,
):
    """Wait for one Cloud Run execution and report useful periodic status."""
    started = monotonic()
    deadline = started + timeout
    visibility_deadline = started + 120
    next_report = started
    previous_phase = None

    while True:
        payload = _describe(
            [
                "run",
                "jobs",
                "executions",
                "describe",
                execution,
                f"--region={infrastructure.region}",
                f"--project={infrastructure.project}",
            ]
        )
        now = monotonic()
        if payload is None:
            if now >= visibility_deadline:
                raise HostedE2EError(
                    f"Cloud Run execution {execution} did not become visible."
                )
            phase = "STARTING"
            terminal = False
            exit_status = None
            task_count = 1
            succeeded = running = failed = 0
            message = "Waiting for Cloud Run to publish execution status."
        else:
            status = payload.get("status")
            status = status if isinstance(status, dict) else {}
            spec = payload.get("spec")
            spec = spec if isinstance(spec, dict) else {}
            conditions = status.get("conditions")
            conditions = conditions if isinstance(conditions, list) else []
            completed = next(
                (
                    condition
                    for condition in conditions
                    if isinstance(condition, dict)
                    and condition.get("type") == "Completed"
                ),
                {},
            )
            completed_status = str(completed.get("status") or "Unknown")
            terminal = bool(status.get("completionTime")) or completed_status in {
                "True",
                "False",
            }
            task_count = int(spec.get("taskCount") or 1)
            succeeded = int(status.get("succeededCount") or 0)
            running = int(status.get("runningCount") or 0)
            failed = int(status.get("failedCount") or 0)
            message = str(completed.get("message") or "").strip()
            if terminal:
                exit_status = 0 if completed_status == "True" and not failed else 1
                phase = "PASSED" if exit_status == 0 else "FAILED"
            else:
                exit_status = None
                started_condition = any(
                    isinstance(condition, dict)
                    and condition.get("type") == "Started"
                    and condition.get("status") == "True"
                    for condition in conditions
                )
                phase = "RUNNING" if running or started_condition else "STARTING"

        should_report = report and (
            now >= next_report or phase != previous_phase or terminal
        )
        if should_report:
            elapsed = max(0, int(now - started))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            print(
                f"[{hours:02d}:{minutes:02d}:{seconds:02d}] {phase}: "
                f"{succeeded}/{task_count} tasks succeeded, "
                f"{running} running, {failed} failed",
                flush=True,
            )
            if terminal and message:
                print(f"  {message}", flush=True)
            while next_report <= now:
                next_report += report_interval
            previous_phase = phase

        if terminal:
            return payload, exit_status
        if now >= deadline:
            raise HostedE2EError(
                f"Cloud Run execution {execution} did not finish within "
                f"{timeout} seconds."
            )
        sleep(poll_interval)


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_execute_summary_reports_unique_junit_failures
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_execute_command_defaults_to_all_and_imports
# @features hosted-e2e
# @dimensions result-summary junit duration artifact-location
def format_execute_summary(payload, *, imported=True, state_root=STATE_ROOT):
    """Format an operator-facing summary for one hosted execution result."""
    execution = str(payload.get("execution") or "unknown")
    exit_status = int(payload.get("exit_status") or 0)
    result = "PASSED" if exit_status == 0 else "FAILED"
    lines = [
        "",
        f"Hosted E2E {result}",
        f"Execution: {execution}",
        f"Suite: {payload.get('suite') or 'unknown'}",
    ]
    source = str(payload.get("source") or "").strip()
    if source:
        lines.append(f"Source: {source}")
    version = str(payload.get("version") or "").strip()
    build_id = str(payload.get("build_id") or "").strip()
    if version or build_id:
        deployment = version or "unknown version"
        if build_id:
            deployment = f"{deployment} (build {build_id})"
        lines.append(f"Deployment: {deployment}")

    started_at = payload.get("suite_started_at")
    finished_at = payload.get("suite_finished_at")
    if isinstance(started_at, str) and isinstance(finished_at, str):
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            elapsed = max(0, int((finished - started).total_seconds()))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                duration = f"{hours}h {minutes}m {seconds}s"
            elif minutes:
                duration = f"{minutes}m {seconds}s"
            else:
                duration = f"{seconds}s"
            lines.append(f"Duration: {duration}")
        except ValueError:
            pass

    destination = Path(state_root) / "results" / execution
    junit_path = destination / "junit.xml"
    if imported and junit_path.is_file():
        try:
            testcases = ElementTree.parse(junit_path).getroot().findall(
                ".//testcase"
            )
        except (ElementTree.ParseError, OSError):
            testcases = []
        if testcases:
            outcomes = {}
            teardown_errors = 0
            for testcase in testcases:
                identity = (
                    testcase.get("classname") or "",
                    testcase.get("name") or "",
                )
                outcome = outcomes.setdefault(
                    identity,
                    {"failure": None, "error": None, "skipped": False},
                )
                failure = testcase.find("failure")
                error = testcase.find("error")
                skipped = testcase.find("skipped")
                if failure is not None and outcome["failure"] is None:
                    outcome["failure"] = failure
                if error is not None and outcome["error"] is None:
                    outcome["error"] = error
                if error is not None:
                    teardown_errors += 1
                if skipped is not None:
                    outcome["skipped"] = True

            failed = [
                (identity, outcome)
                for identity, outcome in outcomes.items()
                if outcome["failure"] is not None or outcome["error"] is not None
            ]
            skipped_count = sum(
                outcome["skipped"]
                and outcome["failure"] is None
                and outcome["error"] is None
                for outcome in outcomes.values()
            )
            passed = len(outcomes) - len(failed) - skipped_count
            lines.append(
                f"Tests: {len(outcomes):,} total — {passed:,} passed, "
                f"{len(failed):,} failed, {skipped_count:,} skipped"
            )
            if teardown_errors:
                lines.append(f"Additional error records: {teardown_errors:,}")
            if failed:
                lines.append("Failed tests:")
                for (classname, name), outcome in failed[:12]:
                    parts = classname.split(".") if classname else []
                    module_indexes = [
                        index
                        for index, part in enumerate(parts)
                        if part.startswith("test_")
                    ]
                    if parts and module_indexes and parts[0].startswith("tests_"):
                        module_index = module_indexes[-1]
                        test_path = Path(
                            "testing", *parts[: module_index + 1]
                        ).with_suffix(".py")
                        qualifiers = parts[module_index + 1 :]
                        nodeid_parts = [test_path.as_posix(), *qualifiers, name]
                        nodeid = "::".join(part for part in nodeid_parts if part)
                    else:
                        nodeid = f"{classname}::{name}" if classname else name
                    problem = (
                        outcome["failure"]
                        if outcome["failure"] is not None
                        else outcome["error"]
                    )
                    message = (
                        str(problem.get("message") or "").splitlines()[0].strip()
                    )
                    lines.append(f"  - {nodeid}")
                    if message:
                        lines.append(f"    {message}")
                remaining = len(failed) - 12
                if remaining:
                    lines.append(f"  - …and {remaining} more; see JUnit XML below.")

    if imported:
        lines.append(f"Artifacts: {destination.resolve()}")
        if junit_path.is_file():
            lines.append(f"JUnit XML: {junit_path.resolve()}")
    else:
        lines.append("Results were left in Cloud Storage and were not imported.")
        lines.append(
            "Import later: venv/bin/python run.py hosted-e2e results "
            f"--execution {execution}"
        )
    return "\n".join(lines)


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_execute_dispatches_validated_focused_targets
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_focused_targets_require_existing_e2e_nodeids
# @features hosted-e2e
# @dimensions focused-execution cloud-run override local-dispatch target-validation argument-injection
def execute(*, suite="all", targets=(), import_results=True, progress=True):
    """Execute the shared Cloud Run job and normally import its evidence."""
    from testing.utility.hosted_e2e_job import validate_focused_targets

    targets = tuple(targets or ())
    if suite == "focused":
        try:
            targets = validate_focused_targets(targets)
        except RuntimeError as error:
            raise HostedE2EError(str(error)) from error
    elif targets:
        raise HostedE2EError(
            "Focused targets require the hosted E2E focused suite."
        )
    elif suite not in {"all", "full"}:
        raise HostedE2EError(f"Unsupported hosted E2E suite {suite!r}.")

    _activate(adc=import_results)
    infrastructure = _infrastructure()
    state = _state_ready(infrastructure)
    # Cloud Run's execution override uses gcloud's UpdateAction parser, which
    # rejects repeated list entries such as separate ``--target`` tokens.
    # ``argparse`` accepts the equivalent equals form inside the container.
    job_arguments = [f"--suite={suite}"]
    for target in targets:
        job_arguments.append(f"--target={target}")
    result = _gcloud(
        "run",
        "jobs",
        "execute",
        infrastructure.job,
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        f"--args={','.join(job_arguments)}",
        "--async",
        "--format=json",
        check=False,
        timeout=300,
    )
    payload = {}
    if result.stdout.strip():
        try:
            payload = _json_result(result, "Cloud Run execution")
        except HostedE2EError:
            if result.returncode == 0:
                raise
    execution = _execution_name(payload, result.stdout, result.stderr)
    if execution is None:
        raise HostedE2EError(
            result.stderr.strip() or "Cloud Run did not identify the job execution."
        )
    state["last_execution"] = execution
    state["last_suite"] = suite
    state["last_targets"] = list(targets)
    _write_json(STATE_PATH, state, owner_only=True)
    if progress:
        print(f"Hosted E2E execution: {execution}", flush=True)
        print(
            "Progress updates will be printed at least every 30 seconds.",
            flush=True,
        )
    _provider_status, exit_status = _wait_for_execution(
        infrastructure,
        execution,
        report=progress,
    )
    if not import_results:
        return {"execution": execution, "exit_status": exit_status, "suite": suite}
    manifest = results(execution=execution, latest=False, merge=True)
    return manifest


# @testable infrastructure
def _latest_execution(infrastructure):
    from google.cloud import storage

    client = storage.Client(project=infrastructure.project)
    bucket = client.bucket(infrastructure.artifact_bucket)
    manifests = [
        blob
        for blob in client.list_blobs(bucket, prefix="executions/")
        if blob.name.endswith("/manifest.json")
    ]
    if not manifests:
        raise HostedE2EError("No hosted E2E result artifacts exist.")
    newest = max(manifests, key=lambda blob: blob.updated or datetime.min.replace(tzinfo=timezone.utc))
    return newest.name.split("/", 2)[1]


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_remote_evidence_merges_tests_and_snapshot_provenance
# @features hosted-e2e traceability
# @dimensions evidence merge provenance
def merge_remote_evidence(local, remote):
    """Merge a hosted pytest manifest into the normal latest evidence file."""
    from testing.utility.traceability_common import (
        TEST_RUN_SCHEMA_VERSION,
        decode_test_run_snapshots,
        encode_test_run_snapshots,
    )

    if not isinstance(remote, dict) or remote.get("schema_version") != TEST_RUN_SCHEMA_VERSION:
        raise HostedE2EError("Hosted result evidence has an unsupported schema.")
    if remote.get("kind") != "test-run" or not isinstance(remote.get("tests"), dict):
        raise HostedE2EError("Hosted result evidence is malformed.")
    local = local if isinstance(local, dict) and local.get("schema_version") in {2, TEST_RUN_SCHEMA_VERSION} else {}
    tests = dict(local.get("tests") or {})
    tests.update(remote["tests"])
    snapshots = decode_test_run_snapshots(local)
    for snapshot_id, paths in decode_test_run_snapshots(remote).items():
        if snapshot_id in snapshots and snapshots[snapshot_id] != paths:
            raise HostedE2EError("Evidence snapshot identity collision detected.")
        snapshots[snapshot_id] = paths
    used_snapshots = {
        row.get("snapshot")
        for row in tests.values()
        if isinstance(row, dict) and isinstance(row.get("snapshot"), str)
    }
    snapshots = {key: value for key, value in snapshots.items() if key in used_snapshots}
    pairs, encoded = encode_test_run_snapshots(snapshots)
    sessions = [
        *list(local.get("sessions") or []),
        *list(remote.get("sessions") or []),
    ][-50:]
    return {
        "schema_version": TEST_RUN_SCHEMA_VERSION,
        "kind": "test-run",
        "provenance": remote.get("provenance") or {},
        "exit_status": int(remote.get("exit_status") or 0),
        "sessions": sessions,
        "fingerprint_pairs": pairs,
        "snapshots": encoded,
        "tests": dict(sorted(tests.items())),
    }


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_result_directory_import_requires_the_exact_source
# @tests tests_tooling/test_009_hosted_e2e.py::test_traceability_common_import_does_not_require_playwright
# @features hosted-e2e traceability
# @dimensions evidence merge provenance source-integrity ci-import
def import_result_directory(directory, *, expected_execution=None):
    """Validate and merge an already-downloaded hosted result directory."""
    from testing.utility.traceability_common import (
        LATEST_TEST_RUN,
        behavior_snapshot,
        load_json,
        write_json,
    )

    directory = Path(directory)
    manifest = load_json(directory / "manifest.json")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "hosted-e2e-result"
    ):
        raise HostedE2EError("Hosted result manifest has an unsupported schema.")
    execution = manifest.get("execution") if isinstance(manifest, dict) else None
    if not isinstance(execution, str) or not EXECUTION_RE.fullmatch(execution):
        raise HostedE2EError("Hosted result manifest has no valid execution name.")
    if expected_execution is not None and execution != expected_execution:
        raise HostedE2EError("Hosted result manifest does not match its execution.")

    source = _git("rev-parse", "HEAD").stdout.strip().casefold()
    source_snapshot, _source_paths = behavior_snapshot(APP_DIR)
    if (
        manifest.get("source") != source
        or manifest.get("source_snapshot") != source_snapshot
    ):
        raise HostedE2EError(
            "Hosted result source does not match the local semantic tree; "
            f"artifacts remain at {directory} but evidence was not merged."
        )

    remote = load_json(directory / "evidence.json")
    evidence_path = APP_DIR / LATEST_TEST_RUN
    merged = merge_remote_evidence(load_json(evidence_path), remote)
    write_json(evidence_path, merged)
    return manifest


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_release_evidence_validation_requires_exact_candidate_parent_and_snapshot
# @tests tests_tooling/test_009_hosted_e2e.py::test_release_evidence_validation_rejects_failed_or_focused_results
# @pairs hosted-e2e:source-integrity hosted-e2e:branch-movement
# @pairs hosted-e2e:failure-retention hosted-e2e:suite-scope
# @pairs hosted-e2e:target-validation traceability:evidence release:continuation
def validate_release_evidence(
    candidate,
    evidence,
    *,
    base,
    repo_root=APP_DIR,
):
    """Validate passing hosted evidence for an exact release commit chain."""
    from testing.utility.traceability_common import (
        LATEST_TEST_RUN,
        TEST_RUN_SCHEMA_VERSION,
        behavior_snapshot,
        load_json,
    )

    repo_root = Path(repo_root)
    revisions = {"base": base, "candidate": candidate, "evidence": evidence}
    for label, revision in revisions.items():
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise HostedE2EError(f"The release {label} is not an exact commit SHA.")

    head = _git("rev-parse", "HEAD", repo_root=repo_root).stdout.strip().casefold()
    if head != evidence:
        raise HostedE2EError(
            f"The checked-out release head is {head}, not evidence commit {evidence}."
        )

    ancestry = _git(
        "merge-base",
        "--is-ancestor",
        base,
        candidate,
        check=False,
        repo_root=repo_root,
    )
    if ancestry.returncode != 0:
        raise HostedE2EError(
            "The release candidate is not descended from the pull-request base."
        )

    mode = "candidate"
    if evidence != candidate:
        mode = "continuation"
        parents = _git(
            "show",
            "--no-patch",
            "--format=%P",
            evidence,
            repo_root=repo_root,
        ).stdout.strip().casefold().split()
        if parents != [candidate]:
            raise HostedE2EError(
                "The evidence continuation must have the exact candidate as its only parent."
            )
        changed = _git(
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            candidate,
            evidence,
            repo_root=repo_root,
        ).stdout.splitlines()
        if changed != [f"M\t{LATEST_TEST_RUN.as_posix()}"]:
            raise HostedE2EError(
                "The evidence continuation must modify only testing/evidence/latest.json."
            )

    payload = load_json(repo_root / LATEST_TEST_RUN)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != TEST_RUN_SCHEMA_VERSION
        or payload.get("kind") != "test-run"
    ):
        raise HostedE2EError("Release evidence has an unsupported schema.")
    provenance = payload.get("provenance")
    hosted = provenance.get("hosted_e2e") if isinstance(provenance, dict) else None
    if not isinstance(hosted, dict):
        raise HostedE2EError("Release evidence has no hosted-E2E provenance.")

    source_snapshot, _source_paths = behavior_snapshot(repo_root)
    if hosted.get("source") != candidate:
        raise HostedE2EError(
            "Release evidence does not name the exact candidate source."
        )
    if hosted.get("source_snapshot") != source_snapshot:
        raise HostedE2EError(
            "Release evidence does not match the current semantic source tree."
        )
    if hosted.get("suite") != "all" or "targets" in hosted:
        raise HostedE2EError(
            "Release evidence must come from the complete hosted all suite."
        )
    if type(payload.get("exit_status")) is not int or payload["exit_status"] != 0:
        raise HostedE2EError("The hosted release suite did not pass.")

    return {
        "base": base,
        "candidate": candidate,
        "evidence": evidence,
        "mode": mode,
        "source_snapshot": source_snapshot,
    }


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_results_can_skip_large_report_archive
# @features hosted-e2e traceability
# @dimensions artifact-download selective-download progress
def results(
    *,
    execution=None,
    latest=False,
    merge=True,
    include_report_archive=True,
):
    """Download one result bundle and merge its outcomes into evidence.json."""
    _activate(adc=True)
    infrastructure = _infrastructure()
    state = _load_json(STATE_PATH) or {}
    if latest:
        execution = _latest_execution(infrastructure)
    execution = execution or state.get("last_execution")
    if not isinstance(execution, str) or not EXECUTION_RE.fullmatch(execution):
        raise HostedE2EError("A valid Cloud Run execution name is required.")

    from google.cloud import storage
    destination = STATE_ROOT / "results" / execution
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading hosted test artifacts to {destination}", flush=True)
    client = storage.Client(project=infrastructure.project)
    bucket = client.bucket(infrastructure.artifact_bucket)
    downloaded = {}
    artifact_names = ["manifest.json", "evidence.json", "junit.xml"]
    if include_report_archive:
        artifact_names.append("reports.tar.gz")
    for name in artifact_names:
        blob = bucket.blob(f"executions/{execution}/{name}")
        if not blob.exists(client=client):
            if name in {"manifest.json", "evidence.json"}:
                raise HostedE2EError(f"Hosted result is missing required {name}.")
            continue
        path = destination / name
        print(f"  downloading {name}...", end="", flush=True)
        blob.download_to_filename(path)
        print(f" {path.stat().st_size:,} bytes", flush=True)
        downloaded[name] = path

    manifest = _load_json(downloaded["manifest.json"])
    if not manifest or manifest.get("execution") != execution:
        raise HostedE2EError("Hosted result manifest does not match its execution.")
    if merge:
        return import_result_directory(
            destination,
            expected_execution=execution,
        )
    return manifest


# @testable infrastructure
def _acquire_cleanup_lease():
    """Clean stale data and keep the lease until provider teardown finishes."""
    os.environ["FLASK_ENV"] = "testing"
    from lagniappe.core.tools.e2e_lease import E2ELease
    from runner.testing import cleanup_test_data

    lease = E2ELease()
    lease.__enter__()
    try:
        lease.assert_active()
        cleanup_test_data()
        lease.assert_active()
    except BaseException:
        lease.__exit__(None, None, None)
        raise
    return lease


# @testable infrastructure
def _active_job_executions(infrastructure):
    result = _gcloud(
        "run",
        "jobs",
        "executions",
        "list",
        f"--job={infrastructure.job}",
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        "--limit=20",
        "--format=json",
    )
    try:
        executions = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as error:
        raise HostedE2EError(
            "Cloud Run execution listing returned invalid JSON."
        ) from error
    if not isinstance(executions, list):
        raise HostedE2EError("Cloud Run execution listing was not a JSON list.")

    active = []
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        status = execution.get("status")
        status = status if isinstance(status, dict) else {}
        if execution.get("completionTime") or status.get("completionTime"):
            continue
        name = execution.get("name")
        metadata = execution.get("metadata")
        if not name and isinstance(metadata, dict):
            name = metadata.get("name")
        if isinstance(name, str) and "/" in name:
            name = name.rsplit("/", 1)[-1]
        if isinstance(name, str) and EXECUTION_RE.fullmatch(name):
            active.append(name)
    return tuple(sorted(set(active)))


# @testable false
# @covered-by runner/hosted_e2e.py::teardown
# @reason teardown owns the lifecycle boundary for downloaded result cleanup
def _clear_local_result_artifacts():
    """Remove downloaded result bundles after a successful lifecycle teardown."""
    result_root = STATE_ROOT / "results"
    if not result_root.exists() and not result_root.is_symlink():
        return False
    if result_root.is_symlink() or result_root.is_file():
        result_root.unlink()
    else:
        shutil.rmtree(result_root)
    print(f"Removed local hosted E2E artifacts: {result_root}")
    return True


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_teardown_removes_downloaded_results_after_success
# @features hosted-e2e
# @dimensions teardown local-artifacts evidence-retention deletion-safety
def teardown(*, force=False):
    """Delete ephemeral resources and downloaded artifacts for the lifecycle."""
    (APP_DIR / ".hosted-e2e-app.yaml").unlink(missing_ok=True)
    _activate(adc=True)
    infrastructure = _infrastructure()
    state = _load_json(STATE_PATH)
    if not state:
        raise HostedE2EError("No hosted E2E lifecycle state exists.")
    _validate_state_infrastructure(state, infrastructure)
    version = str(state.get("version") or "")
    base_url = str(state.get("base_url") or "")
    if not VERSION_RE.fullmatch(version) or version == ANCHOR_VERSION:
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
            infrastructure.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
        ]
    )
    active_executions = _active_job_executions(infrastructure) if job else ()
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

    cleanup_lease = None
    try:
        cleanup_lease = _acquire_cleanup_lease()
    except Exception as error:
        if not force:
            raise HostedE2EError(
                "Could not acquire the shared data lease for final cleanup; "
                f"wait for an active run or resolve the cleanup error ({error}), "
                "then retry or use --force."
            ) from error

    try:
        if job is not None:
            _gcloud(
                "run",
                "jobs",
                "delete",
                infrastructure.job,
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
        state["torn_down_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(STATE_PATH, state, owner_only=True)
        _clear_local_result_artifacts()
        return state
    finally:
        if cleanup_lease is not None:
            cleanup_lease.__exit__(None, None, None)


# @testable infrastructure
def status():
    """Return local lifecycle state plus live App Engine/job presence."""
    _activate(adc=False)
    infrastructure = _infrastructure()
    state = _load_json(STATE_PATH) or {"status": "absent"}
    version = state.get("version")
    app_version = None
    if isinstance(version, str) and VERSION_RE.fullmatch(version):
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
            infrastructure.job,
            f"--region={infrastructure.region}",
            f"--project={infrastructure.project}",
        ]
    )
    return {
        **state,
        "app_version_present": app_version is not None,
        "job_present": job is not None,
    }


# @testable true
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_execute_command_defaults_to_all_and_imports
# @tests tests_tooling/test_009_hosted_e2e.py::test_hosted_release_evidence_command_routes_validation
# @features hosted-e2e
# @dimensions cli-routing suite-scope evidence-import
def run_hosted_e2e_command(arguments):
    parser = argparse.ArgumentParser(
        prog="run.py hosted-e2e",
        description="Run repository tests in an isolated Google-hosted environment.",
    )
    commands = parser.add_subparsers(dest="action", required=True)
    setup_parser = commands.add_parser("setup", help="Provision stable hosted-E2E resources.")
    setup_parser.add_argument("--github-repository", metavar="OWNER/REPOSITORY")
    commands.add_parser(
        "create",
        help="Deploy the committed production build as a matching app version and job.",
    )
    execute_parser = commands.add_parser("execute", help="Run the Cloud Run E2E job.")
    execute_scope = execute_parser.add_mutually_exclusive_group()
    execute_scope.add_argument("--suite", choices=("all", "full"))
    execute_scope.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="Run one existing E2E file/nodeid; repeat for additional targets.",
    )
    execute_parser.add_argument(
        "--no-import-results",
        action="store_true",
        help="Leave this execution in Cloud Storage without importing it locally.",
    )
    results_parser = commands.add_parser("results", help="Download and import job artifacts.")
    result_selector = results_parser.add_mutually_exclusive_group()
    result_selector.add_argument("--execution")
    result_selector.add_argument("--latest", action="store_true")
    results_parser.add_argument("--download-only", action="store_true")
    results_parser.add_argument(
        "--skip-report-archive",
        action="store_true",
        help="Download manifest, evidence, and JUnit XML without reports.tar.gz.",
    )
    import_parser = commands.add_parser(
        "import-results",
        help="Merge an already-downloaded result bundle into local evidence.",
    )
    import_parser.add_argument("--directory", required=True, type=Path)
    import_parser.add_argument("--execution")
    validate_parser = commands.add_parser(
        "validate-release-evidence",
        help="Validate hosted evidence for a release candidate or continuation.",
    )
    validate_parser.add_argument("--candidate", required=True)
    validate_parser.add_argument("--evidence", required=True)
    validate_parser.add_argument("--base", required=True)
    commands.add_parser("status", help="Show local and provider lifecycle state.")
    teardown_parser = commands.add_parser("teardown", help="Delete the ephemeral version and job.")
    teardown_parser.add_argument("--force", action="store_true")
    args = parser.parse_args(arguments)

    try:
        if args.action == "setup":
            payload = setup(args.github_repository)
            print(json.dumps(payload, indent=2, sort_keys=True))
            print(
                "Configure the GitHub environment variables documented in "
                "documentation/TESTING_HOSTED_E2E.md before dispatching CI."
            )
        elif args.action == "create":
            payload = create()
            print(f"Hosted E2E version ready: {payload['base_url']}")
        elif args.action == "execute":
            suite = args.suite or ("focused" if args.targets else "all")
            payload = execute(
                suite=suite,
                targets=args.targets or (),
                import_results=not args.no_import_results,
            )
            print(
                format_execute_summary(
                    payload,
                    imported=not args.no_import_results,
                )
            )
            return int(payload.get("exit_status") or 0)
        elif args.action == "import-results":
            payload = import_result_directory(
                args.directory,
                expected_execution=args.execution,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        elif args.action == "results":
            payload = results(
                execution=args.execution,
                latest=args.latest,
                merge=not args.download_only,
                include_report_archive=not args.skip_report_archive,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return int(payload.get("exit_status") or 0)
        elif args.action == "validate-release-evidence":
            payload = validate_release_evidence(
                args.candidate,
                args.evidence,
                base=args.base,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        elif args.action == "status":
            print(json.dumps(status(), indent=2, sort_keys=True))
        elif args.action == "teardown":
            payload = teardown(force=args.force)
            print(f"Hosted E2E version {payload['version']} was torn down.")
    except HostedE2EError as error:
        print(f"Hosted E2E command stopped: {error}")
        return 2
    except RuntimeError as error:
        print(f"Hosted E2E command failed: {error}")
        return 1
    return 0


__all__ = [
    "HostedE2EError",
    "create",
    "execute",
    "merge_remote_evidence",
    "require_clean_source",
    "results",
    "run_hosted_e2e_command",
    "setup",
    "status",
    "teardown",
    "validate_release_evidence",
]
