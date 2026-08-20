# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_ai_settings_applies_saved_app_config
# @features setup
# @dimensions ai-settings datastore
def get_ai_settings():
    from installer.utils import ensure_datastore_dependency
    from installer.image import DATASTORE_TIMEOUT, get_datastore_client
    from installer import FORMATTER

    f = FORMATTER.initialize()

    ai_entity = None
    try:
        ensure_datastore_dependency()
        ds = get_datastore_client()
        ai_key = ds.key("site", "ai")
        ai_entity = ds.get(ai_key, timeout=DATASTORE_TIMEOUT)
    except Exception as e:
        print(f.warning(f"Could not check Datastore for AI settings: {e}"))
        print(f.warning("Continuing update with existing AI model settings."))

    return ai_entity


from config.ai_settings import (
    apply_ai_settings as apply_ai_settings,
    normalize_ai_settings as normalize_ai_settings,
)
