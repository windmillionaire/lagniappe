"""Location normalization for App Engine and regional Google resources."""


_APP_ENGINE_LOCATION_ALIASES = {
    "europe-west1": "europe-west",
    "us-central1": "us-central",
}
_RESOURCE_REGION_ALIASES = {
    app_engine_location: resource_region
    for resource_region, app_engine_location in _APP_ENGINE_LOCATION_ALIASES.items()
}


# @testable true
# @tests tests_tooling/test_003_config.py::test_google_location_aliases_keep_app_engine_and_regional_resources_distinct
# @features config setup
# @dimensions app-engine-location resource-region compatibility
def normalize_app_engine_location(value):
    """Return the App Engine spelling for a configured Google location."""
    normalized = str(value or "").strip().lower()
    return _APP_ENGINE_LOCATION_ALIASES.get(normalized, normalized)


# @testable true
# @tests tests_tooling/test_003_config.py::test_google_location_aliases_keep_app_engine_and_regional_resources_distinct
# @features config setup
# @dimensions app-engine-location resource-region compatibility
def normalize_resource_region(value):
    """Return the regional-service spelling for a configured Google location."""
    normalized = str(value or "").strip().lower()
    return _RESOURCE_REGION_ALIASES.get(normalized, normalized)
