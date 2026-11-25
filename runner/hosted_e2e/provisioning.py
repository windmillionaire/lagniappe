"""Provision the persistent hosted E2E infrastructure and verify its setup receipt."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from config.constants import RUNTIME_BUCKET_ROLES, RUNTIME_PROJECT_ROLES

from .app_engine import ANCHOR_REVISION, _ensure_anchor, _test_bucket_names
from .preflight import _git
from .runtime import (
    HostedE2EError,
    INVOKER_ACCOUNT,
    RUNTIME_ACCOUNT,
    SETUP_PATH,
    STATE_ROOT,
    STATE_SCHEMA_VERSION,
    _activate,
    _deployer_member,
    _describe,
    _gcloud,
    _infrastructure,
    _json_result,
    _load_json,
    _validate_state_infrastructure,
    _write_json,
)


SETUP_CONTRACT_REVISION = 1
GITHUB_ENVIRONMENT = "hosted-e2e"
HOSTED_APIS = (
    "appengine.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com",
)
CLOUD_BUILD_IDENTITY_RETRY_DELAYS = (2, 4, 8, 16)


def _setup_contract_fingerprint():
    """Fingerprint stable cloud requirements that setup must reconcile."""
    contract = {
        "revision": SETUP_CONTRACT_REVISION,
        "hosted_apis": HOSTED_APIS,
        "runtime_project_roles": RUNTIME_PROJECT_ROLES,
        "runtime_bucket_roles": RUNTIME_BUCKET_ROLES,
        "anchor_revision": ANCHOR_REVISION,
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def _derive_github_repository():
    result = _git("config", "--get", "remote.origin.url", check=False)
    value = result.stdout.strip()
    match = re.search(r"github\.com(?::|/)([^/\s]+/[^/\s]+?)(?:\.git)?$", value)
    return match.group(1) if match else None


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
    workflow_prefix = f"{github_repository}/.github/workflows/hosted-e2e.yml@"
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


def setup(github_repository: str | None = None) -> dict[str, object]:
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

    if (
        _describe(
            [
                "artifacts",
                "repositories",
                "describe",
                infrastructure.artifact_repository,
                f"--location={infrastructure.region}",
                f"--project={infrastructure.project}",
            ]
        )
        is None
    ):
        _gcloud(
            "artifacts",
            "repositories",
            "create",
            infrastructure.artifact_repository,
            "--repository-format=docker",
            f"--location={infrastructure.region}",
            f"--project={infrastructure.project}",
        )
    cloud_build_member = (
        f"serviceAccount:{_cloud_build_service_account(infrastructure)}"
    )
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
        if (
            _describe(
                [
                    "secrets",
                    "describe",
                    secret_name,
                    f"--project={infrastructure.project}",
                ]
            )
            is None
        ):
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
        "setup_contract": _setup_contract_fingerprint(),
        "configured_at": datetime.now(UTC).isoformat(),
        "github_repository": github_repository,
        **asdict(infrastructure),
        "provider_resource": infrastructure.provider_resource,
    }
    _write_json(SETUP_PATH, payload)
    return payload


def _require_current_setup(infrastructure):
    """Require setup state that reflects the current stable cloud contract."""
    setup_state = _load_json(SETUP_PATH)
    if not setup_state or setup_state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise HostedE2EError("Run `run.py hosted-e2e setup` first.")
    if setup_state.get("setup_contract") != _setup_contract_fingerprint():
        raise HostedE2EError(
            "Hosted E2E setup is stale for the current APIs, IAM roles, or "
            "anchor contract; rerun `run.py hosted-e2e setup`."
        )
    _validate_state_infrastructure(setup_state, infrastructure)
    return setup_state
