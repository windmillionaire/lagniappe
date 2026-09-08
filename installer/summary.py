"""Secret-safe setup summaries shared by install and diagnostics."""

import hashlib
import json
from runner.context import setup_command
from runner.console import cell_width, format_value, terminal_width, wrap_text


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
def _install_line(label, value, *, verbatim=False, standalone=False):
    return label, _value(value), verbatim and bool(value), standalone


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
    from config.ai_settings import normalize_ai_features
    from installer.mcp import requested
    features = normalize_ai_features(settings)
    lines.append(f"AI features: {'enabled' if features['AI_ENABLED'] else 'disabled'}")
    lines.append(f"External AI (MCP and API/skill): {'enabled' if features['EXTERNAL_AI_ENABLED'] else 'disabled'}")
    if requested(settings):
        lines.extend([
            f"MCP URL: {_value(settings.get('MCP_RESOURCE'))}",
            f"MCP desired version: {_value(settings.get('MCP_VERSION'))}",
            f"MCP runtime account: {_value(settings.get('MCP_SERVICE_ACCOUNT'))}",
            f"MCP build account: lagniappe-mcp-build@{project}.iam.gserviceaccount.com",
            f"MCP build bucket: {project}-mcp-builds",
        ])
    for kind, name in _bucket_names(settings).items():
        lines.append(f"{kind.title()} bucket: {name}")
    return lines


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_redacted_install_summary_is_allowlisted
# @tests tests_tooling/test_001k_setup_console.py::test_install_summary_is_responsive
# @matrix setup : operator-summary secret-redaction
def install_summary_lines(
    settings,
    *,
    deploy=None,
    node=None,
    gcloud_config=None,
    deployed=False,
    width=None,
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
        "Installation summary",
        _install_line("Application", settings.get("APP_NAME")),
        _install_line("Application URL", app_url, verbatim=True),
        _install_line(
            "Lagniappe version",
            settings.get("VERSION") or node.get("version"),
        ),
        _install_line("Target project", project, verbatim=True),
        _install_line("gcloud configuration", gcloud_config.get("NAME"), verbatim=True),
    ]
    from config.ai_settings import normalize_ai_features
    from installer.mcp import requested
    features = normalize_ai_features(settings)
    lines.append(_install_line("AI features", "enabled" if features["AI_ENABLED"] else "disabled"))
    lines.append(_install_line("External AI (MCP and API/skill)", "enabled" if features["EXTERNAL_AI_ENABLED"] else "disabled"))
    if requested(settings):
        lines.append(
            _install_line(
                "MCP server", settings.get("MCP_RESOURCE") or "selected", verbatim=True
            )
        )
        if not settings.get("MCP_RESOURCE"):
            lines.append(
                _install_line(
                    "Finish MCP setup",
                    setup_command("mcp"),
                    verbatim=True,
                    standalone=True,
                )
            )
        lines.append(_install_line("MCP desired version", settings.get("MCP_VERSION") or "pending"))
    if (
        installer
        and deployer
        and str(installer).strip().casefold() == str(deployer).strip().casefold()
    ):
        lines.append(_install_line("Installer / deployer", installer, verbatim=True))
    else:
        lines.extend(
            [
                _install_line("Installer", installer, verbatim=True),
                _install_line("Deployer", deployer, verbatim=True),
            ]
        )
    lines.extend(
        [
            _install_line(
                "Application Owner", settings.get("ADMIN_EMAIL"), verbatim=True
            ),
            _install_line(
                "Temporary Administrator",
                settings.get("BOOTSTRAP_ADMIN_EMAIL"),
                verbatim=True,
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
            _install_line(
                "Health check", setup_command("doctor"), verbatim=True, standalone=True
            ),
            _install_line(
                "Repair if needed",
                setup_command("repair"),
                verbatim=True,
                standalone=True,
            ),
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
                    f"After Owner review:\n{setup_command('handoff')}",
                    verbatim=True,
                    standalone=True,
                )
            )
        lines.append(
            _install_line(
                "Open this installation", app_url, verbatim=True, standalone=True
            )
        )
    else:
        lines.append(
            _install_line(
                "After manual deployment",
                setup_command("jobs"),
                verbatim=True,
                standalone=True,
            )
        )
    width = terminal_width(width)
    column = max(cell_width(row[0]) + 3 for row in lines if isinstance(row, tuple))
    rendered = []
    for row in lines:
        if isinstance(row, str):
            text = wrap_text(row, width)
        else:
            label, value, verbatim, standalone = row
            text = format_value(
                label,
                value,
                width=width,
                column=column,
                verbatim=verbatim,
                standalone=standalone or width - column < 20,
            )
        rendered.extend(text.split("\n"))
    return rendered


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
    width=None,
):
    """Print the allowlisted final install summary."""
    print()
    for line in install_summary_lines(
        settings,
        deploy=deploy,
        node=node,
        gcloud_config=gcloud_config,
        deployed=deployed,
        width=width,
    ):
        print(line)
