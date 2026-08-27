"""Validation and application helpers for public-page discovery settings."""


PUBLIC_PAGE_SETTING_KEYS = ("PUBLIC_PAGE_INDEXING",)


# @testable false
# @covered-by config/public_pages.py::normalize_public_page_settings
# @reason setup-safe validation type is exercised through the public normalizer
class ConfigPublicPageSettingsError(ValueError):
    """Raised when public-page settings cannot be applied safely."""


# @testable false
# @covered-by config/public_pages.py::normalize_public_page_settings
# @reason private coercion is exercised through the public normalizer
def _boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    normalized = str(value or "").strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ConfigPublicPageSettingsError(
        "Public-page indexing must be enabled or disabled."
    )


# @testable true
# @tests tests_tooling/test_003_config.py::test_public_page_settings_normalize_boolean_values
# @matrix config : public-page-indexing validation
def normalize_public_page_settings(settings=None, current_settings=None):
    """Return the canonical public-page discovery settings."""
    from config import constants

    incoming = dict(settings or {})
    current = dict(current_settings or {})
    default = current.get(
        "PUBLIC_PAGE_INDEXING",
        constants.DEFAULT_PUBLIC_PAGE_INDEXING,
    )
    return {
        "PUBLIC_PAGE_INDEXING": _boolean(
            incoming.get("PUBLIC_PAGE_INDEXING", default)
        )
    }


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_public_page_settings_apply_preserves_unowned_app_config
# @matrix config : app-yaml public-page-indexing
def apply_public_page_settings(app_settings=None, updated_settings=None):
    """Apply canonical public-page settings to SETTINGS.APP or a mapping."""
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
    target.update(
        normalize_public_page_settings(
            settings,
            current_settings=current_settings,
        )
    )
    return target
