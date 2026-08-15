from pathlib import Path

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
# @features setup
# @dimensions recovery failure-isolation
def _recovery_file_present(app_dir=None):
    """Detect the canonical recovery-file shape without importing config."""
    app_dir = Path(app_dir) if app_dir else REPOSITORY_ROOT
    config_dir = app_dir / "config" / "files"
    return (
        (config_dir / "lagniappe_settings.yaml").is_file()
        and not (config_dir / "lagniappe_dev.yaml").exists()
    )


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_default_install_characterization_starts_empty_and_reaches_all_boundaries
# @tests tests_tooling/test_001e_setup_orchestration.py::test_default_install_activates_ai_email_after_deploy_and_jobs
# @pair setup:prerequisites
# @pair setup:virtualenv
# @pair setup:main-install
def install():
    print("Welcome to Lagniappe Setup!")
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

    value = input(
        wrap_text(
            "This script will need to install certain Python packages if they "
            "are not already installed. The script will ask for confirmation "
            "before installing. Continue? [Y/n]: "
        )
    )
    if value.lower() == "n":
        print("Exiting installer.")
        raise SetupCancelled("Setup cancelled before dependency installation.")

    record_step("install setup dependencies")
    ensure_setup_dependencies()
    from config import SETTINGS, File
    from installer import FORMATTER

    f = FORMATTER.initialize()

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

    ai_email_config = None
    if getattr(SETTINGS, "RECOVERY_MODE", False):
        print(
            f.info(
                "Recovery preserved monitoring, Sentry, AI, Redis, domain, and "
                "other saved choices. Use the focused setup modes to reconfigure "
                "them explicitly."
            )
        )
    else:
        optional.setup_error_monitoring()
        optional.change_ai_model()
        record_step("configure AI email submissions")
        ai_email_config = ai_email.setup_ai_email()

    record_step("persist generated configuration")
    SETTINGS.save()

    deployed = False
    consent = input(f.info("Would you like to deploy the app now? [y/N]: "))
    if consent.lower() == "y":
        record_step("deploy application")
        utils.deploy_to_app_engine(print_final_summary=False)
        from installer.upgrade import _configure_deferred_job_recovery

        print(f"\n{f.info('Wrapping up installation...')}")
        if not _configure_deferred_job_recovery(f, gcloud):
            return 1
        if ai_email_config:
            record_step("activate AI email submissions")
            ai_email.activate_ai_email(ai_email_config)
        print(f"\n{f.success('Deployment complete!')}")
        deployed = True
    else:
        project = SETTINGS.GCLOUD_CONFIG["PROJECT"]
        print(f.success("You can deploy the application manually when ready."))
        print("Manual deployment steps:")
        print("1. Review the generated YAML files")
        print(
            "2. Run: "
            f"{format_command([GCLOUD_CLI, 'config', 'set', 'project', project])}"
        )
        print(
            "3. Run: "
            f"{format_command([GCLOUD_CLI, 'app', 'deploy', File.INDEX_YAML.value])}"
        )
        print(
            "4. Run: "
            f"{format_command([GCLOUD_CLI, 'app', 'deploy', File.APP_YAML.value])}"
        )
        print(f"After deployment, run: {setup_command('jobs')}")
        if ai_email_config:
            print(
                "Then activate the saved AI email configuration with: "
                f"{setup_command('ai-email')}"
            )

    print(f"\n{f.success('Setup complete!')}")

    from installer.summary import print_install_summary

    print_install_summary(
        SETTINGS.APP,
        deploy=SETTINGS.DEPLOY,
        node=SETTINGS.NODE,
        gcloud_config=SETTINGS.GCLOUD_CONFIG,
        deployed=deployed,
    )
    return 0
