"""Exercise setup-time configuration imports without credentials or provider calls."""

from unittest.mock import patch


def check_bootstrap() -> None:
    from config import Environment, RuntimeSettings
    from config.ai_models import discover_model_options
    from config.ai_settings import normalize_ai_settings
    from config.storage import configure_storage_bucket

    assert callable(discover_model_options)
    assert callable(configure_storage_bucket)
    settings = RuntimeSettings(Environment.TESTING, {
        "CONFIG_KIND": "lagniappe-settings",
        "CONFIG_SCHEMA_VERSION": 3,
        "GOOGLE_CLOUD_PROJECT": "project-1",
        "VERSION": "1.0",
        "GIBBERISH": "bucket-seed",
        "RUNTIME_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL": "runtime@project-1.iam.gserviceaccount.com",
        "APP_ENGINE_LOCATION": "us-central",
        "RESOURCE_REGION": "us-central1",
    })
    with patch("config.load_runtime_settings", return_value=settings):
        from lagniappe.core.exceptions import AISettingsError

        try:
            normalize_ai_settings({"AI_AUTO_EXECUTE": "invalid"})
        except AISettingsError:
            return
        raise AssertionError("Invalid settings must raise the application's AISettingsError.")


if __name__ == "__main__":
    check_bootstrap()
