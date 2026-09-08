from runner import presentation as ui
from runner.presentation import output as print, read_input as input
from pathlib import Path

from runner.console import format_prompt
from runner.context import (
    GCLOUD_CLI,
    REPOSITORY_ROOT,
    format_command,
    setup_command,
)
from installer import wrap_text
from installer.package_install import ensure_pip_is_available, ensure_setup_dependencies
from installer.errors import SetupCancelled
from installer.state import record_step


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_recovery_is_announced_before_dependency_or_provider_mutation
# @matrix setup : failure-isolation recovery
def _recovery_file_present(app_dir=None):
    """Detect the canonical recovery-file shape without importing config."""
    app_dir = Path(app_dir) if app_dir else REPOSITORY_ROOT
    config_dir = app_dir / "config" / "files"
    return (config_dir / "lagniappe_settings.yaml").is_file() and not (
        config_dir / "lagniappe_dev.yaml"
    ).exists()


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_default_install_characterization_starts_empty_and_reaches_all_boundaries
# @tests tests_tooling/test_001e_setup_orchestration.py::test_default_install_only_prints_manual_deployment_steps_when_declined
# @tests tests_tooling/test_001e_setup_orchestration.py::test_default_install_activates_ai_email_after_deploy_and_jobs
# @matrix setup : explicit-project main-install manual-deploy prerequisites virtualenv
def install():
    print(ui.heading(wrap_text("Welcome to Lagniappe setup")))
    if _recovery_file_present():
        print(
            wrap_text(
                "Recovery mode detected from "
                "config/files/lagniappe_settings.yaml. The recovered project "
                "will be authenticated and verified before provider resources "
                "or generated configuration are changed."
            )
        )

    from installer.utils import check_gcloud_cli

    ensure_pip_is_available()
    record_step("validate gcloud CLI")
    check_gcloud_cli()

    print(wrap_text("Setup will ask before installing any missing Python packages."))
    value = input(format_prompt("Continue? [Y/n]: "))
    if value.lower() == "n":
        print(ui.status(wrap_text("Exiting installer.")))
        raise SetupCancelled("Setup cancelled before dependency installation.")

    record_step("install setup dependencies")
    ensure_setup_dependencies()
    from config import SETTINGS, File
    from installer import FORMATTER

    f = FORMATTER.initialize()
    first_install = not SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT") and not SETTINGS.APP.get("APP_URL")

    from installer.create_config import set_application_defaults

    record_step("initialize application settings")
    set_application_defaults()

    from installer import (
        admin,
        ai_email,
        auth_email,
        gcloud,
        identity,
        optional,
        redis,
        utils,
    )

    steps = (
        ("enable Google Cloud APIs", gcloud.enable_gcloud_apis),
        ("reconcile App Engine", gcloud.setup_app_engine),
        ("reconcile storage buckets", gcloud.configure_storage_buckets),
        ("reconcile task queue", gcloud.create_task_queue),
        ("reconcile database data protection", gcloud.configure_data_protection),
        ("reconcile OCR processor", gcloud.create_ocr_processor),
        ("configure authentication email", auth_email.setup_auth_email),
        (
            "reconcile standalone Identity Platform",
            identity.setup_identity_platform,
        ),
        (
            "configure administrator and Google identity provider",
            admin.setup_admin_and_oauth,
        ),
        ("configure Redis", redis.setup_redis),
    )
    for step_name, operation in steps:
        record_step(step_name)
        operation()

    print(
        f.warning(
            wrap_text(
                "Deployment memory note: every Gunicorn worker adds application "
                "memory use; Lagniappe limits F2 and B2 to three workers."
            )
        )
    )

    ai_email_config = None
    if getattr(SETTINGS, "RECOVERY_MODE", False):
        print(
            f.info(
                wrap_text(
                    "Recovery preserved monitoring, Sentry, AI, Redis, domain, and "
                    "other saved choices. Use the focused setup modes to reconfigure "
                    "them explicitly."
                )
            )
        )
    else:
        optional.setup_error_monitoring()
        if optional.configure_ai_features():
            record_step("configure AI email submissions")
            ai_email_config = ai_email.setup_ai_email()

    record_step("persist generated configuration")
    SETTINGS.save()

    deployed = False
    consent = input(
        format_prompt("Would you like to deploy the app now? [y/N]: ")
    )
    if consent.lower() == "y":
        record_step("deploy application")
        utils.deploy_to_app_engine(
            print_final_summary=False,
            first_install=first_install and not getattr(SETTINGS, "RECOVERY_MODE", False),
        )
        from installer.upgrade import _configure_deferred_job_recovery

        if not _configure_deferred_job_recovery(f, gcloud):
            return 1
        if ai_email_config:
            record_step("activate AI email submissions")
            ai_email.activate_ai_email(ai_email_config)
        deployed = True
    else:
        project = SETTINGS.GCLOUD_CONFIG["PROJECT"]
        print(
            ui.info(wrap_text("You can deploy the application manually when ready."))
        )
        print(wrap_text(ui.heading("Manual deployment steps:")))
        print(wrap_text((f"{ui.literal('1.')} Review the generated YAML files")))
        print(
            ui.value(
                (f"{ui.literal('2.')} Select the project"),
                format_command([GCLOUD_CLI, "config", "set", "project", project]),
                verbatim=True,
                standalone=True,
                action=True,
            )
        )
        index_command = [
            GCLOUD_CLI,
            "app",
            "deploy",
            File.INDEX_YAML.value,
            "--project",
            project,
        ]
        app_command = [
            GCLOUD_CLI,
            "app",
            "deploy",
            File.APP_YAML.value,
            "--project",
            project,
        ]
        print(
            ui.value(
                (f"{ui.literal('3.')} Deploy indexes"),
                format_command(index_command),
                verbatim=True,
                standalone=True,
                action=True,
            )
        )
        print(
            ui.value(
                (f"{ui.literal('4.')} Deploy the application"),
                format_command(app_command),
                verbatim=True,
                standalone=True,
                action=True,
            )
        )
        print(
            ui.value(
                "After deployment, run",
                setup_command("jobs"),
                verbatim=True,
                standalone=True,
                action=True,
            )
        )
        print(
            ui.value(
                "Then reconcile memory monitoring",
                setup_command("monitoring"),
                verbatim=True,
                standalone=True,
                action=True,
            )
        )
        from installer.mcp import requested
        if requested(SETTINGS.APP):
            print(
                ui.value(
                    "Then publish MCP and its app configuration",
                    setup_command("mcp"),
                    verbatim=True,
                    standalone=True,
                    action=True,
                )
            )
        if ai_email_config:
            print(
                ui.value(
                    "Then activate the saved AI email configuration",
                    setup_command("ai-email"),
                    verbatim=True,
                    standalone=True,
                    action=True,
                )
            )

    print(wrap_text(f"\n{f.success('Setup complete')}"))

    from installer.summary import print_install_summary

    print_install_summary(
        SETTINGS.APP,
        deploy=SETTINGS.DEPLOY,
        node=SETTINGS.NODE,
        gcloud_config=SETTINGS.GCLOUD_CONFIG,
        deployed=deployed,
    )
    return 0
