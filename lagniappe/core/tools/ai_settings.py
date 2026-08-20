"""Runtime resolution for application AI settings."""

import logging

from config import constants
from lagniappe import CONFIG

from . import database


LOGGER = logging.getLogger(__name__)
RUNTIME_AI_SETTING_KEYS = (
    "AI_MODEL",
    "AI_UTILITY_MODEL",
    "AI_IMAGE_MODEL",
    "AI_LOCATION",
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_runtime_settings_override_deployment_defaults
# @features ai
# @dimensions model-routing runtime-settings deployment-fallback
def runtime_ai_settings(config=CONFIG):
    """Return live site AI settings over deployment-configured fallbacks."""
    settings = {
        "AI_MODEL": getattr(config, "AI_MODEL", constants.DEFAULT_AI_MODEL),
        "AI_UTILITY_MODEL": getattr(
            config,
            "AI_UTILITY_MODEL",
            constants.DEFAULT_UTILITY_AI_MODEL,
        ),
        "AI_IMAGE_MODEL": getattr(
            config,
            "AI_IMAGE_MODEL",
            constants.DEFAULT_AI_IMAGE_MODEL,
        ),
        "AI_LOCATION": getattr(
            config,
            "AI_LOCATION",
            constants.DEFAULT_AI_LOCATION,
        ),
    }
    try:
        persisted = database.get.site_ai()
    except Exception:
        LOGGER.debug(
            "Unable to read live AI settings; using deployment configuration.",
            exc_info=True,
        )
        return settings

    if persisted:
        settings.update(
            {
                key: persisted[key]
                for key in RUNTIME_AI_SETTING_KEYS
                if persisted.get(key)
            }
        )
    return settings
