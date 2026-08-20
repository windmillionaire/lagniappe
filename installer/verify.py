"""Read-only validation and explicitly named setup activation/repair flows."""


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_installation_is_read_only_and_activation_is_explicit
# @features setup
# @dimensions gcloud-config deploy-surface transactional-state
def validate_installation():
    """Validate local setup state without creating or retargeting resources."""
    from config import verify_generation_manifest
    from runner.deploy import verify_runtime_deploy_surface
    from installer import utils

    utils.check_gcloud_cli()
    verify_generation_manifest()
    verify_runtime_deploy_surface()
    return True


# @testable false
# @covered-by installer/verify.py::validate_installation
# @reason compatibility alias intentionally delegates to read-only validation
def verify_installation():
    """Compatibility name for read-only validation."""
    return validate_installation()


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_installation_is_read_only_and_activation_is_explicit
# @features setup
# @dimensions gcloud-config activation
def activate_installation():
    """Explicitly activate the installation's saved local gcloud context."""
    from runner.gcloud import config_gcloud

    config_gcloud()
    return True


# @testable false
# @covered-by installer/verify.py::activate_installation
# @covered-by installer/verify.py::validate_installation
# @reason named composition of the explicit activation and validation contracts
def prepare_existing_installation():
    """Activate local gcloud state, then validate an existing installation."""
    activate_installation()
    return validate_installation()


# @testable false
# @covered-by installer/create_config.py::set_application_defaults
# @reason explicit first-time authority wrapper around the tested initializer
def initialize_installation():
    """Run first-time configuration, which may create or select a project."""
    from installer.create_config import set_application_defaults

    return set_application_defaults()


# @testable true
# @tests tests_tooling/test_001g_setup_release_readiness.py::test_repair_runs_reconciliation_then_validation
# @features setup
# @dimensions repair explicit-mutation validation
def repair_installation():
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
