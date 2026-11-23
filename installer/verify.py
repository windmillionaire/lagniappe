"""Read-only validation and explicitly named setup activation/repair flows."""

from runner.presentation import output as print


def validate_installation() -> bool:
    """Validate local setup state without creating or retargeting resources."""
    from config import verify_generation_manifest
    from runner.deploy import verify_runtime_deploy_surface
    from installer.commands import check_gcloud_cli

    check_gcloud_cli()
    verify_generation_manifest()
    verify_runtime_deploy_surface()
    return True


def verify_installation() -> bool:
    """Compatibility name for read-only validation."""
    return validate_installation()


def activate_installation(*, announce: bool = True) -> bool:
    """Explicitly activate the installation's saved local gcloud context."""
    from runner.gcloud import config_gcloud

    config_gcloud(announce=announce)
    return True


def prepare_existing_installation() -> bool:
    """Validate local setup after the CLI has activated and verified credentials."""
    return validate_installation()


def initialize_installation() -> bool:
    """Run first-time configuration, which may create or select a project."""
    from installer.create_config import set_application_defaults

    return set_application_defaults()


def repair_installation() -> int:
    """Explicitly reconcile setup state and validate the resulting installation."""
    from installer import wrap_text

    print(
        wrap_text(
            "Repair mode will reconcile the complete saved installation. "
            "Provider and local changes are possible."
        )
    )
    from installer.install import install

    result = install()
    if result is False or result is None:
        return result
    if result is not True and result != 0:
        return result
    validate_installation()
    return 0
