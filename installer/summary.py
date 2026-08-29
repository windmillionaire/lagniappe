"""Secret-safe setup summaries shared by install and diagnostics."""

import hashlib
import json
from runner.context import setup_command


# @testable false
# @covered-by installer/summary.py::expected_resource_lines
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
# @reason private boolean display adapter is exercised through the public summary allowlist
def _enabled(value, *, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "enabled"}


# @testable false
# @covered-by installer/summary.py::install_summary_lines
# @reason private aligned display adapter is exercised through the public summary allowlist
def _install_line(label, value):
    return f"{label + ':':<27}{_value(value)}"


# @testable false
# @covered-by installer/summary.py::expected_resource_lines
# @reason private safe-name derivation is exercised through the public summary allowlist
def _bucket_names(settings):
    secret = settings.get("GIBBERISH")
    if not secret:
        return {}
    digest = hashlib.sha256(str(secret).encode("utf-8")).hexdigest()
    prefix = str(settings.get("PREFIX") or "")
    names = {
        kind: f"{prefix}{kind}-{digest}"[: len(prefix) + 32].lower()
        for kind in ("history", "private", "public")
    }
    names["recovery"] = (
        f"{prefix}recovery-{digest}"[: len(prefix) + 32].lower()
    )
    return names


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_expected_resource_summary_is_allowlisted
# @matrix doctor setup : operator-summary provider-resources secret-redaction
def expected_resource_lines(
    settings,
    *,
    deploy=None,
    gcloud_config=None,
):
    """Return the detailed allowlisted provider inventory used by doctor."""
    settings = settings or {}
    deploy = deploy or {}
    gcloud_config = gcloud_config or {}
    identity = _mapping(settings.get("IDENTITY_PLATFORM_CONFIG"))
    project = settings.get("GOOGLE_CLOUD_PROJECT") or gcloud_config.get("PROJECT")
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
        f"Application: {_value(settings.get('APP_NAME'))}",
        f"Application URL: {_value(app_url)}",
        f"Target project: {_value(project)}",
        f"Runtime service account: {_value(runtime_email)}",
        f"Internal caller service account: {_value(internal_caller_email)}",
        f"Signed URL account: {_value(runtime_email)}",
        "Signed URL API: iamcredentials.googleapis.com",
        f"App Engine location: {_value(settings.get('APP_ENGINE_LOCATION'))}",
        f"Regional resources: {_value(settings.get('RESOURCE_REGION'))}",
        f"OCR location: {_value(settings.get('OCR_LOCATION'))}",
        f"Task queue: {_value(settings.get('TASK_QUEUE_NAME'))}",
        f"OCR processor: {_value(settings.get('OCR_PROCESSOR_ID'))}",
        f"Identity Platform project: {_value(identity.get('projectId'))}",
        (
            "Google sign-in: "
            f"{'enabled' if _enabled(settings.get('GOOGLE_SIGNIN_ENABLED'), default=True) else 'disabled'}"
        ),
        f"Redis endpoint: {_value(redis_endpoint)}",
        f"App Engine runtime: {_value(deploy.get('runtime'))}",
    ]
    for kind, name in _bucket_names(settings).items():
        lines.append(f"{kind.title()} bucket: {name}")
    return lines


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_redacted_install_summary_is_allowlisted
# @matrix setup : operator-summary secret-redaction
def install_summary_lines(
    settings,
    *,
    deploy=None,
    node=None,
    gcloud_config=None,
    deployed=False,
):
    """Return a compact, decision-focused successful-install handoff."""
    settings = settings or {}
    node = node or {}
    gcloud_config = gcloud_config or {}
    project = settings.get("GOOGLE_CLOUD_PROJECT") or gcloud_config.get("PROJECT")
    installer = settings.get("INSTALLER_EMAIL")
    deployer = settings.get("DEPLOYER_EMAIL") or gcloud_config.get("ACCOUNT")
    app_url = (
        f"https://{settings['CUSTOM_DOMAIN']}"
        if settings.get("CUSTOM_DOMAIN")
        else settings.get("APP_URL")
    )
    google_signin = "enabled" if _enabled(
        settings.get("GOOGLE_SIGNIN_ENABLED"), default=True
    ) else "disabled"
    error_monitoring = "enabled" if _enabled(
        settings.get("CAPTURE_ERRORS")
    ) else "disabled"
    ai_observability = "enabled" if _enabled(
        settings.get("AI_OBSERVABILITY")
    ) else "disabled"
    redis_state = "not configured"
    if settings.get("REDIS_HOST"):
        redis_tls = "enabled" if _enabled(settings.get("REDIS_TLS")) else "disabled"
        redis_state = f"configured; TLS {redis_tls}"

    lines = [
        "=== Final install summary (secrets omitted) ===",
        _install_line("Application", settings.get("APP_NAME")),
        _install_line("Application URL", app_url),
        _install_line(
            "Lagniappe version",
            settings.get("VERSION") or node.get("version"),
        ),
        _install_line("Target project", project),
        _install_line("gcloud configuration", gcloud_config.get("NAME")),
    ]
    if (
        installer
        and deployer
        and str(installer).strip().casefold() == str(deployer).strip().casefold()
    ):
        lines.append(_install_line("Installer / deployer", installer))
    else:
        lines.extend(
            [
                _install_line("Installer", installer),
                _install_line("Deployer", deployer),
            ]
        )
    lines.extend(
        [
            _install_line("Application Owner", settings.get("ADMIN_EMAIL")),
            _install_line(
                "Temporary Administrator",
                settings.get("BOOTSTRAP_ADMIN_EMAIL"),
            ),
            _install_line(
                "App Engine location",
                settings.get("APP_ENGINE_LOCATION"),
            ),
            _install_line("Regional resources", settings.get("RESOURCE_REGION")),
            _install_line("OCR location", settings.get("OCR_LOCATION")),
            _install_line("Google sign-in", google_signin),
            _install_line("Redis", redis_state),
            _install_line("Error monitoring", error_monitoring),
            _install_line("AI observability", ai_observability),
            _install_line("AI model", settings.get("AI_MODEL")),
            _install_line("AI utility model", settings.get("AI_UTILITY_MODEL")),
            _install_line("AI image model", settings.get("AI_IMAGE_MODEL")),
            _install_line("Deployment completed", "yes" if deployed else "no"),
            _install_line("Health check", setup_command("doctor")),
            _install_line("Repair if needed", setup_command("repair")),
        ]
    )
    if deployed:
        if (
            installer
            and settings.get("ADMIN_EMAIL")
            and str(installer).strip().casefold()
            != str(settings["ADMIN_EMAIL"]).strip().casefold()
        ):
            lines.append(
                _install_line(
                    "Installer handoff",
                    f"{setup_command('handoff')} after Owner review",
                )
            )
        lines.append(_install_line("Open this installation", app_url))
    else:
        lines.append(f"After manual deployment: {setup_command('jobs')}")
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
