"""Exercise setup-time configuration imports without credentials or provider calls."""

from pathlib import Path
from unittest.mock import patch

import yaml


def check_bootstrap() -> None:
    from config import Environment, RuntimeSettings
    from config.ai_models import discover_model_options
    from config.ai_settings import normalize_ai_settings
    from config.storage import configure_storage_bucket

    assert callable(discover_model_options)
    assert callable(configure_storage_bucket)
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures/offline-runtime/config/files/lagniappe_settings.yaml"
    )
    settings = RuntimeSettings(
        Environment.TESTING, yaml.safe_load(fixture.read_text(encoding="utf-8"))
    )
    with patch("config.load_runtime_settings", return_value=settings):
        from lagniappe.core.exceptions import AISettingsError

        try:
            normalize_ai_settings({"AI_AUTO_EXECUTE": "invalid"})
        except AISettingsError:
            return
        raise AssertionError("Invalid settings must raise the application's AISettingsError.")


if __name__ == "__main__":
    check_bootstrap()
