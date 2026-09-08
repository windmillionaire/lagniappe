"""Version-driven owner-maintenance notices for installer deployments."""

from runner import presentation as ui
from runner.presentation import output as print, read_input as input

import re

from runner.console import format_prompt, wrap_text
from .errors import SetupCancelled


RELEASE_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_maintenance_notice_version_policy
# @matrix setup migrations : major-version version-validation
def parse_release_version(value):
    """Return a stable release-version tuple, or ``None`` for invalid input."""
    match = RELEASE_VERSION_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_maintenance_notice_version_policy
# @matrix setup migrations : major-version unknown-source
def post_upgrade_maintenance_required(installed_version, target_version):
    """Return whether the target crosses an owner-maintenance boundary."""
    target = parse_release_version(target_version)
    if target is None:
        raise ValueError(
            f"Target application version is not stable X.Y.Z: {target_version!r}."
        )
    installed = parse_release_version(installed_version)
    if installed is None:
        return True
    return target[0] > installed[0]


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_legacy_upgrade_deploy_notice_uses_active_operation
# @matrix setup migrations : legacy-upgrade major-version
def legacy_upgrade_deploy_notice_required(settings):
    """Detect a major release reached through a pre-1.0 upgrade orchestrator."""
    from installer import state

    journal = getattr(state, "_ACTIVE_JOURNAL", None)
    payload = getattr(journal, "payload", {}) if journal is not None else {}
    version = str(settings.APP.get("VERSION") or settings.NODE.get("version") or "")
    parsed = parse_release_version(version)
    return payload.get("mode") == "upgrade" and parsed is not None and parsed[1:] == (0, 0)


# @testable false
# @covered-by installer/upgrade.py::_apply_update
# @covered-by installer/utils.py::deploy_to_app_engine
# @reason shared terminal presentation is asserted through both deployment workflows
def print_post_upgrade_maintenance_notice(formatter, installed_version, target_version):
    """Explain required owner work before a major-version deployment."""
    transition = f"to version {target_version}"
    if parse_release_version(installed_version):
        transition = f"from {installed_version} to {target_version}"
    print(wrap_text(f"\n{ui.heading('Required post-upgrade maintenance')}"))
    print(
        wrap_text(
            f"This deployment upgrades Lagniappe {transition} and requires "
            "Owner-run application maintenance. Setup does not run data migrations."
        )
    )
    print(
        wrap_text(
            (
                "After deployment, open "
                f"{ui.literal('Admin → Site Settings → Maintenance')}, select "
                f"{ui.literal('Apply Updates')}, resolve any reported failures, and then "
                f"select {ui.literal('Refresh Cache')}."
            )
        )
    )


# @testable false
# @covered-by installer/upgrade.py::_apply_update
# @covered-by installer/utils.py::deploy_to_app_engine
# @reason shared terminal presentation is asserted through both deployment workflows
def print_post_upgrade_maintenance_steps(formatter):
    """Repeat the required in-app work after a major deployment succeeds."""
    print(wrap_text(f"\n{ui.heading('Required next steps')}"))
    print(
        wrap_text((f"  {ui.literal('1.')} Sign in as the Owner or an Administrator."))
    )
    print(
        wrap_text(
            (
                f"  {ui.literal('2.')} Open "
                f"{ui.literal('Admin → Site Settings → Maintenance')}."
            )
        )
    )
    print(
        wrap_text(
            (
                f"  {ui.literal('3.')} Select {ui.literal('Apply Updates')} and resolve "
                "any reported failures."
            )
        )
    )
    print(wrap_text((f"  {ui.literal('4.')} Select {ui.literal('Refresh Cache')}.")))


# @testable false
# @covered-by installer/utils.py::deploy_to_app_engine
# @reason compatibility confirmation is exercised through the deployment helper
def confirm_legacy_upgrade_deployment(formatter, target_version):
    """Give old upgrade orchestration one final stop before deploying 1.0+."""
    print_post_upgrade_maintenance_notice(formatter, None, target_version)
    consent = input(
        format_prompt(
            "Deploy this major version and complete the required maintenance "
                "afterward? [y/N]: "
        )
    )
    if consent.strip().casefold() not in {"y", "yes"}:
        raise SetupCancelled(
            "Deployment cancelled. The currently deployed application was not changed."
        )


__all__ = [
    "confirm_legacy_upgrade_deployment",
    "legacy_upgrade_deploy_notice_required",
    "parse_release_version",
    "post_upgrade_maintenance_required",
    "print_post_upgrade_maintenance_notice",
    "print_post_upgrade_maintenance_steps",
]
