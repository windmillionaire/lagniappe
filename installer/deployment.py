# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_deployment_settings_applies_saved_app_config
# @matrix setup : datastore deployment-settings
def get_deployment_settings():
    from installer.utils import ensure_datastore_dependency
    from installer.image import DATASTORE_TIMEOUT, get_datastore_client
    from installer import FORMATTER

    f = FORMATTER.initialize()

    deployment_entity = None
    try:
        ensure_datastore_dependency()
        ds = get_datastore_client()
        deployment_key = ds.key("site", "deployment")
        deployment_entity = ds.get(deployment_key, timeout=DATASTORE_TIMEOUT)
    except Exception as e:
        print(f.warning(f"Could not check Datastore for deployment settings: {e}"))
        print(f.warning("Continuing update with existing app.yaml settings."))

    return deployment_entity


from config.deployment import (
    apply_deployment_settings as apply_deployment_settings,
    normalize_deployment_settings as normalize_deployment_settings,
)
