"""Runtime-safe orchestration for application administration."""

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe import Config
    from config.ai_models import ModelOptions

from config.ai_models import discover_model_options
from config.ai_settings import normalize_ai_settings
from config.constants import DEFAULT_DEPLOYMENT_SETTINGS
from config.deployment import normalize_deployment_settings
from lagniappe import CONFIG
from lagniappe.core.tools.ai.settings import runtime_ai_settings
from lagniappe.core.tools.database import migrations as database_migrations
from lagniappe.core.tools.database import site as site_database


def load_deployment_settings(*, config: Config | None = None) -> dict[str, object]:
    """Load normalized deployment settings with live values taking precedence."""
    config = config or CONFIG
    defaults = {
        key: getattr(config, key, value)
        for key, value in DEFAULT_DEPLOYMENT_SETTINGS.items()
    }
    entity = site_database.deployment()
    if entity:
        defaults.update(
            {
                key: value
                for key, value in dict(entity).items()
                if key in DEFAULT_DEPLOYMENT_SETTINGS
            }
        )
    # Read legacy values without rewriting them. New submissions still use the
    # strict worker ceiling in the route-level validation boundary.
    return normalize_deployment_settings(defaults, enforce_worker_limit=False)


def load_ai_settings_payload(settings: Mapping[str, object] | None = None, *, config: Config | None = None) -> tuple[dict[str, object], ModelOptions]:
    """Load normalized runtime AI settings and current model options."""
    config = config or CONFIG
    settings = settings or runtime_ai_settings(config=config)
    model_options = discover_model_options(
        project=config.GOOGLE_CLOUD_PROJECT,
        location=str(settings["AI_LOCATION"]),
        credentials=config.google_credentials,
        current_settings=settings,
    )
    return (
        normalize_ai_settings(
            settings,
            current_settings=settings,
            model_options=model_options,
        ),
        model_options,
    )


def run_site_updates() -> database_migrations.MigrationStatus:
    """Run data migrations and return their complete status report."""
    return database_migrations.run_data_migrations()
