"""Deterministic generated documents from explicit installer inputs.

These builders neither read SETTINGS nor persist documents. Secret creation and
application of the returned mappings belong to create_config.
"""

import copy

from config.constants import UNSUPPORTED_SETTING_KEYS
from config.recovery import CONFIG_KIND, CONFIG_SCHEMA_VERSION
from config.locations import normalize_app_engine_location, normalize_resource_region


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_build_app_settings_refreshes_agent_access_defaults
# @tests tests_tooling/test_001a_setup_validation_config.py::test_config_builders_preserve_inputs_and_generate_independent_documents
# @matrix setup : agent-access ai-defaults config-files config-version source-link
def build_app_settings(app_settings, gcloud_config, *, version, secret_defaults):
    from config import constants

    app = dict(app_settings)

    app.pop("FIREBASE_CONFIG", None)
    # Current AI policy uses AI_ENABLED and EXTERNAL_AI_ENABLED. MCP deployment
    # details are flat settings; client registration belongs to application code.
    app.pop("EXTERNAL_AGENT_API_ENABLED", None)
    app.pop("REMOTE_MCP", None)
    app.setdefault("AI_ENABLED", True)
    unsupported = sorted(UNSUPPORTED_SETTING_KEYS.intersection(app))
    if unsupported:
        raise RuntimeError(
            "Current setup found unsupported settings: "
            + ", ".join(unsupported)
        )
    version = str(version or "").strip()
    if not version:
        raise RuntimeError("package.json must define the current application version.")
    app_engine_location = normalize_app_engine_location(
        app.get("APP_ENGINE_LOCATION")
        or constants.DEFAULT_APP_ENGINE_LOCATION
    )
    resource_region = normalize_resource_region(
        app.get("RESOURCE_REGION")
        or constants.DEFAULT_RESOURCE_REGION
    )
    planned_runtime_email = (
        f"{gcloud_config['NAME']}@"
        f"{gcloud_config['PROJECT']}.iam.gserviceaccount.com"
    )
    runtime_email = (
        app.get("RUNTIME_SERVICE_ACCOUNT_EMAIL")
        or planned_runtime_email
    )
    internal_caller_email = (
        app.get("INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL")
        or runtime_email
    )
    default_settings = {
        "CONFIG_KIND": CONFIG_KIND,
        "CONFIG_SCHEMA_VERSION": CONFIG_SCHEMA_VERSION,
        "GOOGLE_CLOUD_PROJECT": gcloud_config["PROJECT"],
        "INSTALLER_EMAIL": (
            app.get("INSTALLER_EMAIL")
            or gcloud_config["ACCOUNT"]
        ),
        "DEPLOYER_EMAIL": (
            app.get("DEPLOYER_EMAIL")
            or gcloud_config["ACCOUNT"]
        ),
        "BOOTSTRAP_ADMIN_EMAIL": app.get("BOOTSTRAP_ADMIN_EMAIL", ""),
        "ADMIN_EMAIL": (
            app.get("ADMIN_EMAIL")
            or gcloud_config["ACCOUNT"]
        ),
        "VERSION": version,
        "GIBBERISH": app.get("GIBBERISH", secret_defaults.get("GIBBERISH")),
        "SECRET_KEY": app.get("SECRET_KEY", secret_defaults.get("SECRET_KEY")),
        "AGENT_ACCESS_ENABLED": app.get(
            "AGENT_ACCESS_ENABLED", constants.DEFAULT_AGENT_ACCESS_ENABLED
        ),
        "AGENT_ACCESS_EMAIL": app.get("AGENT_ACCESS_EMAIL")
        or constants.DEFAULT_AGENT_ACCESS_EMAIL,
        "AGENT_ACCESS_NAME": app.get("AGENT_ACCESS_NAME")
        or constants.DEFAULT_AGENT_ACCESS_NAME,
        "AGENT_ACCESS_CODE": app.get("AGENT_ACCESS_CODE")
        or secret_defaults.get("AGENT_ACCESS_CODE"),
        "APP_ENGINE_LOCATION": app_engine_location,
        "RESOURCE_REGION": resource_region,
        "OCR_LOCATION": app.get(
            "OCR_LOCATION", constants.DEFAULT_OCR_LOCATION
        ),
        "AI_MODEL": app.get("AI_MODEL", constants.DEFAULT_AI_MODEL),
        "AI_UTILITY_MODEL": app.get(
            "AI_UTILITY_MODEL", constants.DEFAULT_UTILITY_AI_MODEL
        ),
        "AI_IMAGE_MODEL": app.get(
            "AI_IMAGE_MODEL", constants.DEFAULT_AI_IMAGE_MODEL
        ),
        "AI_LOCATION": app.get("AI_LOCATION", constants.DEFAULT_AI_LOCATION),
        "ANALYTICS": app.get("ANALYTICS", constants.DEFAULT_ANALYTICS_ENABLED),
        "CAPTURE_ERRORS": app.get(
            "CAPTURE_ERRORS", constants.DEFAULT_ERROR_MONITORING_ENABLED
        ),
        "SENTRY_TRACES_SAMPLE_RATE": app.get(
            "SENTRY_TRACES_SAMPLE_RATE",
            constants.DEFAULT_SENTRY_TRACES_SAMPLE_RATE,
        ),
        "SENTRY_PROFILE_SESSION_SAMPLE_RATE": app.get(
            "SENTRY_PROFILE_SESSION_SAMPLE_RATE",
            constants.DEFAULT_SENTRY_PROFILE_SESSION_SAMPLE_RATE,
        ),
        "PUBLIC_MANUAL": app.get(
            "PUBLIC_MANUAL", constants.DEFAULT_PUBLIC_MANUAL
        ),
        "PUBLIC_PAGE_INDEXING": app.get(
            "PUBLIC_PAGE_INDEXING", constants.DEFAULT_PUBLIC_PAGE_INDEXING
        ),
        "SOURCE_URL": app.get(
            "SOURCE_URL", constants.DEFAULT_SOURCE_URL
        ),
        "REDIS_TLS": app.get(
            "REDIS_TLS", constants.DEFAULT_REDIS_TLS_ENABLED
        ),
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": runtime_email,
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": internal_caller_email,
    }
    app.update(default_settings)

    return app


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_config_builders_preserve_inputs_and_generate_independent_documents
# @matrix deploy : app-yaml pdf-preview static-assets
def build_deploy_yaml(app_settings, deployment):
    from config import constants

    from config.deployment import apply_deployment_settings

    app = dict(app_settings)
    deploy = copy.deepcopy(deployment)

    apply_deployment_settings(
        app_config=deploy, app_settings=app, updated_settings=app
    )

    deploy["default_expiration"] = constants.DEFAULT_EXPIRATION
    deploy["handlers"] = copy.deepcopy(constants.APP_HANDLERS)
    runtime_email = str(
        app.get("RUNTIME_SERVICE_ACCOUNT_EMAIL") or ""
    ).strip()
    if not runtime_email:
        raise RuntimeError(
            "RUNTIME_SERVICE_ACCOUNT_EMAIL is required before generating "
            "the App Engine deployment configuration."
        )
    deploy["service_account"] = runtime_email

    return app, deploy


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_config_builders_preserve_inputs_and_generate_independent_documents
# @matrix setup : config-files transactional-state
def build_dev_yaml(dev_settings, test_settings):
    from config import constants

    dev = dict(dev_settings)
    test = dict(test_settings)

    dev["SERVER_NAME"] = dev.get(
        "SERVER_NAME", constants.DEFAULT_SERVER_NAME
    )
    dev["SERVER_PORT"] = dev.get(
        "SERVER_PORT", constants.DEFAULT_DEV_PORT
    )
    test["ADMIN_EMAIL"] = test.get(
        "ADMIN_EMAIL", constants.DEFAULT_ADMIN_EMAIL
    )
    test["ADMIN_NAME"] = test.get(
        "ADMIN_NAME", constants.DEFAULT_ADMIN_NAME
    )
    test["SERVER_NAME"] = test.get(
        "SERVER_NAME", constants.DEFAULT_SERVER_NAME
    )
    test["SERVER_PORT"] = test.get(
        "SERVER_PORT", constants.DEFAULT_TEST_PORT
    )
    test["PREFIX"] = test.get(
        "PREFIX", constants.DEFAULT_TEST_PREFIX
    )

    return dev, test


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_config_builders_preserve_inputs_and_generate_independent_documents
# @matrix setup : config-files transactional-state
def build_index_yaml(existing):
    from config import constants

    indexes = copy.deepcopy(existing)

    indexes.update(copy.deepcopy(constants.INDEX_YAML))

    return indexes


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_config_builders_preserve_inputs_and_generate_independent_documents
# @matrix setup : config-files transactional-state
def build_manifest(app_settings, existing):
    from config import constants
    from runner.deploy import update_manifest

    manifest = copy.deepcopy(existing)
    for k, v in constants.MANIFEST.items():
        manifest[k] = manifest.get(k, copy.deepcopy(v))

    update_manifest(app_settings=app_settings, manifest=manifest)

    return manifest
