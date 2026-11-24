"""Installer provisioning, least-privilege IAM, migration, and probes for runtime secrets."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from subprocess import CalledProcessError, CompletedProcess
from typing import Protocol

from config import File, SettingsDraft
from config.secrets import (
    DEFAULT_RUNTIME_SECRET_NAME,
    DEFAULT_RUNTIME_SECRET_VERSION,
    SECRETS_BACKEND_SECRET_MANAGER,
    SecretsBackendError,
    find_leaked_secret_keys,
    normalize_secrets_config,
    uses_secret_manager,
)
from installer.commands import run_gcloud_command

SECRET_MANAGER_API = "secretmanager.googleapis.com"
SECRET_ACCESSOR_ROLE = "roles/secretmanager.secretAccessor"


class _GcloudRunner(Protocol):
    def __call__(
        self, command: list[str], *, check: bool
    ) -> CompletedProcess[str] | CalledProcessError: ...


def _run(
    runner: _GcloudRunner | None, command: list[str], *, check: bool = False
) -> CompletedProcess[str] | CalledProcessError:
    active = runner or run_gcloud_command
    return active(command, check=check)


def _policy_has_binding(policy: Mapping[str, object], role: str, member: str) -> bool:
    bindings = policy.get("bindings")
    if not isinstance(bindings, list):
        return False
    for binding in bindings:
        if not isinstance(binding, Mapping):
            continue
        if binding.get("role") != role:
            continue
        members = binding.get("members")
        if isinstance(members, list) and member in members:
            return True
    return False


def ensure_runtime_secrets_infrastructure(
    project_id: str,
    runtime_service_account: str,
    *,
    secret_name: str = DEFAULT_RUNTIME_SECRET_NAME,
    gcloud_runner: _GcloudRunner | None = None,
) -> dict[str, object]:
    """Enable Secret Manager API, create the runtime secret, and bind least-privilege IAM."""
    project_id = str(project_id or "").strip()
    runtime_email = str(runtime_service_account or "").strip().casefold()
    if not project_id or not runtime_email:
        raise SecretsBackendError(
            "Project ID and RUNTIME_SERVICE_ACCOUNT_EMAIL are required before "
            "provisioning runtime secrets."
        )
    normalize_secrets_config(
        {
            "SECRETS_BACKEND": SECRETS_BACKEND_SECRET_MANAGER,
            "SECRETS_SECRET_NAME": secret_name,
        }
    )

    enabled = _run(
        gcloud_runner,
        [
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            f"--filter=config.name={SECRET_MANAGER_API}",
            "--format=value(config.name)",
        ],
    )
    api_already_enabled = (
        enabled.returncode == 0
        and SECRET_MANAGER_API
        in {line.strip() for line in str(enabled.stdout or "").splitlines()}
    )
    if not api_already_enabled:
        enable_result = _run(
            gcloud_runner,
            [
                "services",
                "enable",
                SECRET_MANAGER_API,
                f"--project={project_id}",
            ],
        )
        if enable_result.returncode != 0:
            raise SecretsBackendError(
                f"Could not enable {SECRET_MANAGER_API} on project {project_id}."
            )

    describe = _run(
        gcloud_runner,
        [
            "secrets",
            "describe",
            secret_name,
            f"--project={project_id}",
            "--format=json",
        ],
    )
    created_secret = False
    if describe.returncode != 0:
        create = _run(
            gcloud_runner,
            [
                "secrets",
                "create",
                secret_name,
                "--replication-policy=automatic",
                f"--project={project_id}",
            ],
        )
        if create.returncode != 0:
            raise SecretsBackendError(
                f"Could not create Secret Manager secret {secret_name} in {project_id}."
            )
        created_secret = True

    member = f"serviceAccount:{runtime_email}"
    policy_result = _run(
        gcloud_runner,
        [
            "secrets",
            "get-iam-policy",
            secret_name,
            f"--project={project_id}",
            "--format=json",
        ],
    )
    has_binding = False
    if policy_result.returncode == 0:
        try:
            policy = json.loads(policy_result.stdout or "{}")
            if isinstance(policy, Mapping):
                has_binding = _policy_has_binding(policy, SECRET_ACCESSOR_ROLE, member)
        except json.JSONDecodeError:
            has_binding = False

    granted_iam = False
    if not has_binding:
        bind = _run(
            gcloud_runner,
            [
                "secrets",
                "add-iam-policy-binding",
                secret_name,
                f"--member={member}",
                f"--role={SECRET_ACCESSOR_ROLE}",
                f"--project={project_id}",
            ],
        )
        if bind.returncode != 0:
            raise SecretsBackendError(
                f"Could not grant {SECRET_ACCESSOR_ROLE} on {secret_name} to {runtime_email}."
            )
        granted_iam = True

    return {
        "api_enabled": True,
        "secret_name": secret_name,
        "created_secret": created_secret,
        "granted_iam": granted_iam,
        "runtime_service_account": runtime_email,
    }


def probe_runtime_secrets_resource(
    settings: Mapping[str, object],
    project_id: str,
    *,
    gcloud_runner: _GcloudRunner | None = None,
) -> dict[str, object]:
    """Read-only doctor/recovery probe for Secret Manager runtime secrets.

    Never reads or returns secret payload values.
    """
    if not uses_secret_manager(settings):
        return {
            "state": "AVAILABLE",
            "details": {"backend": "local_yaml"},
            "error": None,
        }
    normalized = normalize_secrets_config(settings)
    secret_name = normalized["SECRETS_SECRET_NAME"]
    expected_version = normalized["SECRETS_VERSION"]
    runtime_email = str(
        settings.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()

    describe = _run(
        gcloud_runner,
        [
            "secrets",
            "describe",
            secret_name,
            f"--project={project_id}",
            "--format=json",
        ],
    )
    if describe.returncode != 0:
        return {
            "state": "ABSENT",
            "details": {"secret": secret_name, "missing": ["secret"]},
            "error": f"Secret Manager secret '{secret_name}' is missing or unreadable.",
        }
    try:
        metadata = json.loads(describe.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "state": "UNAVAILABLE",
            "details": {"secret": secret_name},
            "error": f"Secret Manager metadata for '{secret_name}' was invalid JSON.",
        }

    aliases = metadata.get("versionAliases") if isinstance(metadata, Mapping) else {}
    if not isinstance(aliases, Mapping):
        aliases = {}
    missing: list[str] = []
    resolved_version = (
        str(aliases.get(DEFAULT_RUNTIME_SECRET_VERSION) or "")
        if expected_version == DEFAULT_RUNTIME_SECRET_VERSION
        else expected_version
    )
    if not resolved_version:
        missing.append("current-version-alias")

    policy_result = _run(
        gcloud_runner,
        [
            "secrets",
            "get-iam-policy",
            secret_name,
            f"--project={project_id}",
            "--format=json",
        ],
    )
    has_accessor = False
    if policy_result.returncode == 0 and runtime_email:
        try:
            policy = json.loads(policy_result.stdout or "{}")
            if isinstance(policy, Mapping):
                has_accessor = _policy_has_binding(
                    policy, SECRET_ACCESSOR_ROLE, f"serviceAccount:{runtime_email}"
                )
        except json.JSONDecodeError:
            has_accessor = False
    if not has_accessor:
        missing.append("runtime-secretAccessor-binding")

    if missing:
        return {
            "state": "ABSENT",
            "details": {
                "secret": secret_name,
                "version": resolved_version or None,
                "missing": missing,
            },
            "error": (
                f"Runtime secrets resource '{secret_name}' is incomplete: "
                + ", ".join(missing)
            ),
        }
    return {
        "state": "AVAILABLE",
        "details": {
            "backend": SECRETS_BACKEND_SECRET_MANAGER,
            "secret": secret_name,
            "version": resolved_version,
        },
        "error": None,
    }


def migrate_local_yaml_to_secret_manager(
    draft: SettingsDraft | None = None,
    *,
    secret_name: str = DEFAULT_RUNTIME_SECRET_NAME,
    gcloud_runner: _GcloudRunner | None = None,
    ensure_infra: Callable[..., dict[str, object]] | None = None,
) -> dict[str, object]:
    """Explicit opt-in migration from local_yaml to GCP Secret Manager."""
    active_draft = draft if draft is not None else SettingsDraft()
    project_id = str(active_draft.APP.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    runtime_email = str(
        active_draft.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip()
    if not project_id or not runtime_email:
        raise SecretsBackendError(
            "GOOGLE_CLOUD_PROJECT and RUNTIME_SERVICE_ACCOUNT_EMAIL must be "
            "configured before migrating to Secret Manager."
        )
    provision = ensure_infra or ensure_runtime_secrets_infrastructure
    infra = provision(
        project_id,
        runtime_email,
        secret_name=secret_name,
        gcloud_runner=gcloud_runner,
    )
    active_draft.APP["SECRETS_BACKEND"] = SECRETS_BACKEND_SECRET_MANAGER
    active_draft.APP["SECRETS_SECRET_NAME"] = secret_name
    active_draft.APP["SECRETS_VERSION"] = DEFAULT_RUNTIME_SECRET_VERSION
    active_draft.save(File.APP_SETTINGS_YAML)

    disk_settings = File.APP_SETTINGS_YAML.load()
    leaked = find_leaked_secret_keys(disk_settings)
    if leaked:
        raise SecretsBackendError(
            "Migration left secret keys on disk: " + ", ".join(leaked)
        )
    return {
        "backend": SECRETS_BACKEND_SECRET_MANAGER,
        "secret_name": secret_name,
        "project_id": project_id,
        "infrastructure": infra,
    }


def configure_secrets_migrate() -> int:
    """Interactive entry point for migrating local_yaml secrets and offering deploy."""
    from installer.deploy import deploy_to_app_engine
    from installer.verify import prepare_existing_installation
    from runner import presentation as ui
    from runner.console import format_prompt, wrap_text
    from runner.presentation import output as print, read_input as input

    prepare_existing_installation()
    result = migrate_local_yaml_to_secret_manager()
    print(
        ui.success(
            wrap_text(
                f"Migrated runtime secrets for {result['project_id']} to Secret Manager "
                f"({result['secret_name']}) and stripped them from lagniappe_settings.yaml."
            )
        )
    )
    print(
        ui.info(
            wrap_text(
                "The app must be redeployed so App Engine switches to reading runtime "
                "secrets from Secret Manager."
            )
        )
    )
    consent = input(format_prompt("Deploy the updated app now? [Y/n]: "))
    if consent.strip().casefold() != "n":
        deploy_to_app_engine(print_final_summary=False)
        print(ui.success(wrap_text("Secret Manager runtime configuration deployed.")))
    else:
        print(
            ui.warning(
                wrap_text(
                    "Deployment deferred. Run ./setup.sh update when ready to activate "
                    "Secret Manager on App Engine."
                )
            )
        )
    return 0
