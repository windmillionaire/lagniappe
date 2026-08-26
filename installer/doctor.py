"""Read-only local and provider diagnostics for an existing installation."""

import hashlib
import json
import os
from pathlib import Path
import re

import yaml

from runner.context import REPOSITORY_ROOT, setup_command
from installer.summary import install_summary_lines


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


# @testable false
# @covered-by installer/doctor.py::run_doctor
# @reason private UTF-8 parser is exercised through the public read-only diagnostic
def _load_document(path):
    with path.open("r", encoding="utf-8", newline="") as document:
        if path.suffix == ".json":
            return json.load(document)
        return yaml.safe_load(document) or {}


# @testable false
# @covered-by installer/doctor.py::run_doctor
# @reason local checksum and permission collection is owned by the public diagnostic
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

    if source_checksum and manifest:
        if (
            manifest.get("schema") != 2
            or manifest.get("source")
            != {
                "path": GENERATION_SOURCE,
                "sha256": source_checksum,
            }
            or manifest.get("generation") != source_checksum
        ):
            issues.append(
                "generated files do not match the current constants generation"
            )

    if os.name != "nt":
        for relative in SECRET_FILES:
            path = root / relative
            if path.is_file() and path.stat().st_mode & 0o077:
                issues.append(f"{relative}: permissions are broader than owner-only")

    return documents, issues


# @testable false
# @covered-by installer/doctor.py::run_doctor
# @reason read-only command normalization is exercised through the public diagnostic
def _gcloud_value(runner, command):
    try:
        result = runner(command, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return str(result.stdout or "").strip() or None


# @testable false
# @covered-by installer/doctor.py::run_doctor
# @reason active identity collection is owned by the public diagnostic
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


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_doctor_reads_adc_identity_without_changing_it
# @matrix setup : adc doctor provider-identity read-only
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
        principal = (
            getattr(credentials, "service_account_email", None)
            or getattr(credentials, "signer_email", None)
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


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_default_doctor_provider_checker_targets_saved_project
# @matrix setup : doctor operator-permissions project-identity provider-apis provider-discovery
def _default_provider_checker(settings, project):
    from config import constants
    from installer.iam import inspect_operator_permissions
    from installer.recovery import verify_recovery_resources
    from installer.utils import run_gcloud_command

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
        "state": (
            "UNAVAILABLE"
            if any(missing_permissions.values())
            else "AVAILABLE"
        ),
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
    missing_apis = sorted(
        set(constants.REQUIRED_GOOGLE_CLOUD_APIS) - enabled_apis
    )
    report["required-apis"] = {
        "state": "ABSENT" if missing_apis else "AVAILABLE",
        "details": {"missing": missing_apis},
        "error": None,
    }
    return report


# @testable false
# @covered-by installer/doctor.py::run_doctor
# @reason identity drift comparison is exercised through the public diagnostic
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


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_doctor_reports_keyless_identity_drift
# @matrix setup : adc doctor keyless-config project-identity
def _keyless_identity_issues(settings, deploy):
    """Return local keyless identity and deployment attachment drift."""
    runtime_email = str(
        settings.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
    internal_caller_email = str(
        settings.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip().casefold()
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


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_doctor_reports_drift_without_writing
# @matrix setup : doctor drift independent-provider-check provider-identity read-only
def run_doctor(
    *,
    root=REPOSITORY_ROOT,
    gcloud_runner=None,
    adc_checker=None,
    provider_checker=None,
):
    """Inspect setup state and expected providers without repairing anything."""
    root = Path(root)
    documents, local_issues = _local_state(root)
    settings = documents.get("config/files/lagniappe_settings.yaml") or {}
    deploy = documents.get("lagniappe.yaml") or {}
    node = documents.get("package.json") or {}
    dev = documents.get("config/files/lagniappe_dev.yaml") or {}
    saved_gcloud = dev.get("gcloud_config") or {}
    local_issues.extend(_keyless_identity_issues(settings, deploy))
    issues = list(local_issues)

    print("=== Lagniappe setup doctor (read-only) ===")
    if local_issues:
        print("Local generated state: DRIFT")
        for issue in local_issues:
            print(f"- {issue}")
    else:
        print("Local generated state: OK")

    active = {}
    identity_issues = []
    if settings and saved_gcloud:
        if gcloud_runner is None:
            from installer.utils import run_gcloud_command

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
                and adc["principal"].casefold()
                != saved_gcloud["ACCOUNT"].casefold()
            ):
                identity_issues.append(
                    "ADC principal differs from the saved deployer"
                )
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
            "Active gcloud configuration: "
            f"{active.get('configuration') or '(unavailable)'}"
        )
        print(f"Active gcloud account: {active.get('account') or '(unavailable)'}")
        print(f"Active gcloud project: {active.get('project') or '(unavailable)'}")
        print(f"ADC principal: {adc.get('principal') or '(unavailable)'}")
        print(f"ADC project: {adc.get('project') or '(unavailable)'}")
        print(
            "ADC quota project: "
            f"{adc.get('quota_project') or '(unavailable)'}"
        )
        print(
            "Saved installer: "
            f"{settings.get('INSTALLER_EMAIL') or '(not configured)'}"
        )
        print(
            "Saved deployer: "
            f"{settings.get('DEPLOYER_EMAIL') or '(not configured)'}"
        )
        print(
            "Saved owner: "
            f"{settings.get('ADMIN_EMAIL') or '(not configured)'}"
        )
        if identity_issues:
            print("Identity state: DRIFT")
            for issue in identity_issues:
                print(f"- {issue}")
        else:
            print("Identity state: OK")
    else:
        identity_issues.append("saved setup identity is unavailable")
        issues.extend(identity_issues)
        print("Identity state: UNAVAILABLE")

    print("Expected target and provider resources:")
    for line in install_summary_lines(
        settings,
        deploy=deploy,
        node=node,
        gcloud_config=saved_gcloud,
    )[1:-5]:
        print(f"- {line}")

    project = settings.get("GOOGLE_CLOUD_PROJECT") or saved_gcloud.get("PROJECT")
    provider_report = {}
    provider_issues = []
    if settings and project and not identity_issues:
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
            "Provider state: DRIFT OR UNAVAILABLE"
            if provider_issues
            else "Provider state: OK"
        )
        for name in sorted(provider_report):
            print(f"- {name}: {provider_report[name].get('state')}")
    elif project:
        print("Provider state: DRIFT OR UNAVAILABLE")
    else:
        issues.append("target project is unavailable")
        print("Provider state: UNAVAILABLE")

    if issues:
        print(f"Repair command: {setup_command('repair')}")
        return 1
    print("Doctor result: OK")
    return 0
