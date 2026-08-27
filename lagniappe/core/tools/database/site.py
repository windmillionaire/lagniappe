"""Datastore persistence for singleton site settings."""

from config.ai_settings import AI_SETTING_KEYS
from config.constants import DEFAULT_DEPLOYMENT_SETTINGS
from config.public_pages import PUBLIC_PAGE_SETTING_KEYS

from .core import DATA, KINDS


# @testable false
# @reason site config persistence is owned by route/E2E workflows
def get_or_create(key):
    """Fetch a site config entity by key, creating it if missing."""
    entity = DATA.datastore.get(key)
    if entity:
        return entity

    entity = DATA.datastore.entity(key=key)
    DATA.datastore.put(entity)
    return entity


# @testable infrastructure
def key(identifier):
    """Build a Datastore key for a site config entry."""
    return DATA.datastore.key(KINDS.site.value, identifier)


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @matrix admin : metadata public-preview
def image():
    """Fetch the stored site image metadata entity."""
    return DATA.datastore.get(key("image"))


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_deployment_form_saves_and_updates_summary
# @matrix admin : deployment-settings metadata
def deployment():
    """Fetch the stored deployment settings metadata entity."""
    return DATA.datastore.get(key("deployment"))


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_ai_form_saves_current_models_through_route
# @matrix admin : ai-settings metadata
def ai():
    """Fetch the stored AI model settings metadata entity."""
    return DATA.datastore.get(key("ai"))


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_save_site_public_pages_persists_canonical_payload
# @matrix admin : metadata public-page-indexing
def public_pages():
    """Fetch the stored public-page discovery settings entity."""
    return DATA.datastore.get(key("public_pages"))


# @testable true
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
# @tests tests_unit/test_018_database_assets.py::test_save_site_image_persists_version_without_mutating_input
# @matrix admin : metadata site-image-upload
def save_image(data):
    """Persist site image metadata and increment its version."""
    image_key = key("image")
    entity = DATA.datastore.get(image_key)
    if not entity:
        entity = DATA.datastore.entity(key=image_key)

    version = int(entity.get("version", 0)) + 1
    entity.update({**data, "version": version})
    DATA.datastore.put(entity)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_save_site_deployment_persists_canonical_payload_and_prunes_old_keys
# @matrix admin : deployment-settings metadata
def save_deployment(data):
    """Persist canonical deployment settings and increment their version."""
    deployment_key = key("deployment")
    entity = DATA.datastore.get(deployment_key)
    if not entity:
        entity = DATA.datastore.entity(key=deployment_key)

    version = int(entity.get("version", 0)) + 1
    canonical = {
        name: value for name, value in data.items() if name in DEFAULT_DEPLOYMENT_SETTINGS
    }
    entity.clear()
    entity.update({**canonical, "version": version})
    DATA.datastore.put(entity)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_save_site_ai_persists_canonical_payload_and_prunes_old_keys
# @matrix admin : ai-settings metadata
def save_ai(data):
    """Persist canonical AI settings and increment their version."""
    ai_key = key("ai")
    entity = DATA.datastore.get(ai_key)
    if not entity:
        entity = DATA.datastore.entity(key=ai_key)

    version = int(entity.get("version", 0)) + 1
    canonical = {name: value for name, value in data.items() if name in AI_SETTING_KEYS}
    entity.clear()
    entity.update({**canonical, "version": version})
    DATA.datastore.put(entity)


# @testable true
# @tests tests_unit/test_018_database_assets.py::test_save_site_public_pages_persists_canonical_payload
# @matrix admin : metadata public-page-indexing
def save_public_pages(data):
    """Persist canonical public-page settings and increment their version."""
    settings_key = key("public_pages")
    entity = DATA.datastore.get(settings_key)
    if not entity:
        entity = DATA.datastore.entity(key=settings_key)

    version = int(entity.get("version", 0)) + 1
    canonical = {
        name: value for name, value in data.items() if name in PUBLIC_PAGE_SETTING_KEYS
    }
    entity.clear()
    entity.update({**canonical, "version": version})
    DATA.datastore.put(entity)
