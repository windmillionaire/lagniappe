"""Validation and application helpers for AI model settings."""


AI_SETTING_KEYS = ("AI_MODEL", "AI_UTILITY_MODEL", "AI_IMAGE_MODEL", "AI_LOCATION")


# @testable false
# @covered-by config/ai_settings.py::normalize_ai_settings
# @reason fallback exception type for setup-time validation without app imports
class ConfigAISettingsError(ValueError):
    """Raised when AI settings cannot be applied safely."""


# @testable false
# @covered-by config/ai_settings.py::normalize_ai_settings
# @reason avoids importing the app package while setup creates config files
def _ai_settings_error_class():
    try:
        from lagniappe.core.exceptions import AISettingsError

        return AISettingsError
    except Exception:
        return ConfigAISettingsError


# @testable false
# @covered-by config/ai_settings.py::normalize_ai_settings
# @reason default extraction covered through public normalization tests
def _default_settings(current_settings=None):
    from config import constants

    current_settings = current_settings or {}
    return {
        "AI_MODEL": current_settings.get("AI_MODEL", constants.DEFAULT_AI_MODEL),
        "AI_UTILITY_MODEL": current_settings.get(
            "AI_UTILITY_MODEL",
            constants.DEFAULT_UTILITY_AI_MODEL,
        ),
        "AI_IMAGE_MODEL": current_settings.get(
            "AI_IMAGE_MODEL",
            constants.DEFAULT_AI_IMAGE_MODEL,
        ),
        "AI_LOCATION": current_settings.get("AI_LOCATION", constants.DEFAULT_AI_LOCATION),
    }


# @testable false
# @covered-by config/ai_settings.py::normalize_ai_settings
# @reason validation branch covered through public normalization tests
def _validate_model(value, kind, model_options, current_value, label):
    from config.ai_models import known_model_ids

    AISettingsError = _ai_settings_error_class()
    valid_ids = known_model_ids(model_options, kind=kind)
    if value not in valid_ids and value != current_value:
        raise AISettingsError(f"{label} must be one of the available {kind} models.")


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_settings_normalize_validates_models_and_keeps_current_custom
# @matrix ai : custom-current model-settings validation
def normalize_ai_settings(ai_settings=None, current_settings=None, model_options=None):
    """Return canonical AI settings after validating model names and location."""
    from config import constants
    from config.ai_models import discover_model_options

    AISettingsError = _ai_settings_error_class()
    defaults = _default_settings(current_settings)
    incoming = dict(ai_settings or {})
    values = {
        key: str(incoming.get(key, defaults[key]) or defaults[key]).strip()
        for key in AI_SETTING_KEYS
    }

    if values["AI_LOCATION"] != constants.DEFAULT_AI_LOCATION:
        raise AISettingsError("AI endpoint must be global.")

    if model_options is None:
        model_options = discover_model_options(current_settings=defaults, use_cache=False)

    _validate_model(
        values["AI_MODEL"],
        "text",
        model_options,
        defaults["AI_MODEL"],
        "Primary model",
    )
    _validate_model(
        values["AI_UTILITY_MODEL"],
        "text",
        model_options,
        defaults["AI_UTILITY_MODEL"],
        "Utility model",
    )
    _validate_model(
        values["AI_IMAGE_MODEL"],
        "image",
        model_options,
        defaults["AI_IMAGE_MODEL"],
        "Image model",
    )

    return values


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_ai_settings_apply_preserves_unowned_app_config
# @matrix config : ai-settings app-yaml
def apply_ai_settings(app_settings=None, updated_settings=None):
    """Apply canonical AI settings to SETTINGS.APP or the provided mapping."""
    try:
        from config import SETTINGS
    except ImportError:
        SETTINGS = None

    if updated_settings is None and app_settings is None:
        if SETTINGS is None:
            raise RuntimeError("SETTINGS is required when app settings are not provided.")
        target = SETTINGS.APP
        settings = target
    elif updated_settings is None:
        target = SETTINGS.APP if SETTINGS is not None else app_settings
        settings = app_settings
    else:
        target = app_settings if app_settings is not None else SETTINGS.APP
        settings = updated_settings

    current_settings = settings if settings is not target else target
    normalized = normalize_ai_settings(settings, current_settings=current_settings)
    target.update(normalized)
    return target
