"""Read-only provider discovery for canonical settings recovery."""

import json
from urllib.parse import urlparse

from config.locations import normalize_app_engine_location, normalize_resource_region
from config.storage import recovery_bucket_name, storage_bucket_names
from installer.utils import run_gcloud_command


ABSENT = "ABSENT"
AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason recovery-specific provider state error exercised through verification
class RecoveryResourceError(RuntimeError):
    """Raised when recovered provider resources cannot be safely verified."""


# @testable false
# @covered-by installer/recovery.py::_probe_gcloud_json
# @covered-by installer/recovery.py::_probe_ocr
# @reason provider error classification exercised through public recovery verification
def _provider_error_state(error):
    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    if callable(code):
        try:
            code = code()
        except Exception:
            code = None
    text = str(error or "").casefold()
    class_name = type(error).__name__.casefold()
    if status_code == 404 or code == 404 or "notfound" in class_name:
        return ABSENT
    if any(
        marker in text
        for marker in (
            "not_found",
            "not found",
            "does not exist",
            "could not be found",
        )
    ):
        return ABSENT
    return UNAVAILABLE


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_recovery_provider_states_distinguish_absent_from_unavailable
# @matrix setup : failure-isolation provider-discovery recovery
def _probe_gcloud_json(command):
    """Return a three-state observation for an explicitly targeted gcloud lookup."""
    result = run_gcloud_command(command, check=False)
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()
        return {
            "state": _provider_error_state(error),
            "details": None,
            "error": error or "provider lookup failed",
        }
    try:
        details = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "state": UNAVAILABLE,
            "details": None,
            "error": "provider returned invalid JSON",
        }
    if details in ({}, []):
        return {"state": ABSENT, "details": details, "error": None}
    return {"state": AVAILABLE, "details": details, "error": None}


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason command construction is checked through the public provider recovery report
def _probe_service_account(project_id, email):
    return _probe_gcloud_json(
        [
            "iam",
            "service-accounts",
            "describe",
            email,
            f"--project={project_id}",
            "--format=json",
        ]
    )


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason command construction is checked through the public provider recovery report
def _probe_enabled_api(project_id, service_name):
    result = run_gcloud_command(
        [
            "services",
            "list",
            "--enabled",
            f"--project={project_id}",
            f"--filter=config.name={service_name}",
            "--format=value(config.name)",
        ],
        check=False,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()
        return {
            "state": _provider_error_state(error),
            "details": None,
            "error": error or "provider lookup failed",
        }
    enabled_services = {
        value.strip()
        for value in result.stdout.splitlines()
        if value.strip()
    }
    if service_name not in enabled_services:
        return {
            "state": ABSENT,
            "details": {"name": service_name, "state": "DISABLED"},
            "error": None,
        }
    return {
        "state": AVAILABLE,
        "details": {"name": service_name, "state": "ENABLED"},
        "error": None,
    }


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason command construction is checked through the public provider recovery report
def _probe_service_account_policy(project_id, email):
    return _probe_gcloud_json(
        [
            "iam",
            "service-accounts",
            "get-iam-policy",
            email,
            f"--project={project_id}",
            "--format=json",
        ]
    )


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason command construction is checked through the public provider recovery report
def _probe_app_engine(project_id):
    return _probe_gcloud_json(
        ["app", "describe", f"--project={project_id}", "--format=json"]
    )


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason command construction is checked through the public provider recovery report
def _probe_runtime_version(project_id):
    return _probe_gcloud_json(
        [
            "app",
            "versions",
            "list",
            "--service=default",
            "--sort-by=~version.createTime",
            "--limit=1",
            f"--project={project_id}",
            "--format=json",
        ]
    )


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason command construction is checked through the public provider recovery report
def _probe_task_queue(project_id, region, queue_name):
    return _probe_gcloud_json(
        [
            "tasks",
            "queues",
            "describe",
            queue_name,
            f"--location={region}",
            f"--project={project_id}",
            "--format=json",
        ]
    )


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason command construction is checked through the public provider recovery report
def _probe_bucket(project_id, bucket_name):
    return _probe_gcloud_json(
        [
            "storage",
            "buckets",
            "describe",
            f"gs://{bucket_name}",
            f"--project={project_id}",
            "--format=json",
        ]
    )


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason provider client construction is checked through the public provider recovery report
def _probe_ocr(project_id, location, processor_name):
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai

        client = documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(
                api_endpoint=f"{location}-documentai.googleapis.com"
            )
        )
        processor = client.get_processor(name=processor_name)
        return {
            "state": AVAILABLE,
            "details": {
                "name": processor.name,
                "display_name": processor.display_name,
            },
            "error": None,
        }
    except Exception as error:
        return {
            "state": _provider_error_state(error),
            "details": None,
            "error": str(error),
        }


# @testable true
# @tests tests_tooling/test_001b_setup_providers.py::test_identity_platform_recovery_gets_live_config
# @matrix setup : identity-platform recovery
def _probe_identity_platform(project_id):
    try:
        import requests
        from installer.google_provider import (
            _get_access_token,
            _google_request_headers,
        )
        from installer.identity import (
            IDENTITY_PLATFORM_SUBTYPE,
            _email_password_enabled,
            get_identity_platform_config,
        )

        config = get_identity_platform_config(
            requests.Session(),
            project_id,
            _google_request_headers(_get_access_token(), project_id),
        )
        if config is None:
            return {"state": ABSENT, "details": None, "error": None}
        return {
            "state": AVAILABLE,
            "details": {
                "emailPasswordEnabled": _email_password_enabled(config),
                "subtype": config.get("subtype"),
                "standalone": config.get("subtype") == IDENTITY_PLATFORM_SUBTYPE,
            },
            "error": None,
        }
    except Exception as error:
        return {
            "state": UNAVAILABLE,
            "details": None,
            "error": str(error),
        }


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason Redis setup adapter is checked through the public provider recovery report
def _probe_redis(settings):
    from installer.redis import test_redis_connection

    if test_redis_connection(settings, exit_on_failure=False):
        return {"state": AVAILABLE, "details": None, "error": None}
    return {
        "state": UNAVAILABLE,
        "details": None,
        "error": "the recovered Redis endpoint could not be verified",
    }


# @testable false
# @covered-by installer/recovery.py::verify_recovery_resources
# @reason state enforcement is exercised through the public provider recovery report
def _require_observable(name, observation):
    if observation["state"] == UNAVAILABLE:
        raise RecoveryResourceError(
            f"Recovery stopped because {name} is unavailable: "
            f"{observation.get('error') or 'provider lookup failed'}"
        )
    return observation


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_recovery_provider_discovery_targets_only_recovered_project
# @tests tests_tooling/test_001e_setup_orchestration.py::test_recovery_reports_missing_signing_setup_as_repairable_drift
# @tests tests_tooling/test_001e_setup_orchestration.py::test_recovery_provider_mismatch_or_unavailable_stops_before_mutation
# @matrix setup : failure-isolation keyless-config project-identity project-number provider-discovery recovery repair
def verify_recovery_resources(settings, project_id, *, project_details=None):
    """Discover saved resource markers without mutating or replacing the snapshot."""
    runtime_email = settings["RUNTIME_SERVICE_ACCOUNT_EMAIL"]
    internal_caller_email = settings["INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"]
    if runtime_email.casefold() != internal_caller_email.casefold():
        raise RecoveryResourceError(
            "Recovered internal caller does not match the runtime service account."
        )
    app_engine_location = normalize_app_engine_location(
        settings["APP_ENGINE_LOCATION"]
    )
    resource_region = normalize_resource_region(settings["RESOURCE_REGION"])
    report = {}

    report["service-account"] = _require_observable(
        "runtime service account",
        _probe_service_account(project_id, runtime_email),
    )
    if report["service-account"]["state"] == ABSENT:
        raise RecoveryResourceError(
            "Recovery stopped because the saved runtime service account is absent."
        )
    service_account = report["service-account"]["details"] or {}
    discovered_email = (
        service_account.get("email")
        or service_account.get("name", "").rsplit("/", 1)[-1]
    )
    if discovered_email and discovered_email.casefold() != runtime_email.casefold():
        raise RecoveryResourceError(
            "Recovered runtime service-account email does not match the provider."
        )

    report["iam-credentials-api"] = _require_observable(
        "Service Account Credentials API",
        _probe_enabled_api(
            project_id,
            "iamcredentials.googleapis.com",
        ),
    )

    report["signing-iam"] = _require_observable(
        "runtime signing IAM policy",
        _probe_service_account_policy(project_id, runtime_email),
    )
    bindings = (report["signing-iam"].get("details") or {}).get(
        "bindings",
        [],
    )
    signing_members = {
        member
        for binding in bindings
        if binding.get("role") == "roles/iam.serviceAccountTokenCreator"
        and not (binding.get("condition") or {}).get("expression")
        for member in binding.get("members", [])
    }
    deployer_email = str(settings.get("DEPLOYER_EMAIL") or "").strip()
    deployer_type = (
        "serviceAccount"
        if deployer_email.casefold().endswith(".gserviceaccount.com")
        else "user"
    )
    expected_signers = {
        f"serviceAccount:{runtime_email}",
        f"{deployer_type}:{deployer_email}",
    }
    if not deployer_email or not expected_signers.issubset(signing_members):
        report["signing-iam"] = {
            **report["signing-iam"],
            "state": ABSENT,
            "missing_members": sorted(expected_signers - signing_members),
        }

    report["app-engine"] = _require_observable(
        "App Engine application",
        _probe_app_engine(project_id),
    )
    if report["app-engine"]["state"] == AVAILABLE:
        expected_host = urlparse(settings["APP_URL"]).hostname
        details = report["app-engine"]["details"] or {}
        provider_project = details.get("id") or details.get("projectId")
        if provider_project and provider_project != project_id:
            raise RecoveryResourceError(
                "Recovered App Engine application belongs to a different project."
            )
        provider_host = (
            details.get("defaultHostname")
            or details.get("default_hostname")
            or ""
        )
        if provider_host and provider_host.casefold() != expected_host.casefold():
            raise RecoveryResourceError(
                "Recovered App Engine hostname does not match the provider."
            )
        provider_location = normalize_app_engine_location(
            details.get("locationId") or details.get("location_id")
        )
        if provider_location and provider_location != app_engine_location:
            raise RecoveryResourceError(
                "Recovered App Engine location does not match the provider."
            )

    report["runtime-version"] = _require_observable(
        "App Engine runtime version",
        _probe_runtime_version(project_id),
    )
    if report["runtime-version"]["state"] == AVAILABLE:
        versions = report["runtime-version"]["details"]
        version = versions[0] if isinstance(versions, list) else versions
        provider_email = (
            version.get("serviceAccount")
            or version.get("serviceAccountEmail")
            or version.get("service_account")
        )
        if provider_email and provider_email.casefold() != runtime_email.casefold():
            raise RecoveryResourceError(
                "Recovered runtime service account does not match the deployed version."
            )

    queue_name = settings.get("TASK_QUEUE_NAME")
    if queue_name:
        report["task-queue"] = _require_observable(
            "Cloud Tasks queue",
            _probe_task_queue(
                project_id,
                resource_region,
                queue_name,
            ),
        )
        if report["task-queue"]["state"] == AVAILABLE:
            provider_name = (report["task-queue"]["details"] or {}).get("name", "")
            expected_name = (
                f"projects/{project_id}/locations/{resource_region}/"
                f"queues/{queue_name}"
            )
            if provider_name and provider_name != expected_name:
                raise RecoveryResourceError(
                    "Recovered Cloud Tasks queue does not match the provider."
                )

    processor_name = settings.get("OCR_PROCESSOR_ID")
    if processor_name:
        processor_parts = str(processor_name).split("/", 2)
        processor_project = (
            processor_parts[1]
            if len(processor_parts) == 3 and processor_parts[0] == "projects"
            else ""
        )
        provider_project_number = str(
            (project_details or {}).get("projectNumber") or ""
        ).strip()
        if processor_project not in {
            project_id,
            provider_project_number,
        }:
            raise RecoveryResourceError(
                "Recovered OCR processor project parent does not match the "
                "authenticated project ID or project number."
            )
        report["ocr-processor"] = _require_observable(
            "Document AI processor",
            _probe_ocr(project_id, settings["OCR_LOCATION"], processor_name),
        )
        if report["ocr-processor"]["state"] == AVAILABLE:
            details = report["ocr-processor"]["details"] or {}
            if details.get("name") != processor_name:
                raise RecoveryResourceError(
                    "Recovered OCR processor does not match the provider."
                )
            if (
                details.get("display_name")
                and details["display_name"] != settings.get("OCR_PROCESSOR")
            ):
                raise RecoveryResourceError(
                    "Recovered OCR processor name does not match the provider."
                )

    identity_config = settings.get("IDENTITY_PLATFORM_CONFIG")
    if identity_config:
        report["identity-platform"] = _require_observable(
            "Identity Platform",
            _probe_identity_platform(project_id),
        )
        details = report["identity-platform"].get("details") or {}
        if report["identity-platform"]["state"] == ABSENT:
            raise RecoveryResourceError(
                "Recovered Identity Platform configuration is absent."
            )
        if not details.get("standalone"):
            raise RecoveryResourceError(
                "Recovered authentication is not standalone Identity Platform."
            )
        if not details.get("emailPasswordEnabled"):
            raise RecoveryResourceError(
                "Recovered Identity Platform email/password authentication is "
                "disabled at the provider."
            )

    expected_project_number = str((project_details or {}).get("projectNumber") or "")
    if not expected_project_number:
        raise RecoveryResourceError(
            "Recovery stopped because the target project number is unavailable."
        )
    recovery_buckets = {
        **storage_bucket_names(settings),
        "recovery": recovery_bucket_name(settings),
    }
    for kind, bucket_name in recovery_buckets.items():
        key = f"{kind}-bucket"
        report[key] = _require_observable(
            f"{kind} Cloud Storage bucket",
            _probe_bucket(project_id, bucket_name),
        )
        if report[key]["state"] == AVAILABLE and expected_project_number:
            provider_number = str(
                (report[key]["details"] or {}).get("projectNumber") or ""
            )
            if provider_number and provider_number != expected_project_number:
                raise RecoveryResourceError(
                    f"Recovered {kind} bucket belongs to a different project."
                )

    if all(
        settings.get(key) not in (None, "")
        for key in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")
    ):
        report["redis"] = _require_observable(
            "Redis endpoint",
            _probe_redis(settings),
        )

    return report
