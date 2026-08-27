"""Read public-page settings saved by the deployed application."""


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_upgrade_restore_public_page_settings_applies_saved_app_config
# @matrix setup : datastore public-page-indexing
def get_public_page_settings():
    from installer.utils import ensure_datastore_dependency
    from installer.image import DATASTORE_TIMEOUT, get_datastore_client
    from installer import FORMATTER

    formatter = FORMATTER.initialize()
    entity = None
    try:
        ensure_datastore_dependency()
        datastore = get_datastore_client()
        entity = datastore.get(
            datastore.key("site", "public_pages"),
            timeout=DATASTORE_TIMEOUT,
        )
    except Exception as error:
        print(
            formatter.warning(
                f"Could not check Datastore for public-page settings: {error}"
            )
        )
        print(
            formatter.warning(
                "Continuing update with existing public-page settings."
            )
        )
    return entity


from config.public_pages import (  # noqa: E402
    apply_public_page_settings as apply_public_page_settings,
    normalize_public_page_settings as normalize_public_page_settings,
)
