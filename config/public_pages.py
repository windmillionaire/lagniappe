"""Validation and application helpers for public-page discovery settings."""


from collections.abc import Mapping, MutableMapping


PUBLIC_PAGE_SETTING_KEYS = ("PUBLIC_PAGE_INDEXING",)


class ConfigPublicPageSettingsError(ValueError):
    """Raised when public-page settings cannot be applied safely."""


def _boolean(value: object) -> bool:
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


def normalize_public_page_settings(
    settings: Mapping[str, object] | None = None,
    current_settings: Mapping[str, object] | None = None,
) -> dict[str, bool]:
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


def apply_public_page_settings(
    app_settings: MutableMapping[str, object] | None = None,
    updated_settings: Mapping[str, object] | None = None,
) -> MutableMapping[str, object]:
    """Apply canonical public-page settings to SETTINGS.APP or a mapping."""
    try:
        from config import SETTINGS
    except ImportError:
        SETTINGS = None

    if app_settings is None:
        if SETTINGS is None:
            raise RuntimeError("SETTINGS is required when app settings are not provided.")
        target = SETTINGS.APP
        settings = target if updated_settings is None else updated_settings
    elif updated_settings is None:
        target = SETTINGS.APP if SETTINGS is not None else app_settings
        settings = app_settings
    else:
        target = app_settings
        settings = updated_settings

    target.update(normalize_public_page_settings(settings, current_settings=settings))
    return target
