"""Runtime-safe orchestration for application administration."""

from config.ai_models import discover_model_options
from config.ai_settings import normalize_ai_settings
from config.constants import DEFAULT_DEPLOYMENT_SETTINGS
from config.deployment import normalize_deployment_settings
from lagniappe import CONFIG
from lagniappe.core.tools.ai.settings import runtime_ai_settings
from lagniappe.core.tools.database import migrations as database_migrations
from lagniappe.core.tools.database import site as site_database
# @testable true
# @tests tests_unit/test_026_site_admin.py::test_deployment_settings_merge_live_values_over_runtime_defaults
# @matrix admin : config deployment-settings metadata
def load_deployment_settings(*, config=None):
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
    return normalize_deployment_settings(defaults)


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_ai_settings_payload_normalizes_runtime_settings_against_discovery
# @matrix admin : ai-settings config metadata
def load_ai_settings_payload(settings=None, *, config=None):
    """Load normalized runtime AI settings and current model options."""
    config = config or CONFIG
    settings = settings or runtime_ai_settings(config=config)
    model_options = discover_model_options(
        project=config.GOOGLE_CLOUD_PROJECT,
        location=settings["AI_LOCATION"],
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


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_site_updates_return_the_migration_report
# @matrix admin : audit site-update
def run_site_updates():
    """Run data migrations and return their complete status report."""
    return database_migrations.run_data_migrations()
