# @testable false
# @covered-by config/deployment.py::normalize_deployment_settings
# @reason fallback exception type for deployment validation without app imports
class ConfigDeploymentSettingsError(ValueError):
    """Raised when deployment settings cannot be applied safely."""


# @testable false
# @covered-by config/deployment.py::normalize_deployment_settings
# @reason avoids importing the app package while setup creates config files
def _deployment_settings_error_class():
    try:
        from lagniappe.core.exceptions import DeploymentSettingsError

        return DeploymentSettingsError
    except Exception:
        return ConfigDeploymentSettingsError


# @testable false
# @covered-by config/deployment.py::normalize_deployment_settings
# @reason shared validation detail for deployment integer settings
def _deployment_int(settings, defaults, key, label, min_value=1):
    DeploymentSettingsError = _deployment_settings_error_class()
    value = settings.get(key, defaults[key])
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise DeploymentSettingsError(
            f"{label} must be an integer greater than or equal to {min_value}."
        )

    if parsed < min_value:
        raise DeploymentSettingsError(
            f"{label} must be an integer greater than or equal to {min_value}."
        )

    return str(parsed)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_deployment_settings_normalize_validation
# @matrix config user-settings : app-yaml deployment-settings validation
def normalize_deployment_settings(deployment_settings):
    from config import constants

    DeploymentSettingsError = _deployment_settings_error_class()

    defaults = dict(constants.DEFAULT_DEPLOYMENT_SETTINGS)
    if not deployment_settings:
        return defaults

    scaling_type = deployment_settings.get(
        "DEPLOY_SCALING_TYPE", defaults["DEPLOY_SCALING_TYPE"]
    )
    if scaling_type not in constants.SCALING_TYPES:
        raise DeploymentSettingsError("Scaling type must be automatic or basic.")

    worker_count = _deployment_int(
        deployment_settings, defaults, "DEPLOY_WORKER_COUNT", "Worker count"
    )
    max_instances = _deployment_int(
        deployment_settings, defaults, "DEPLOY_MAX_INSTANCES", "Instance count"
    )
    instance_class = deployment_settings.get(
        "DEPLOY_INSTANCE_CLASS", defaults["DEPLOY_INSTANCE_CLASS"]
    ).upper()
    min_idle_instances = _deployment_int(
        deployment_settings,
        defaults,
        "DEPLOY_MIN_IDLE_INSTANCES",
        "Minimum idle instances",
        min_value=0,
    )
    idle_timeout = deployment_settings.get(
        "DEPLOY_IDLE_TIMEOUT", defaults["DEPLOY_IDLE_TIMEOUT"]
    )

    valid_classes = (
        constants.AUTOMATIC_INSTANCE_CLASSES
        if scaling_type == "automatic"
        else constants.BASIC_INSTANCE_CLASSES
    )
    if instance_class not in valid_classes:
        raise DeploymentSettingsError(
            f"{scaling_type.title()} scaling requires one of: {', '.join(valid_classes)}."
        )

    if scaling_type == "automatic" and int(min_idle_instances) > int(max_instances):
        raise DeploymentSettingsError(
            "Minimum idle instances cannot exceed max instances."
        )

    return {
        "DEPLOY_SCALING_TYPE": scaling_type,
        "DEPLOY_WORKER_COUNT": worker_count,
        "DEPLOY_INSTANCE_CLASS": instance_class,
        "DEPLOY_MAX_INSTANCES": max_instances,
        "DEPLOY_MIN_IDLE_INSTANCES": min_idle_instances,
        "DEPLOY_IDLE_TIMEOUT": idle_timeout,
    }


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_deployment_settings_apply_automatic_scaling_preserves_unowned_app_config
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_deployment_settings_apply_basic_scaling_preserves_unowned_app_config
# @matrix config : app-yaml deployment-settings
def apply_deployment_settings(app_config=None, app_settings=None, updated_settings=None):
    from config import constants

    try:
        from config import SETTINGS
    except ImportError:
        SETTINGS = None

    if updated_settings is None and app_settings is None:
        if SETTINGS is None:
            raise RuntimeError("SETTINGS is required when app config is not provided.")
        deployment_settings = app_config or SETTINGS.APP
        target_app_config = SETTINGS.DEPLOY
        target_app_settings = SETTINGS.APP
    elif updated_settings is None:
        deployment_settings = app_settings
        if app_config is None:
            if SETTINGS is None:
                raise RuntimeError("SETTINGS is required when app config is not provided.")
            target_app_config = SETTINGS.DEPLOY
        else:
            target_app_config = app_config
        target_app_settings = SETTINGS.APP if SETTINGS is not None else {}
    else:
        deployment_settings = updated_settings
        if app_config is None:
            if SETTINGS is None:
                raise RuntimeError("SETTINGS is required when app config is not provided.")
            target_app_config = SETTINGS.DEPLOY
        else:
            target_app_config = app_config
        if app_settings is not None:
            target_app_settings = app_settings
        elif SETTINGS is not None:
            target_app_settings = SETTINGS.APP
        else:
            target_app_settings = {}

    settings = normalize_deployment_settings(deployment_settings)
    target_app_settings.update(settings)

    target_app_config["runtime"] = constants.RUNTIME
    target_app_config["entrypoint"] = (
        f"gunicorn -t {constants.GUNICORN_TIMEOUT_SECONDS} -w "
        f"{settings['DEPLOY_WORKER_COUNT']} -b :$PORT main:app"
    )
    configured_inbound_services = target_app_config.get("inbound_services") or []
    if isinstance(configured_inbound_services, (list, tuple)):
        inbound_services = list(configured_inbound_services)
    else:
        inbound_services = [configured_inbound_services]

    if settings["DEPLOY_SCALING_TYPE"] == "automatic":
        target_app_config.pop("basic_scaling", None)
        target_app_config["instance_class"] = settings["DEPLOY_INSTANCE_CLASS"]
        target_app_config["automatic_scaling"] = {
            "min_idle_instances": settings["DEPLOY_MIN_IDLE_INSTANCES"],
            "max_instances": settings["DEPLOY_MAX_INSTANCES"],
        }
        for service in constants.AUTOMATIC_INBOUND_SERVICES:
            if service not in inbound_services:
                inbound_services.append(service)
        target_app_config["inbound_services"] = inbound_services
    else:
        target_app_config.pop("automatic_scaling", None)
        target_app_config["instance_class"] = settings["DEPLOY_INSTANCE_CLASS"]
        target_app_config["basic_scaling"] = {
            "max_instances": settings["DEPLOY_MAX_INSTANCES"],
            "idle_timeout": settings["DEPLOY_IDLE_TIMEOUT"],
        }
        automatic_services = set(constants.AUTOMATIC_INBOUND_SERVICES)
        inbound_services = [
            service for service in inbound_services if service not in automatic_services
        ]
        if inbound_services:
            target_app_config["inbound_services"] = inbound_services
        else:
            target_app_config.pop("inbound_services", None)

    return target_app_config
