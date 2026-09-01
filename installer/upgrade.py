"""Update configuration or replace and upgrade an existing installation."""

import json
import subprocess
from datetime import datetime
from importlib import reload

from runner.context import GIT_CLI, REPOSITORY_ROOT, setup_command
from installer.image import get_images, save_images
from installer.utils import ensure_datastore_dependency, ensure_storage_dependency

from .errors import SetupError
from .upgrade_notice import (
    parse_release_version,
    post_upgrade_maintenance_required,
    print_post_upgrade_maintenance_notice,
    print_post_upgrade_maintenance_steps,
)
from .verify import activate_installation


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_update_reloads_config_and_setup_helpers
# @matrix setup : config-files deferred-jobs post-deploy public-page-settings storage-buckets
def update():
    """Apply app-saved configuration without replacing repository code."""
    activate_installation()
    return _apply_update(upgrade=False)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_replaces_source_then_applies_update
# @matrix setup : branch config-files git-upgrade post-deploy
# @pairs migrations:major-version setup:major-version
def upgrade(branch=None):
    """Replace tracked source from a remote branch, then apply and deploy it."""
    activate_installation()

    from config import SETTINGS
    import installer

    formatter = installer.FORMATTER.initialize()
    branch = str(branch or "main").strip()
    reset_target = _reset_target_for_branch(branch)
    installed_version = str(
        SETTINGS.APP.get("VERSION") or SETTINGS.NODE.get("version") or ""
    ).strip()

    with formatter.yaspin(
        text=formatter.success("Inspecting upgrade target")
    ) as spinner:
        target = _fetch_upgrade_target(spinner, branch=branch)
    if target is None:
        return 1
    maintenance_required = post_upgrade_maintenance_required(
        installed_version,
        target["version"],
    )

    print(f"\n{formatter.info('Lagniappe Software Upgrade')}")
    print("=" * 40)
    print(
        "\nThis will replace the installed Lagniappe source with "
        f"{reset_target} at {target['commit'][:12]}, apply saved settings, "
        "and offer to deploy it."
    )
    print(f"  Installed version: {installed_version or 'unknown'}")
    print(f"  Target version: {target['version']}")

    print(f"\n{formatter.success('What will be preserved:')}")
    print("  • All app data, users, and uploaded files")
    print("  • Generated installation settings and provider configuration")
    print("  • App-saved deployment settings, AI settings, and site images")

    print(f"\n{formatter.warning('What will be replaced:')}")
    print(f"  • Tracked repository files, using git reset --hard {reset_target}")
    print("  • Generated deployment files rebuilt from the new source")

    print(f"\n{formatter.error('What will be lost:')}")
    print("  • Tracked local code modifications in this checkout")

    consent = input(f"\n{formatter.info('Ready to upgrade? [y/N]: ')}")
    if consent.strip().casefold() not in {"y", "yes"}:
        print(formatter.success("Upgrade cancelled."))
        return 1

    with formatter.yaspin(
        text=formatter.success("Replacing tracked source")
    ) as spinner:
        if not _update_repository(
            spinner,
            branch=branch,
            target_commit=target["commit"],
        ):
            return 1

    _refresh_setup_dependencies()
    return _apply_update(
        upgrade=True,
        installed_version=installed_version,
        target_version=target["version"],
        maintenance_required=maintenance_required,
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_update_reloads_config_and_setup_helpers
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_replaces_source_then_applies_update
# @matrix setup : config-files deferred-jobs git-upgrade post-deploy provider-apis public-page-settings storage-buckets
# @pairs migrations:major-version setup:major-version
def _apply_update(
    *,
    upgrade,
    installed_version=None,
    target_version=None,
    maintenance_required=None,
):
    """Apply current-checkout generation and app-saved settings."""

    import config
    import installer

    f = installer.FORMATTER.initialize()
    reload(installer)
    reload(config)
    from config import SETTINGS, constants
    from installer import create_config, gcloud, utils

    reload(constants)
    create_config = reload(create_config)
    gcloud = reload(gcloud)
    utils = reload(utils)
    from runner.deploy import verify_runtime_deploy_surface

    installed_version = str(
        installed_version
        or SETTINGS.APP.get("VERSION")
        or SETTINGS.NODE.get("version")
        or ""
    ).strip()
    target_version = str(target_version or SETTINGS.NODE.get("version") or "").strip()
    if maintenance_required is None:
        maintenance_required = post_upgrade_maintenance_required(
            installed_version,
            target_version,
        )

    new_version = create_config.update_config()
    if target_version and new_version != target_version:
        raise SetupError(
            "The inspected upgrade target changed while preparing the deployment: "
            f"expected {target_version}, loaded {new_version}."
        )
    create_config.verify_application_config(upgrade=upgrade)
    verify_runtime_deploy_surface()
    if upgrade:
        print(f.success(f"Upgrading to version {new_version}"))
    else:
        print(f.success(f"Updating configuration for version {new_version}"))

    gcloud.enable_gcloud_apis()
    gcloud.setup_app_engine()
    gcloud.configure_storage_buckets()
    gcloud.configure_data_protection()
    _update_custom_images(f)
    _update_deployment_settings(f)
    _update_ai_settings(f)
    _update_public_page_settings(f)
    SETTINGS.save()
    config.verify_generation_manifest()

    completion = "Upgrade complete!" if upgrade else "Update complete!"
    print(f"\n{f.success(completion)}")
    if maintenance_required:
        print_post_upgrade_maintenance_notice(
            f,
            installed_version,
            new_version,
        )
    consent = input(f.info("Would you like to deploy the app now? [y/N]: "))
    if consent.casefold() == "y":
        utils.deploy_to_app_engine(
            print_final_summary=False,
            upgrade_notice_handled=True,
        )
        print(f"\n{f.info('Wrapping up installation...')}")
        recovery_ready = _configure_deferred_job_recovery(f, gcloud)
        print(f"\n{f.success('Deployment complete!')}")
        if SETTINGS.APP.get("CUSTOM_DOMAIN"):
            print(f"Your app is available at: https://{SETTINGS.APP['CUSTOM_DOMAIN']}")
        else:
            print(
                "Your app is available at: "
                f"{SETTINGS.APP.get('APP_URL', 'your App Engine URL')}"
            )
        if maintenance_required:
            print_post_upgrade_maintenance_steps(f)
        return 0 if recovery_ready else 1

    print(f.success(f"Remember to deploy when ready: {setup_command()}"))
    print(f"After deployment, run: {setup_command('jobs')}")
    print(f"Then reconcile memory monitoring: {setup_command('monitoring')}")
    if maintenance_required:
        print("The currently deployed application was not changed.")
        print_post_upgrade_maintenance_steps(f)
    return 0


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_post_deploy_deferred_job_recovery_failure_is_nonfatal
# @matrix deferred-jobs setup : failure-isolation post-deploy recovery
def _configure_deferred_job_recovery(f, gcloud):
    """Provision recovery without invalidating an otherwise successful deploy."""
    try:
        gcloud.create_deferred_job_reconciler()
    except (Exception, SystemExit) as error:
        message = (
            "Deployment succeeded, but deferred-job recovery could not be "
            "configured. This does not invalidate the completed update; "
            "active deferred jobs may fail until recovery is repaired."
        )
        if not isinstance(error, SystemExit) and str(error).strip():
            message = f"{message} Reason: {error}"
        print(f.warning(message))
        print(f"Retry with: {setup_command('jobs')}")
        return False
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_images_installs_storage_before_restore_spinner
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_images_continues_when_no_remote_image_is_available
# @matrix setup : image-restore site-image partial-failure
def _update_custom_images(f):
    """Best-effort restore site images uploaded through the app."""
    from config import SETTINGS

    try:
        ensure_datastore_dependency()
    except Exception as error:
        print(
            f.warning(
                f"Could not inspect custom images; continuing with existing "
                f"images. Reason: {error}"
            )
        )
        return

    site_image_entity = None
    with f.yaspin(text=f.success("Checking for custom images")) as spinner:
        try:
            site_image_entity = get_images()
            spinner.ok(f.ok_glyph)
        except Exception as error:
            spinner.write(
                f.warning(
                    f"Could not inspect custom images; continuing with existing "
                    f"images. Reason: {error}"
                )
            )
            spinner.ok(f.ok_glyph)
            return

    if not site_image_entity:
        return
    if not any(key != "version" for key in site_image_entity):
        return

    try:
        ensure_storage_dependency()
    except Exception as error:
        print(
            f.warning(
                f"Could not restore custom images; continuing with existing "
                f"images. Reason: {error}"
            )
        )
        return

    with f.yaspin(text=f.success("Restoring custom images")) as spinner:
        try:
            restored = save_images(spinner, site_image_entity)
            if restored:
                try:
                    SETTINGS.APP["SITE_IMAGE_VERSION"] = int(
                        site_image_entity.get("version", 0)
                    )
                except (TypeError, ValueError):
                    spinner.write(
                        f.warning(
                            "Site images were restored, but their cache version "
                            "was invalid; keeping the existing cache version."
                        )
                    )
            spinner.ok(f.ok_glyph)
        except Exception as error:
            spinner.write(
                f.warning(
                    f"Could not restore custom images; continuing with existing "
                    f"images. Reason: {error}"
                )
            )
            spinner.ok(f.ok_glyph)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_deployment_settings_applies_saved_app_config
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_deployment_settings_continues_when_unavailable
# @matrix setup : app-yaml deployment-settings
def _update_deployment_settings(f):
    """Apply deployment settings saved from the app, if available."""
    from config.deployment import apply_deployment_settings
    from installer import deployment as deployment_module

    try:
        ensure_datastore_dependency()
    except Exception as error:
        print(f.warning(f"Could not update deployment settings: {error}"))
        return

    with f.yaspin(text=f.success("Checking for deployment settings")) as spinner:
        try:
            deployment_entity = deployment_module.get_deployment_settings()
            spinner.ok(f.ok_glyph)
        except Exception as error:
            print(f.warning(f"Could not update deployment settings: {error}"))
            spinner.fail(f.fail_glyph)
            return

    if not deployment_entity:
        return

    with f.yaspin(text=f.success("Applying deployment settings")) as spinner:
        try:
            # Preserve the operator's saved deployment settings during an
            # update. The worker ceiling applies only when settings are newly
            # submitted through the application or generated for an install.
            apply_deployment_settings(
                deployment_entity,
                enforce_worker_limit=False,
            )
            spinner.ok(f.ok_glyph)
        except Exception as error:
            spinner.write(f.warning(f"Could not apply deployment settings: {error}"))
            spinner.fail(f.fail_glyph)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_ai_settings_applies_saved_app_config
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_ai_settings_continues_when_unavailable
# @matrix setup : ai-settings app-yaml
def _update_ai_settings(f):
    """Apply AI model settings saved from the app, if available."""
    from config.ai_settings import apply_ai_settings
    from installer import ai_settings as ai_settings_module

    try:
        ensure_datastore_dependency()
    except Exception as error:
        print(f.warning(f"Could not update AI settings: {error}"))
        return

    with f.yaspin(text=f.success("Checking for AI settings")) as spinner:
        try:
            ai_entity = ai_settings_module.get_ai_settings()
            spinner.ok(f.ok_glyph)
        except Exception as error:
            print(f.warning(f"Could not update AI settings: {error}"))
            spinner.fail(f.fail_glyph)
            return

    if not ai_entity:
        return

    with f.yaspin(text=f.success("Applying AI settings")) as spinner:
        try:
            apply_ai_settings(ai_entity)
            spinner.ok(f.ok_glyph)
        except Exception as error:
            spinner.write(f.warning(f"Could not apply AI settings: {error}"))
            spinner.fail(f.fail_glyph)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_public_page_settings_applies_saved_app_config
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_public_page_settings_continues_when_unavailable
# @matrix setup : app-yaml public-page-indexing
def _update_public_page_settings(f):
    """Apply public-page settings saved from the app, if available."""
    from config.public_pages import apply_public_page_settings
    from installer import public_pages as public_pages_module

    try:
        ensure_datastore_dependency()
    except Exception as error:
        print(f.warning(f"Could not update public-page settings: {error}"))
        return

    with f.yaspin(text=f.success("Checking for public-page settings")) as spinner:
        try:
            entity = public_pages_module.get_public_page_settings()
            spinner.ok(f.ok_glyph)
        except Exception as error:
            print(f.warning(f"Could not update public-page settings: {error}"))
            spinner.fail(f.fail_glyph)
            return

    if not entity:
        return

    with f.yaspin(text=f.success("Applying public-page settings")) as spinner:
        try:
            apply_public_page_settings(entity)
            spinner.ok(f.ok_glyph)
        except Exception as error:
            spinner.write(f.warning(f"Could not apply public-page settings: {error}"))
            spinner.fail(f.fail_glyph)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_refreshes_setup_dependencies_from_replaced_checkout
# @matrix setup : dependency-bootstrap git-upgrade
def _refresh_setup_dependencies():
    """Reload dependency bootstrap code from the replaced checkout and reconcile it."""
    from installer import package_install

    refreshed = reload(package_install)
    refreshed.ensure_pip_is_available()
    refreshed.ensure_setup_dependencies()


# @testable false
# @covered-by installer/upgrade.py::_update_repository
# @reason formatting helper for an argument-list Git reset target
def _reset_target_for_branch(branch):
    """Return the remote ref used as the hard-reset target."""
    branch = str(branch or "").strip()
    if branch.startswith(("origin/", "refs/")):
        return branch
    return f"origin/{branch}"


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_target_fetches_and_reads_exact_remote_version
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_target_rejects_missing_ref_and_invalid_version
# @matrix setup : branch failure-propagation git-upgrade version-validation
def _fetch_upgrade_target(spinner, branch="main"):
    """Fetch and inspect one exact remote commit without replacing source."""
    from installer import FORMATTER

    formatter = FORMATTER.initialize()
    branch = str(branch or "").strip()
    if not branch:
        spinner.write(formatter.error("Upgrade branch cannot be empty."))
        spinner.fail(formatter.fail_glyph)
        return None
    reset_target = _reset_target_for_branch(branch)
    git = GIT_CLI or "git"

    try:
        fetched = subprocess.run(
            [git, "fetch", "--all"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if fetched.returncode != 0:
            spinner.write(formatter.error(f"Git fetch failed: {fetched.stderr}"))
            spinner.fail(formatter.fail_glyph)
            return None

        resolved = subprocess.run(
            [git, "rev-parse", "--verify", f"{reset_target}^{{commit}}"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        commit = resolved.stdout.strip()
        if resolved.returncode != 0 or not commit:
            detail = resolved.stderr.strip() or "remote branch was not found"
            spinner.write(
                formatter.error(f"Could not resolve {reset_target}: {detail}")
            )
            spinner.fail(formatter.fail_glyph)
            return None

        package = subprocess.run(
            [git, "show", f"{commit}:package.json"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if package.returncode != 0:
            spinner.write(
                formatter.error(
                    f"Could not read package.json from {reset_target}: "
                    f"{package.stderr.strip()}"
                )
            )
            spinner.fail(formatter.fail_glyph)
            return None
        try:
            version = json.loads(package.stdout).get("version")
        except (AttributeError, json.JSONDecodeError) as error:
            spinner.write(
                formatter.error(
                    f"Could not parse package.json from {reset_target}: {error}"
                )
            )
            spinner.fail(formatter.fail_glyph)
            return None
        if parse_release_version(version) is None:
            spinner.write(
                formatter.error(
                    f"{reset_target} package.json must use a stable X.Y.Z version."
                )
            )
            spinner.fail(formatter.fail_glyph)
            return None

        spinner.ok(formatter.ok_glyph)
        return {
            "branch": branch,
            "ref": reset_target,
            "commit": commit,
            "version": str(version),
        }
    except (OSError, subprocess.SubprocessError) as error:
        spinner.write(formatter.error(f"Failed to inspect upgrade target: {error}"))
        spinner.fail(formatter.fail_glyph)
        return None


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_repository_preserves_report_before_branch_reset
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_repository_handles_clean_status_and_status_failure
# @matrix setup : branch failure-propagation git-upgrade local-change-report
def _update_repository(spinner, branch="main", *, target_commit=None):
    """Fetch remotes and replace tracked files with the requested remote ref."""
    from installer import FORMATTER

    formatter = FORMATTER.initialize()
    branch = str(branch or "").strip()
    if not branch:
        spinner.write(formatter.error("Upgrade branch cannot be empty."))
        spinner.fail(formatter.fail_glyph)
        return False
    reset_target = _reset_target_for_branch(branch)
    replacement_target = str(target_commit or reset_target).strip()
    git = GIT_CLI or "git"

    try:
        status = subprocess.run(
            [git, "status", "--porcelain"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0:
            spinner.write(formatter.error(f"Git status failed: {status.stderr}"))
            spinner.fail(formatter.fail_glyph)
            return False

        if status.stdout.strip():
            spinner.write(
                formatter.warning(
                    "Local changes detected. Upgrade will discard tracked "
                    f"changes with git reset --hard {replacement_target}."
                )
            )
            report_path = _write_local_changes_report(
                status.stdout,
                reset_target=replacement_target,
            )
            if report_path:
                spinner.write(
                    formatter.warning(f"Saved local changes report: {report_path}")
                )

        if target_commit is None:
            fetched = subprocess.run(
                [git, "fetch", "--all"],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if fetched.returncode != 0:
                spinner.write(formatter.error(f"Git fetch failed: {fetched.stderr}"))
                spinner.fail(formatter.fail_glyph)
                return False

        replaced = subprocess.run(
            [git, "reset", "--hard", replacement_target],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if replaced.returncode != 0:
            spinner.write(formatter.error(f"Git reset failed: {replaced.stderr}"))
            spinner.fail(formatter.fail_glyph)
            return False

        spinner.ok(formatter.ok_glyph)
        return True
    except (OSError, subprocess.SubprocessError) as error:
        spinner.write(formatter.error(f"Failed to update repository: {error}"))
        spinner.fail(formatter.fail_glyph)
        return False


# @testable false
# @covered-by installer/upgrade.py::_update_repository
# @reason local safety report is exercised through the dirty upgrade path
def _write_local_changes_report(status_output, reset_target="origin/main"):
    """Save a best-effort report of tracked changes before a hard reset."""
    reports_dir = REPOSITORY_ROOT / "reports"
    git = GIT_CLI or "git"

    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = reports_dir / f"upgrade-local-changes-{timestamp}.md"

        diff_stat = subprocess.run(
            [git, "diff", "--stat"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        unstaged_diff = subprocess.run(
            [git, "diff"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        staged_diff = subprocess.run(
            [git, "diff", "--cached"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        report_path.write_text(
            "\n".join(
                [
                    "# Lagniappe Upgrade Local Changes Report",
                    "",
                    f"Created: {datetime.now().isoformat(timespec='seconds')}",
                    "",
                    (
                        "Lagniappe detected local repository changes before running "
                        f"`git reset --hard {reset_target}`."
                    ),
                    (
                        "Tracked file changes may be discarded by the reset. "
                        "Untracked files are listed for visibility but are not "
                        "removed by `git reset --hard`."
                    ),
                    "",
                    "## Git Status",
                    "",
                    "```text",
                    status_output.rstrip() or "(clean)",
                    "```",
                    "",
                    "## Diff Stat",
                    "",
                    "```text",
                    _git_report_output(diff_stat),
                    "```",
                    "",
                    "## Unstaged Diff",
                    "",
                    "```diff",
                    _git_report_output(unstaged_diff),
                    "```",
                    "",
                    "## Staged Diff",
                    "",
                    "```diff",
                    _git_report_output(staged_diff),
                    "```",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return report_path
    except (OSError, subprocess.SubprocessError):
        return None


# @testable false
# @covered-by installer/upgrade.py::_write_local_changes_report
# @reason formatting helper for the local changes report
def _git_report_output(result):
    output = result.stdout or result.stderr or ""
    if result.returncode != 0:
        prefix = f"(command failed with exit code {result.returncode})"
        return f"{prefix}\n{output.strip()}".strip()
    return output.strip() or "(none)"
