"""Installer orchestration, settings persistence and public compatibility entrypoints."""

from runner import presentation as ui
from runner.presentation import output as print, read_input as input
import secrets
from config.experiments import normalize_experiments_config

from runner.console import format_prompt
from runner.context import setup_command
from installer import wrap_text
from installer.errors import SetupCancelled
from installer.commands import _fail
from installer import admin, credentials, project_bootstrap, setup_target


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_adc_authentication_is_kept_only_after_project_permission_confirmation
# @matrix setup : adc permissions transactional-state
def _confirm_operator_permissions(
    project_id,
    *,
    billing_account=None,
    require_billing_link=False,
    transaction,
):
    try:
        missing = setup_target._require_operator_permissions(
            project_id,
            billing_account=billing_account,
            require_billing_link=require_billing_link,
        )
    except Exception:
        transaction.reject_current()
        raise
    transaction.commit()
    return missing


# @testable false
# @covered-by installer/create_config.py::set_application_defaults
# @reason secret-free console summary owned by the fresh-install confirmation flow
def _display_install_identity_summary(preflight, adc_identity):
    from config import SETTINGS

    rows = [
        ("Active gcloud configuration", SETTINGS.GCLOUD_CONFIG["NAME"]),
        ("Active gcloud CLI account", SETTINGS.GCLOUD_CONFIG["ACCOUNT"]),
    ]
    if adc_identity.get("state") != "pending":
        rows.extend(
            [
                ("ADC principal", adc_identity.get("principal") or "(unknown)"),
                ("ADC project", adc_identity.get("project") or "(unset)"),
                ("ADC quota project", adc_identity.get("quota_project") or "(unset)"),
            ]
        )
    rows.extend(
        [
            ("Target project", SETTINGS.GCLOUD_CONFIG["PROJECT"]),
            (
                "Installer/provisioner",
                SETTINGS.APP.get("INSTALLER_EMAIL")
                or SETTINGS.GCLOUD_CONFIG["ACCOUNT"],
            ),
            (
                "Deployer",
                SETTINGS.APP.get("DEPLOYER_EMAIL") or SETTINGS.GCLOUD_CONFIG["ACCOUNT"],
            ),
            ("Application owner", SETTINGS.APP.get("ADMIN_EMAIL") or "(not set)"),
            (
                "Temporary application Administrator",
                SETTINGS.APP.get("BOOTSTRAP_ADMIN_EMAIL") or "(none)",
            ),
        ]
    )
    runtime_email = SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
    if runtime_email:
        rows.append(("Runtime service account", runtime_email))
    else:
        planned_email = (
            f"{SETTINGS.GCLOUD_CONFIG['NAME']}@"
            f"{SETTINGS.GCLOUD_CONFIG['PROJECT']}.iam.gserviceaccount.com"
        )
        rows.append(("Runtime service account (planned)", planned_email))
    print("\n" + ui.heading("Configuration"))
    for label, value in rows:
        print(ui.value(label, value, column=38, verbatim=True))
    print(ui.value("Required APIs already enabled", len(preflight["enabled_apis"])))
    print(ui.value("Required APIs pending", len(preflight["missing_apis"])))


# @testable false
# @covered-by installer/create_config.py::_set_default_config
# @reason generates missing secrets and applies the deterministic application document
def _build_app_settings():
    from config import SETTINGS
    from installer import config_builders

    secret_defaults = {}
    for key, size in (("GIBBERISH", 16), ("SECRET_KEY", 32)):
        if key not in SETTINGS.APP:
            secret_defaults[key] = secrets.token_hex(size)
    if not SETTINGS.APP.get("AGENT_ACCESS_CODE"):
        secret_defaults["AGENT_ACCESS_CODE"] = secrets.token_urlsafe(32)
    app = config_builders.build_app_settings(
        SETTINGS.APP,
        SETTINGS.GCLOUD_CONFIG,
        version=SETTINGS.NODE.get("version"),
        secret_defaults=secret_defaults,
    )
    SETTINGS.APP.clear()
    SETTINGS.APP.update(app)


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_deep_copies_templates
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_generates_fresh_settings
# @pair setup:config-files
def _set_default_config():
    from config import SETTINGS
    from installer import config_builders

    _build_app_settings()

    app, deploy = config_builders.build_deploy_yaml(SETTINGS.APP, SETTINGS.DEPLOY)
    dev, test = config_builders.build_dev_yaml(
        SETTINGS.DEV_CONFIG, SETTINGS.TEST_CONFIG
    )
    indexes = config_builders.build_index_yaml(SETTINGS.INDEX)
    manifest = config_builders.build_manifest(app, SETTINGS.MANIFEST)
    for target, generated in (
        (SETTINGS.APP, app),
        (SETTINGS.DEPLOY, deploy),
        (SETTINGS.DEV_CONFIG, dev),
        (SETTINGS.TEST_CONFIG, test),
        (SETTINGS.INDEX, indexes),
        (SETTINGS.MANIFEST, manifest),
    ):
        target.clear()
        target.update(generated)
    SETTINGS.DEV.pop("setup_draft", None)

    SETTINGS.save()


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_update_config_sets_application_version_from_package
# @tests tests_tooling/test_001a_setup_validation_config.py::test_update_config_refreshes_preloaded_builders_and_current_settings
# @matrix setup : config-files config-version git-upgrade
def update_config():
    """Refresh generated config defaults and return the active package version."""
    from importlib import reload
    from installer import config_builders
    from runner import deploy

    # Older in-memory upgrade orchestrators reload only this facade. Refresh
    # the builders and their explicit-input manifest helper even if the process
    # loaded their older implementations before replacing the checkout.
    reload(deploy)
    reload(config_builders)
    from config import SETTINGS, constants

    version = str(SETTINGS.NODE.get("version") or "").strip()
    if not version:
        raise RuntimeError("package.json must define the current application version.")
    SETTINGS.APP["VERSION"] = version
    SETTINGS.APP.setdefault(
        "GOOGLE_SIGNIN_ENABLED",
        constants.DEFAULT_GOOGLE_SIGNIN_ENABLED,
    )
    _set_default_config()

    return version


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_set_application_defaults_persists_prompted_name_before_cloud_change
# @tests tests_tooling/test_001a_setup_validation_config.py::test_existing_project_prepares_bootstrap_apis_before_adc
# @tests tests_tooling/test_001e_setup_orchestration.py::test_recovery_uses_saved_project_preserves_owner_and_verifies_before_dev_write
# @matrix setup : adc config-files existing-project gcloud-config interactive-input preconfirmation provider-apis recovery
def set_application_defaults():
    with credentials._adc_auth_transaction() as transaction:
        return _set_application_defaults(transaction)


# @testable false
# @covered-by installer/create_config.py::set_application_defaults
# @reason installer implementation runs within the public ADC transaction boundary
def _set_application_defaults(transaction):
    from config import File, SETTINGS
    from config.recovery import (
        materialize_recovery_redis_ca,
        validate_recovery_document,
    )
    from installer import FORMATTER

    f = FORMATTER.initialize()
    recovery_mode = File.APP_SETTINGS_YAML.exists() and not File.DEV_YAML.exists()
    SETTINGS.RECOVERY_MODE = recovery_mode
    if recovery_mode:
        print(
            f.warning(
                wrap_text(
                    "Recovery mode: found config/files/lagniappe_settings.yaml "
                    "without config/files/lagniappe_dev.yaml. No provider or local "
                    "configuration mutation will occur until the recovered target "
                    "has been authenticated and verified."
                )
            )
        )
        recovered = validate_recovery_document(SETTINGS.APP)
        SETTINGS.APP.clear()
        SETTINGS.APP.update(recovered)

    setup_draft = (
        {}
        if recovery_mode
        else getattr(SETTINGS, "DEV", {}).get("setup_draft") or {}
    )
    app_name = str(
        SETTINGS.APP.get("APP_NAME") or setup_draft.get("APP_NAME") or ""
    ).strip()
    gcloud_name = SETTINGS.GCLOUD_CONFIG.get("NAME", "")
    account = SETTINGS.GCLOUD_CONFIG.get("ACCOUNT", "")
    project_id = (
        SETTINGS.APP["GOOGLE_CLOUD_PROJECT"]
        if recovery_mode
        else SETTINGS.GCLOUD_CONFIG.get("PROJECT", "")
    )

    SETTINGS.GCLOUD_CONFIG["ACCOUNT"] = setup_target._get_gcloud_account(account)
    account = SETTINGS.GCLOUD_CONFIG["ACCOUNT"]

    if not recovery_mode and not setup_target._validate_app_name(app_name) and not project_id:
        app_name, selected_project = setup_target._select_initial_target(account)
    else:
        if not setup_target._validate_app_name(app_name):
            app_name = setup_target._get_app_name()
        sanitized_app_name = setup_target._gcloud_configuration_name(app_name)
        selected_project = setup_target._get_gcloud_project(project_id, sanitized_app_name)

    if not setup_target._validate_app_name(app_name):
        print(f.error(wrap_text("A name is required for your Lagniappe installation.")))
        _fail()
    SETTINGS.APP["APP_NAME"] = app_name

    sanitized_app_name = setup_target._gcloud_configuration_name(app_name)
    if gcloud_name != sanitized_app_name:
        SETTINGS.GCLOUD_CONFIG["NAME"] = sanitized_app_name

    if recovery_mode and selected_project != project_id:
        raise RuntimeError(
            "Recovery cannot retarget the saved installation to another project."
        )
    SETTINGS.GCLOUD_CONFIG["PROJECT"] = selected_project
    account = SETTINGS.GCLOUD_CONFIG["ACCOUNT"]
    project_id = SETTINGS.GCLOUD_CONFIG["PROJECT"]
    target = setup_target.SetupTarget(
        app_name=app_name,
        configuration_name=SETTINGS.GCLOUD_CONFIG["NAME"],
        account=account,
        project_id=project_id,
    )
    if not recovery_mode:
        SETTINGS.DEV["setup_draft"] = {"APP_NAME": app_name}
        SETTINGS.save(File.DEV_YAML)

    from runner import gcloud as switcher

    switcher.config_gcloud()
    cli_identity = setup_target._active_cli_identity()
    expected_cli = {
        "configuration": SETTINGS.GCLOUD_CONFIG["NAME"],
        "account": SETTINGS.GCLOUD_CONFIG["ACCOUNT"],
        "project": project_id,
    }
    if cli_identity != expected_cli:
        raise RuntimeError(
            f"Active gcloud CLI identity mismatch: expected {expected_cli}, "
            f"found {cli_identity}"
        )

    preflight = project_bootstrap._target_preflight(target)
    cli_identity = setup_target._active_cli_identity()
    if cli_identity != expected_cli:
        raise RuntimeError(
            f"Active gcloud CLI identity mismatch after target preflight: "
            f"expected {expected_cli}, found {cli_identity}"
        )
    SETTINGS._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(preflight["enabled_apis"])
    if recovery_mode and preflight["project"]["state"] != "available":
        raise RuntimeError(
            f"Recovery requires positive access to existing project '{project_id}'; "
            f"provider state was {preflight['project']['state']}."
        )
    if recovery_mode and not (
        preflight["project"].get("details") or {}
    ).get("projectNumber"):
        raise RuntimeError(
            "Recovery could not verify the target project number needed to "
            "cross-check Cloud Storage ownership."
        )
    SETTINGS.GCLOUD_CONFIG["BILLING_ACCOUNT"] = preflight["billing_account"]
    project_client = None
    if preflight["project"]["state"] == "available":
        project_client = setup_target._preflight_operator_authority(account, project_id)
    if not recovery_mode:
        from installer.admin import collect_owner_and_signin_choice

        collect_owner_and_signin_choice(account)
        admin._configure_delegated_bootstrap(
            preflight,
            account,
            project_id=project_id,
            project_client=project_client,
            app_settings=SETTINGS.APP,
        )
    defer_adc_for_api_preparation = (
        not recovery_mode
        and preflight["project"]["state"] == "available"
        and bool(
            project_bootstrap.BOOTSTRAP_GOOGLE_CLOUD_APIS - set(preflight["enabled_apis"])
        )
    )
    if (
        preflight["project"]["state"] == "available"
        and not defer_adc_for_api_preparation
    ):
        adc_identity = credentials._ensure_adc_principal(
            target, transaction=transaction
        )
    else:
        adc_identity = {"state": "pending"}
        if preflight["project"]["state"] != "available":
            transaction.refresh_required = True

    # @testable false
    # @covered-by installer/create_config.py::set_application_defaults
    # @reason spinner closure for the parent install preflight sequence
    def align_target_adc():
        if defer_adc_for_api_preparation:
            credentials._ensure_adc_principal(target, transaction=transaction)
        with f.progress(
            text="Verifying Google Cloud credentials",
            success_text='Google Cloud credentials verified',
        ) as sp:
            identity = credentials._set_adc_quota_project(
                target, sp, transaction=transaction
            )
            sp.ok()
        with f.progress(
            text="Verifying project permissions",
            success_text='Project permissions verified',
        ) as sp:
            _confirm_operator_permissions(
                project_id,
                transaction=transaction,
                billing_account=preflight["billing_account"],
                require_billing_link=(
                    bool(preflight["billing_account"])
                    and not preflight["billing_enabled"]
                ),
            )
            sp.ok()
        return identity

    if (
        preflight["project"]["state"] == "available"
        and not defer_adc_for_api_preparation
    ):
        adc_identity = align_target_adc()

    if recovery_mode:
        from installer.recovery import verify_recovery_resources

        materialize_recovery_redis_ca(SETTINGS.APP)
        recovery_report = verify_recovery_resources(
            SETTINGS.APP,
            project_id,
            project_details=preflight["project"].get("details"),
        )
        print(ui.heading(wrap_text("\nRecovery provider discovery")))
        for resource, observation in recovery_report.items():
            print(wrap_text(f"{resource}: {observation['state']}"))

    _set_default_config()

    _display_install_identity_summary(preflight, adc_identity)
    confirmation = input(
        format_prompt("Continue with installation? [y/N]: ")
    )
    if confirmation.strip().lower() not in ("y", "yes"):
        print(
            f.info(
                wrap_text("Installation cancelled. Configuration files were preserved.")
            )
        )
        raise SetupCancelled("Installation cancelled.")

    project_bootstrap._apply_target_preflight(
        target,
        preflight,
        project_ready=(
            align_target_adc
            if (
                preflight["project"]["state"] in ("absent", "unverified")
                or defer_adc_for_api_preparation
            )
            else None
        ),
    )
    SETTINGS._SETUP_ENABLED_GOOGLE_CLOUD_APIS = set(preflight["enabled_apis"])
    if (
        SETTINGS.GCLOUD_CONFIG.get("BILLING_ACCOUNT")
        != preflight["billing_account"]
    ):
        SETTINGS.GCLOUD_CONFIG["BILLING_ACCOUNT"] = preflight["billing_account"]
        SETTINGS.save(File.DEV_YAML)

    return True


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_application_config_reports_missing_areas
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_application_config_requires_google_client_only_when_enabled
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_application_config_rejects_keyless_identity_mismatch
# @tests tests_tooling/test_001a_setup_validation_config.py::test_verify_application_config_reports_invalid_redis_tls
# @tests tests_tooling/test_001a_setup_validation_config.py::test_upgrade_collects_missing_ai_choices
# @matrix setup : config-files google-oauth keyless-config optional project-identity redis-tls validation
# @matrix setup : ai-policy git-upgrade interactive-input
def verify_application_config(upgrade=False):
    """Validate settings and collect the new AI policy during source upgrades."""
    from installer import FORMATTER

    f = FORMATTER.initialize()

    from config import constants, SETTINGS
    normalize_experiments_config(SETTINGS.APP)

    required_settings = constants.REQUIRED_APPLICATION_SETTINGS
    missing_areas = list(
        dict.fromkeys(
            area
            for setting, area in required_settings.items()
            if SETTINGS.APP.get(setting) is None
        )
    )
    if "RUNTIME_SERVICE_ACCOUNT_EMAIL" in required_settings:
        runtime_email = str(
            SETTINGS.APP.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
        ).strip().casefold()
        internal_caller_email = str(
            SETTINGS.APP.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL") or ""
        ).strip().casefold()
        project_id = str(
            SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT") or ""
        ).strip()
        expected_suffix = f"@{project_id}.iam.gserviceaccount.com"
        if (
            runtime_email
            and internal_caller_email
            and (
                runtime_email != internal_caller_email
                or not runtime_email.endswith(expected_suffix)
            )
            and "Google Cloud keyless identity" not in missing_areas
        ):
            missing_areas.append("Google Cloud keyless identity")

    if "AUTH_EMAIL_CONFIG" in required_settings:
        from installer.auth_email import auth_email_config_matches

        if (
            SETTINGS.APP.get("AUTH_EMAIL_CONFIG") is not None
            and not auth_email_config_matches(
                SETTINGS.APP.get("AUTH_EMAIL_CONFIG")
            )
            and "Authentication email" not in missing_areas
        ):
            missing_areas.append("Authentication email")

    if "GOOGLE_SIGNIN_ENABLED" in required_settings:
        google_signin_enabled = SETTINGS.APP.get("GOOGLE_SIGNIN_ENABLED") is True
        if (
            google_signin_enabled
            and not str(SETTINGS.APP.get("GOOGLE_CLIENT_ID") or "").strip()
            and "Authentication" not in missing_areas
        ):
            missing_areas.append("Authentication")

    if SETTINGS.APP.get("REDIS_TLS"):
        from config.redis import (
            RedisTLSConfigurationError,
            redis_client_kwargs,
        )

        try:
            redis_client_kwargs(SETTINGS.APP)
        except RedisTLSConfigurationError:
            if "Redis transport security" not in missing_areas:
                missing_areas.append("Redis transport security")

    if missing_areas and not upgrade:
        message = "The application configuration is missing required settings.\n"
    else:
        message = "New features require additional settings.\n"

    if missing_areas:
        print(
            f.error(
                f"{message}"
                f"Missing configuration areas: {', '.join(missing_areas)}.\n"
                f"Run {setup_command()} to add the missing settings while preserving the current configuration."
            )
        )
        _fail()

    if upgrade and "EXTERNAL_AI_ENABLED" not in SETTINGS.APP:
        # The source-upgrade path reloads this module after replacing the checkout,
        # so older upgrade orchestrators also reach the newly introduced choices.
        from installer.optional import configure_ai_features

        configure_ai_features()
    elif upgrade and "MCP_NAME" not in SETTINGS.APP:
        from installer.mcp import requested

        if requested(SETTINGS.APP):
            from installer.optional import configure_mcp_name

            configure_mcp_name()
            SETTINGS.save()

    print(f.success(wrap_text("Application configuration verified.")))
    return True


# @testable false
# @covered-by installer/setup_target.py::validate_project_id
# @reason public compatibility entrypoint for target syntax validation
def validate_project_id(project_id):
    return setup_target.validate_project_id(project_id)
