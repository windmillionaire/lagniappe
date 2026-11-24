"""Read-only local and provider diagnostics for an existing installation."""

from collections.abc import Callable, Mapping
from subprocess import CalledProcessError, CompletedProcess
from typing import Protocol


from runner import presentation as ui
from runner.presentation import output as print

import hashlib
import json
import os
from pathlib import Path
import re

import yaml

from config import decode_app_settings
from runner.context import REPOSITORY_ROOT, setup_command
from installer.summary import expected_resource_lines


class _GcloudRunner(Protocol):
    def __call__(
        self, command: list[str], *, check: bool
    ) -> CompletedProcess[str] | CalledProcessError: ...


GENERATED_FILES = (
    "lagniappe.yaml",
    "config/files/lagniappe_settings.yaml",
    "config/files/lagniappe_dev.yaml",
    "package.json",
    "index.yaml",
    "lagniappe/web/static/manifest.json",
)
GENERATION_MANIFEST = "config/files/lagniappe_generation.json"
GENERATION_SOURCE = "config/constants.py"
SECRET_FILES = (
    "config/files/lagniappe_settings.yaml",
    "config/files/lagniappe_dev.yaml",
    GENERATION_MANIFEST,
)


def _load_document(path):
    with path.open("r", encoding="utf-8", newline="") as document:
        if path.suffix == ".json":
            return json.load(document)
        data = yaml.safe_load(document) or {}
        if path.name == "lagniappe_settings.yaml":
            return decode_app_settings(data)
        return data


def _local_state(root):
    issues = []
    documents = {}
    for relative in GENERATED_FILES:
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            issues.append(f"{relative}: missing or empty")
            continue
        try:
            documents[relative] = _load_document(path)
        except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError):
            issues.append(f"{relative}: unreadable")
            continue
    manifest_path = root / GENERATION_MANIFEST
    manifest = {}
    if not manifest_path.is_file() or manifest_path.stat().st_size == 0:
        issues.append(f"{GENERATION_MANIFEST}: missing or empty")
    else:
        try:
            manifest = _load_document(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            issues.append(f"{GENERATION_MANIFEST}: unreadable")

    source_path = root / GENERATION_SOURCE
    source_checksum = None
    if not source_path.is_file() or source_path.stat().st_size == 0:
        issues.append(f"{GENERATION_SOURCE}: missing or empty")
    else:
        source_content = re.sub(
            rb"(?m)^BUILD_ID\s*=.*(?:\r?\n|$)",
            b"",
            source_path.read_bytes(),
        )
        source_checksum = hashlib.sha256(source_content).hexdigest()

    if (
        source_checksum
        and manifest
        and (
            manifest.get("schema") != 2
            or manifest.get("source")
            != {
                "path": GENERATION_SOURCE,
                "sha256": source_checksum,
            }
            or manifest.get("generation") != source_checksum
        )
    ):
        issues.append(
            "generated files do not match the current constants generation"
        )

    if os.name != "nt":
        for relative in SECRET_FILES:
            path = root / relative
            if path.is_file() and path.stat().st_mode & 0o077:
                issues.append(f"{relative}: permissions are broader than owner-only")

    app_settings = documents.get("config/files/lagniappe_settings.yaml")
    if isinstance(app_settings, Mapping):
        from config.secrets import (
            SecretsBackendError,
            find_leaked_secret_keys,
            normalize_secrets_config,
            uses_secret_manager,
        )

        try:
            normalize_secrets_config(app_settings)
        except SecretsBackendError as error:
            issues.append(f"config/files/lagniappe_settings.yaml: {error}")
        else:
            if uses_secret_manager(app_settings):
                leaked = find_leaked_secret_keys(app_settings)
                if leaked:
                    issues.append(
                        "config/files/lagniappe_settings.yaml: secret keys present "
                        "on disk while SECRETS_BACKEND=secret_manager ("
                        + ", ".join(leaked)
                        + ")"
                    )

    return documents, issues


def _gcloud_value(runner, command):
    try:
        result = runner(command, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return str(result.stdout or "").strip() or None


def _active_cli_identity(runner):
    return {
        "configuration": _gcloud_value(
            runner,
            [
                "config",
                "configurations",
                "list",
                "--filter=is_active:true",
                "--format=value(name)",
            ],
        ),
        "account": _gcloud_value(
            runner,
            ["config", "get-value", "account"],
        ),
        "project": _gcloud_value(
            runner,
            ["config", "get-value", "project"],
        ),
    }


def _read_adc_identity(
    *,
    auth_default=None,
    request_factory=None,
    token_lookup=None,
):
    """Return a secret-free view of ADC without login, install, or file writes."""
    if auth_default is None:
        import google.auth

        auth_default = google.auth.default
    try:
        credentials, project = auth_default(
            scopes=[
                "https://www.googleapis.com/auth/cloud-platform",
                "https://www.googleapis.com/auth/userinfo.email",
                "openid",
            ]
        )
        principal = getattr(credentials, "service_account_email", None) or getattr(
            credentials, "signer_email", None
        )
        if not principal:
            if request_factory is None:
                from google.auth.transport.requests import Request

                request_factory = Request
            credentials.refresh(request_factory())
            if credentials.token:
                if token_lookup is None:
                    import requests

                    token_lookup = requests.get
                response = token_lookup(
                    "https://oauth2.googleapis.com/tokeninfo",
                    params={"access_token": credentials.token},
                    timeout=5,
                )
                if response.status_code == 200:
                    principal = response.json().get("email")
        return {
            "state": "success",
            "principal": principal,
            "project": project,
            "quota_project": getattr(credentials, "quota_project_id", None),
        }
    except Exception:
        return {
            "state": "unavailable",
            "principal": None,
            "project": None,
            "quota_project": None,
        }


def _default_provider_checker(settings, project):
    from config import constants
    from installer.iam import inspect_operator_permissions
    from installer.recovery import verify_recovery_resources
    from installer.commands import run_gcloud_command

    result = run_gcloud_command(
        ["projects", "describe", project, "--format=json"],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("target project is unavailable")
    try:
        project_details = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError("target project returned invalid data") from error
    report = verify_recovery_resources(
        settings,
        project,
        project_details=project_details,
    )
    missing_permissions = inspect_operator_permissions(project)
    report["operator-permissions"] = {
        "state": ("UNAVAILABLE" if any(missing_permissions.values()) else "AVAILABLE"),
        "details": missing_permissions,
        "error": None,
    }
    services = run_gcloud_command(
        [
            "services",
            "list",
            "--enabled",
            f"--project={project}",
            "--format=value(config.name)",
        ],
        check=False,
    )
    if services.returncode != 0:
        raise RuntimeError("required Google Cloud APIs are unavailable")
    enabled_apis = {
        value.strip()
        for value in str(services.stdout or "").splitlines()
        if value.strip()
    }
    from config.secrets import uses_secret_manager
    from installer.secrets import SECRET_MANAGER_API, probe_runtime_secrets_resource

    required_apis = set(constants.REQUIRED_GOOGLE_CLOUD_APIS)
    if uses_secret_manager(settings):
        required_apis.add(SECRET_MANAGER_API)
    missing_apis = sorted(required_apis - enabled_apis)
    report["required-apis"] = {
        "state": "ABSENT" if missing_apis else "AVAILABLE",
        "details": {"missing": missing_apis},
        "error": None,
    }
    if uses_secret_manager(settings):
        report["runtime-secrets"] = probe_runtime_secrets_resource(settings, project)
    from installer.monitoring import inspect_memory_alert

    report["app-engine-memory-alert"] = inspect_memory_alert(settings, project)
    from installer.mcp import inspect_deployment
    try:
        report["mcp-service"] = inspect_deployment(settings)
    except Exception:
        report["mcp-service"] = {"state": "UNAVAILABLE", "details": {}, "error": "MCP provider inspection failed."}
    return report


def _identity_issues(saved, active):
    expected = {
        "configuration": saved.get("NAME"),
        "account": saved.get("ACCOUNT"),
        "project": saved.get("PROJECT"),
    }
    issues = []
    for name, expected_value in expected.items():
        active_value = active.get(name)
        if not active_value:
            issues.append(f"active gcloud {name} is unavailable")
        elif expected_value and active_value != expected_value:
            issues.append(f"active gcloud {name} differs from saved setup state")
    return issues


def _keyless_identity_issues(settings, deploy):
    """Return local keyless identity and deployment attachment drift."""
    runtime_email = (
        str(settings.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or "").strip().casefold()
    )
    internal_caller_email = (
        str(settings.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL") or "")
        .strip()
        .casefold()
    )
    issues = []
    if settings.get("CONFIG_KIND") != "lagniappe-settings":
        issues.append("CONFIG_KIND is missing or unsupported")
    if str(settings.get("CONFIG_SCHEMA_VERSION") or "").strip() != "3":
        issues.append("CONFIG_SCHEMA_VERSION is missing or unsupported")
    if not runtime_email:
        issues.append("RUNTIME_SERVICE_ACCOUNT_EMAIL is not configured")
    if not internal_caller_email:
        issues.append("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL is not configured")
    if (
        runtime_email
        and internal_caller_email
        and runtime_email != internal_caller_email
    ):
        issues.append("internal caller differs from the runtime service account")
    project_id = str(settings.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if runtime_email and not runtime_email.endswith(
        f"@{project_id}.iam.gserviceaccount.com"
    ):
        issues.append("runtime service account belongs to a different project")
    attached_email = str(deploy.get("service_account") or "").strip().casefold()
    if runtime_email and attached_email != runtime_email:
        issues.append(
            "App Engine deployment service account differs from the runtime identity"
        )
    return issues


def run_doctor(
    *,
    root: str | Path = REPOSITORY_ROOT,
    gcloud_runner: _GcloudRunner | None = None,
    adc_checker: Callable[[], Mapping[str, str | None]] | None = None,
    provider_checker: Callable[
        [Mapping[str, object], str], Mapping[str, Mapping[str, object]]
    ]
    | None = None,
) -> int:
    """Inspect setup state and expected providers without repairing anything."""
    root = Path(root)
    documents, local_issues = _local_state(root)
    settings = documents.get("config/files/lagniappe_settings.yaml") or {}
    deploy = documents.get("lagniappe.yaml") or {}
    dev = documents.get("config/files/lagniappe_dev.yaml") or {}
    saved_gcloud = dev.get("gcloud_config") or {}
    local_issues.extend(_keyless_identity_issues(settings, deploy))
    issues = list(local_issues)

    print(ui.heading("Lagniappe setup doctor") + " " + ui.secondary("(read-only)"))
    if local_issues:
        print(ui.warning("Local generated state: drift detected"))
        for issue in local_issues:
            print(ui.info(f"  - {issue}"))
    else:
        print(ui.success("Local generated state: verified"))

    active = {}
    identity_issues = []
    if settings and saved_gcloud:
        if gcloud_runner is None:
            from installer.commands import run_gcloud_command

            gcloud_runner = run_gcloud_command
        active = _active_cli_identity(gcloud_runner)
        identity_issues.extend(_identity_issues(saved_gcloud, active))
        adc = (adc_checker or _read_adc_identity)()
        if adc.get("state") != "success":
            identity_issues.append("Application Default Credentials are unavailable")
        else:
            if not adc.get("principal"):
                identity_issues.append("ADC principal is unavailable")
            elif (
                saved_gcloud.get("ACCOUNT")
                and str(adc["principal"]).casefold() != saved_gcloud["ACCOUNT"].casefold()
            ):
                identity_issues.append("ADC principal differs from the saved deployer")
            if saved_gcloud.get("PROJECT") and (
                adc.get("project") != saved_gcloud["PROJECT"]
            ):
                identity_issues.append(
                    "ADC project differs from the saved target project"
                )
            if saved_gcloud.get("PROJECT") and (
                adc.get("quota_project") != saved_gcloud["PROJECT"]
            ):
                identity_issues.append(
                    "ADC quota project differs from the saved target project"
                )
        issues.extend(identity_issues)
        print(
            ui.value(
                "Active gcloud configuration",
                f"{active.get('configuration') or '(unavailable)'}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "Active gcloud account",
                f"{active.get('account') or '(unavailable)'}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "Active gcloud project",
                f"{active.get('project') or '(unavailable)'}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "ADC principal",
                f"{adc.get('principal') or '(unavailable)'}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "ADC project", f"{adc.get('project') or '(unavailable)'}", verbatim=True
            )
        )
        print(
            ui.value(
                "ADC quota project",
                f"{adc.get('quota_project') or '(unavailable)'}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "Saved installer",
                f"{settings.get('INSTALLER_EMAIL') or '(not configured)'}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "Saved deployer",
                f"{settings.get('DEPLOYER_EMAIL') or '(not configured)'}",
                verbatim=True,
            )
        )
        print(
            ui.value(
                "Saved owner",
                f"{settings.get('ADMIN_EMAIL') or '(not configured)'}",
                verbatim=True,
            )
        )
        if identity_issues:
            print(ui.error("Identity state: drift detected"))
            for issue in identity_issues:
                print(ui.info(f"  - {issue}"))
        else:
            print(ui.success("Identity state: verified"))
    else:
        identity_issues.append("saved setup identity is unavailable")
        issues.extend(identity_issues)
        print(ui.error("Identity state: unavailable"))

    if identity_issues:
        command = "auth" if settings and saved_gcloud else "repair"
        print(ui.value(
            "Authentication command" if command == "auth" else "Repair command",
            setup_command(command),
            action=True,
            verbatim=True,
            standalone=True,
        ))
        return 1

    print(ui.heading("Expected target and provider resources:"))
    for line in expected_resource_lines(
        settings,
        deploy=deploy,
        gcloud_config=saved_gcloud,
    ):
        label, _, value = line.partition(": ")
        print(ui.value(label, value, verbatim=True))

    project = settings.get("GOOGLE_CLOUD_PROJECT") or saved_gcloud.get("PROJECT")
    provider_report = {}
    provider_issues = []
    if settings and project:
        try:
            checker = provider_checker or _default_provider_checker
            provider_report = checker(settings, project)
        except Exception as error:
            provider_issues.append(
                f"provider drift or unavailable state ({type(error).__name__})"
            )
        else:
            unavailable = [
                name
                for name, observation in provider_report.items()
                if observation.get("state") != "AVAILABLE"
            ]
            if unavailable:
                provider_issues.append(
                    "provider resources not available: "
                    + ", ".join(sorted(unavailable))
                )

    issues.extend(provider_issues)
    if provider_report:
        print(
            ui.warning("Provider state: drift detected or unavailable")
            if provider_issues
            else ui.success("Provider state: verified")
        )
        for name in sorted(provider_report):
            state = provider_report[name].get("state")
            outcome = ui.styled(
                str(state).lower().replace("_", " "),
                "green" if state == "AVAILABLE" else "yellow",
            )
            print(ui.info(f"  {name}: {outcome}"))
    elif project:
        print(ui.warning("Provider state: drift detected or unavailable"))
    else:
        issues.append("target project is unavailable")
        print(ui.warning("Provider state: unavailable"))

    if issues:
        print(
            ui.value(
                "Repair command",
                setup_command("repair"),
                action=True,
                verbatim=True,
                standalone=True,
            )
        )
        return 1
    print(ui.success("Doctor result: verified"))
    return 0
