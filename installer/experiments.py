"""Configure a dedicated experiments installation using normal setup owners."""

from runner import presentation as ui
from runner.presentation import output as print
from installer.errors import SetupError


# @testable true
# @tests tests_tooling/test_001l_setup_experiments.py::test_experiments_preset_preserves_existing_choices_and_rejects_conversion
# @matrix experiments : configuration
def configure(*, requested=False, first_install=False):
    from config import SETTINGS
    from config.experiments import normalize_experiments_config

    app = SETTINGS.APP
    if requested and not first_install and not app.get("EXPERIMENTS_ENABLED"):
        raise SetupError(
            "Use --experiments when creating a new installation; existing installations are not converted."
        )
    if not requested and not app.get("EXPERIMENTS_ENABLED"):
        return False
    if not app.get("EXPERIMENTS_ENABLED"):
        app.update(
            {
                "EXPERIMENTS_ENABLED": True,
                "EXPERIMENTS_PROJECT": app["GOOGLE_CLOUD_PROJECT"],
                "EXPERIMENTS_EXECUTION_ENABLED": True,
                "EXPERIMENTS_DIAGNOSTICS": "summary",
                "AGENT_ACCESS_ENABLED": True,
                "GOOGLE_SIGNIN_ENABLED": True,
                "AI_ENABLED": True,
                "EXTERNAL_AI_ENABLED": True,
            }
        )
        app.setdefault("MCP_NAME", f"{SETTINGS.GCLOUD_CONFIG['NAME']}-mcp")
    app.update(normalize_experiments_config(app))
    SETTINGS.save()
    print(
        ui.info(
            "Experiments installation: normal Google sign-in, an Administrator agent, MCP execution, and request measurements."
        )
    )
    print(ui.value("Target project", app["EXPERIMENTS_PROJECT"], verbatim=True))
    print(ui.value("Agent identity", app["AGENT_ACCESS_EMAIL"], verbatim=True))
    print(
        ui.info(
            "The agent access code is stored in the protected config/files/lagniappe_settings.yaml file."
        )
    )
    return True


# @testable true
# @tests tests_tooling/test_001l_setup_experiments.py::test_experiments_toolchain_builds_production_without_provisioning_test_resources
# @matrix experiments : toolchain
def prepare_toolchain():
    """Reuse local dependency setup without test buckets or a development build."""
    import sys
    from runner.context import NPM_CLI
    from installer.development import (
        _installed_node_version,
        node_version_supported,
        _run_command,
    )

    if not NPM_CLI or not node_version_supported(_installed_node_version()):
        raise SetupError(
            "Experiments require the Node.js version in .nvmrc and npm. Install them and rerun setup."
        )
    for label, command in (
        (
            "Installing Python development dependencies",
            [sys.executable, "-m", "pip", "install", "-r", "requirements-dev.txt"],
        ),
        (
            "Installing the pinned MCP environment manager",
            [
                sys.executable,
                "-m",
                "runner.uv_bootstrap",
                "install",
                "--non-interactive",
            ],
        ),
        ("Installing locked frontend dependencies", [NPM_CLI, "ci"]),
        (
            "Installing Playwright Chromium",
            [sys.executable, "-m", "playwright", "install", "chromium"],
        ),
    ):
        if not _run_command(label, command):
            raise SetupError(f"{label} failed; rerun setup to resume.")


# @testable true
# @tests tests_tooling/test_001l_setup_experiments.py::test_experiments_bootstrap_verification_requires_saved_accounts
# @matrix experiments : bootstrap
def verify_bootstrap(*, require_admin=False):
    """Start the normal app, then verify its persisted bootstrap outcome."""
    import requests
    from google.cloud import datastore
    from config import SETTINGS

    app = SETTINGS.APP
    if not app.get("EXPERIMENTS_ENABLED"):
        return
    origin = (
        f"https://{app['CUSTOM_DOMAIN']}"
        if app.get("CUSTOM_DOMAIN")
        else app["APP_URL"]
    )
    response = requests.get(
        f"{origin.rstrip('/')}/users/login", timeout=(10, 120), allow_redirects=False
    )
    if response.status_code != 200:
        raise SetupError(
            "Experiments app startup could not be verified. Inspect app logs and rerun setup update."
        )
    client = datastore.Client(project=app["EXPERIMENTS_PROJECT"])
    state = client.get(client.key("site", "experiments-bootstrap"))
    if not state or state.get("version") != 1:
        raise SetupError(
            "Experiments account bootstrap has not completed. Inspect app logs and rerun setup update."
        )
    for role, email in (
        ("owner", app["ADMIN_EMAIL"]),
        ("agent", app["AGENT_ACCESS_EMAIL"]),
    ):
        key = state.get(role)
        user = client.get(key) if key else None
        if not user or str(user.get("email", "")).casefold() != email.casefold():
            raise SetupError(f"Experiments {role} account could not be verified.")
        if role == "owner" and not user.get("owner"):
            raise SetupError("Experiments Owner role could not be verified.")
        if role == "agent" and require_admin and not user.get("admin"):
            raise SetupError(
                "Experiments agent Administrator role could not be verified."
            )
    print(ui.success("Experiments Owner and agent accounts are ready."))
    print(
        ui.value(
            "Agent browser login",
            f"{origin.rstrip('/')}/users/agent-login",
            verbatim=True,
        )
    )
