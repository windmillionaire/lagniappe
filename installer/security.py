"""Interactive security configuration entry points."""

from runner import presentation as ui
from runner.presentation import output as print, read_input as input

from runner.console import format_prompt, wrap_text
from .verify import prepare_existing_installation


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_security_cli_configures_and_optionally_deploys_redis_tls
# @matrix setup : cli deploy redis-tls
def configure_security():
    """Configure optional Redis transport security for an installation."""
    prepare_existing_installation()

    from config import SETTINGS
    from config.redis import redis_tls_enabled
    from installer import FORMATTER, utils
    from installer import redis as redis_setup

    f = FORMATTER.initialize()
    enabled = redis_tls_enabled(SETTINGS.APP)

    print(wrap_text(f"\n{ui.heading('Security configuration')}"))
    print(wrap_text(f"Redis TLS is currently {'enabled' if enabled else 'disabled'}."))

    while True:
        choice = (
            input(
                format_prompt(
                    "Enable/refresh Redis TLS, disable it, or exit? [E/d/x]: "
                )
            )
            .strip()
            .lower()
        )
        if choice in {"", "e", "enable", "refresh"}:
            result = redis_setup._enable_redis_tls()
            break
        if choice in {"d", "disable"}:
            result = redis_setup._disable_redis_tls()
            break
        if choice in {"x", "exit"}:
            print(ui.status(wrap_text("Security configuration unchanged.")))
            return 1
        print(
            f.error(
                wrap_text("Choose E to enable/refresh, D to disable, or X to exit.")
            )
        )

    if result is False:
        return 1
    if result is None:
        return 1

    print(
        f.warning(
            wrap_text(
                "The app must be redeployed promptly so new Redis connections use "
                "the same transport mode as Redis Cloud."
            )
        )
    )
    consent = input(format_prompt("Deploy the updated app now? [Y/n]: "))
    if consent.lower() != "n":
        utils.deploy_to_app_engine(print_final_summary=False)
        print(f.success(wrap_text("Redis security configuration deployed.")))
    else:
        print(
            f.warning(
                wrap_text(
                    "Deployment deferred. Newly opened app connections may fail "
                    "until the updated settings are deployed."
                )
            )
        )
    return 0
