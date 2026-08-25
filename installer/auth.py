"""Explicit interactive authentication for setup-managed Google Cloud access."""

from installer.errors import SetupError


# @testable true
# @tests tests_tooling/test_001e_setup_orchestration.py::test_setup_auth_uses_explicit_browser_flow
# @matrix auth setup : adc explicit-command gcloud-token interactive
def authenticate():
    """Refresh the saved gcloud login and align human ADC for this checkout."""
    from runner.gcloud import activate_repository_gcloud

    try:
        activate_repository_gcloud(
            ensure_adc=True,
            ensure_cli_token=True,
            allow_cli_login=True,
            allow_runtime_adc=False,
            allow_adc_login=True,
            select_adc_target=True,
        )
    except RuntimeError as error:
        raise SetupError(f"Authentication did not complete: {error}") from error

    print(
        "Google Cloud CLI and Application Default Credentials are ready for "
        "this installation."
    )
    return 0
