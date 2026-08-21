"""Secret-safe setup summaries shared by install and diagnostics."""

import hashlib
import json
import platform
import sys

from runner.context import setup_command


# @testable false
# @covered-by installer/summary.py::install_summary_lines
# @reason private parsing adapter is exercised through the public summary allowlist
def _mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# @testable false
# @covered-by installer/summary.py::install_summary_lines
# @reason private display adapter is exercised through the public summary allowlist
def _value(value):
    value = str(value or "").strip()
    return value or "(not configured)"


# @testable false
# @covered-by installer/summary.py::install_summary_lines
# @reason private safe-name derivation is exercised through the public summary allowlist
def _bucket_names(settings):
    secret = settings.get("GIBBERISH")
    if not secret:
        return {}
    digest = hashlib.sha256(str(secret).encode("utf-8")).hexdigest()
    prefix = str(settings.get("PREFIX") or "")
    names = {
        kind: f"{prefix}{kind}-{digest}"[: len(prefix) + 32].lower()
        for kind in ("history", "private", "public", "export")
    }
    names["recovery"] = (
        f"{prefix}recovery-{digest}"[: len(prefix) + 32].lower()
    )
    return names


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_redacted_install_summary_is_allowlisted
# @features setup
# @dimensions operator-summary secret-redaction
def install_summary_lines(
    settings,
    *,
    deploy=None,
    node=None,
    gcloud_config=None,
    deployed=False,
):
    """Return an allowlisted install summary without serializing settings."""
    settings = settings or {}
    deploy = deploy or {}
    node = node or {}
    gcloud_config = gcloud_config or {}
    identity = _mapping(settings.get("IDENTITY_PLATFORM_CONFIG"))
    project = (
        settings.get("GOOGLE_CLOUD_PROJECT")
        or gcloud_config.get("PROJECT")
    )
    runtime_email = settings.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
    internal_caller_email = settings.get(
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL"
    )
    app_url = (
        f"https://{settings['CUSTOM_DOMAIN']}"
        if settings.get("CUSTOM_DOMAIN")
        else settings.get("APP_URL")
    )
    redis_endpoint = ""
    if settings.get("REDIS_HOST"):
        redis_endpoint = str(settings["REDIS_HOST"])
        if settings.get("REDIS_PORT"):
            redis_endpoint += f":{settings['REDIS_PORT']}"

    lines = [
        "=== Final install summary (secrets omitted) ===",
        f"Application: {_value(settings.get('APP_NAME'))}",
        f"Application URL: {_value(app_url)}",
        f"Target project: {_value(project)}",
        (
            "Active gcloud configuration: "
            f"{_value(gcloud_config.get('NAME'))}"
        ),
        f"Installer: {_value(settings.get('INSTALLER_EMAIL'))}",
        (
            "Deployer: "
            f"{_value(settings.get('DEPLOYER_EMAIL') or gcloud_config.get('ACCOUNT'))}"
        ),
        f"Application owner: {_value(settings.get('ADMIN_EMAIL'))}",
        (
            "Temporary application Administrator: "
            f"{_value(settings.get('BOOTSTRAP_ADMIN_EMAIL'))}"
        ),
        f"Runtime service account: {_value(runtime_email)}",
        f"Internal caller service account: {_value(internal_caller_email)}",
        f"Signed URL account: {_value(runtime_email)}",
        "Signed URL API: iamcredentials.googleapis.com",
        f"App Engine location: {_value(settings.get('APP_ENGINE_LOCATION'))}",
        f"Regional resources: {_value(settings.get('RESOURCE_REGION'))}",
        f"OCR location: {_value(settings.get('OCR_LOCATION'))}",
        f"Task queue: {_value(settings.get('TASK_QUEUE_NAME'))}",
        f"OCR processor: {_value(settings.get('OCR_PROCESSOR_ID'))}",
        (
            "Identity Platform project: "
            f"{_value(identity.get('projectId'))}"
        ),
        (
            "Google sign-in: "
            f"{'enabled' if settings.get('GOOGLE_SIGNIN_ENABLED', True) else 'disabled'}"
        ),
        f"Redis endpoint: {_value(redis_endpoint)}",
    ]
    for kind, name in _bucket_names(settings).items():
        lines.append(f"{kind.title()} bucket: {name}")
    lines.extend(
        [
            (
                "Lagniappe version: "
                f"{_value(settings.get('VERSION') or node.get('version'))}"
            ),
            f"App Engine runtime: {_value(deploy.get('runtime'))}",
            (
                "Installer Python: "
                f"{platform.python_implementation()} "
                f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            ),
            f"Deployment completed: {'yes' if deployed else 'no'}",
            f"Optional health check: {setup_command('doctor')}",
            f"Repair if needed: {setup_command('repair')}",
        ]
    )
    if deployed:
        lines.append(
            "Lagniappe has been installed successfully. "
            f"Log in at {_value(app_url)}"
        )
    else:
        lines.append(
            f"After manual deployment: {setup_command('jobs')}"
        )
    return lines


# @testable false
# @covered-by installer/summary.py::install_summary_lines
# @reason console adapter delegates all output selection to the tested allowlist
def print_install_summary(
    settings,
    *,
    deploy=None,
    node=None,
    gcloud_config=None,
    deployed=False,
):
    """Print the allowlisted final install summary."""
    print()
    for line in install_summary_lines(
        settings,
        deploy=deploy,
        node=node,
        gcloud_config=gcloud_config,
        deployed=deployed,
    ):
        print(line)
