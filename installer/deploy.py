"""Installer deployment workflow and post-deployment completion."""

from runner import presentation as ui
from runner.presentation import output as print
from runner.console import wrap_text


# @testable false
# @covered-by installer/deploy.py::deploy_to_app_engine
# @reason console-only installation summary
def print_summary():
    from config import SETTINGS
    from installer.summary import print_install_summary

    print_install_summary(
        SETTINGS.APP,
        deploy=SETTINGS.DEPLOY,
        node=SETTINGS.NODE,
        gcloud_config=SETTINGS.GCLOUD_CONFIG,
        deployed=True,
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_prerequisite_gcloud_and_deploy_helpers
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_legacy_upgrade_warning_can_cancel_before_provider_deploy
# @matrix setup : deploy failure gcloud-command post-deploy progress
# @pairs migrations:deploy setup:legacy-upgrade setup:major-version
def deploy_to_app_engine(
    *,
    print_final_summary=True,
    upgrade_notice_handled=False,
    first_install=False,
):
    from config import SETTINGS
    from installer import FORMATTER
    from installer.upgrade_notice import (
        confirm_legacy_upgrade_deployment,
        legacy_upgrade_deploy_notice_required,
        print_post_upgrade_maintenance_steps,
    )
    from runner.deploy import deploy

    f = FORMATTER.initialize()
    legacy_upgrade_notice = (
        not upgrade_notice_handled and legacy_upgrade_deploy_notice_required(SETTINGS)
    )
    if legacy_upgrade_notice:
        target_version = str(
            SETTINGS.APP.get("VERSION") or SETTINGS.NODE.get("version") or ""
        ).strip()
        confirm_legacy_upgrade_deployment(f, target_version)

    print(
        wrap_text(
            "Deploying App Engine indexes and the application may take up to 10 minutes."
        )
    )
    with f.progress(
        text="Deploying application",
        success_text='Application deployed',
    ) as spinner:
        try:
            deploy(
                build_assets=SETTINGS.APP.get("EXPERIMENTS_ENABLED", False),
                deploy_indexes=True,
                quiet=True,
                capture_output=True,
                announce_progress=False,
                announce_completion=False,
            )
        except Exception:
            spinner.fail()
            raise
        spinner.ok()

    from installer.mcp import requested

    if requested(SETTINGS.APP):
        print(wrap_text(f.success('MCP server is ready')))
    elif SETTINGS.APP.get("MCP_RESOURCE"):
        print(wrap_text("External AI access is disabled."))

    from installer.monitoring import reconcile_memory_alert_after_deploy

    reconcile_memory_alert_after_deploy()

    custom_domain = str(SETTINGS.APP.get("CUSTOM_DOMAIN") or "").strip()
    if custom_domain:
        from installer.domain.gcp import wait_for_managed_certificate
        from installer.state import record_step

        record_step("verify custom-domain TLS certificate")
        wait_for_managed_certificate(custom_domain, announce_ready=first_install)

    from installer.experiments import verify_bootstrap
    verify_bootstrap(require_admin=first_install)

    if print_final_summary:
        print(ui.success(wrap_text("Deployment complete")))
        print_summary()
    if legacy_upgrade_notice:
        print_post_upgrade_maintenance_steps(f)
