"""Datastore persistence for singleton site settings."""

import uuid
from collections.abc import Mapping

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key

from config.ai_settings import AI_PERSISTED_SETTING_KEYS
from config.constants import DEFAULT_DEPLOYMENT_SETTINGS
from config.public_pages import PUBLIC_PAGE_SETTING_KEYS

from .core import DATA, KINDS


def get_or_create(key: Key) -> DatastoreEntity:
    """Fetch a site config entity by key, creating it if missing."""
    entity = DATA.datastore.get(key)
    if entity:
        return entity

    entity = DATA.datastore.entity(key=key)
    DATA.datastore.put(entity)
    return entity


def key(identifier: str) -> Key:
    """Build a Datastore key for a site config entry."""
    return DATA.datastore.key(KINDS.site.value, identifier)


def image() -> DatastoreEntity | None:
    """Fetch the stored site image metadata entity."""
    return DATA.datastore.get(key("image"))


def deployment() -> DatastoreEntity | None:
    """Fetch the stored deployment settings metadata entity."""
    return DATA.datastore.get(key("deployment"))


def ai() -> DatastoreEntity | None:
    """Fetch the stored AI model settings metadata entity."""
    return DATA.datastore.get(key("ai"))


def public_pages() -> DatastoreEntity | None:
    """Fetch the stored public-page discovery settings entity."""
    return DATA.datastore.get(key("public_pages"))


def save_image(data: Mapping[str, object]) -> None:
    """Persist site image metadata and increment its version."""
    image_key = key("image")
    entity = DATA.datastore.get(image_key)
    if not entity:
        entity = DATA.datastore.entity(key=image_key)

    version = int(entity.get("version", 0)) + 1
    entity.update({**data, "version": version})
    DATA.datastore.put(entity)


def save_deployment(data: Mapping[str, object]) -> None:
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


def save_ai(data: Mapping[str, object]) -> None:
    """Persist canonical AI settings and increment their version."""
    ai_key = key("ai")
    entity = DATA.datastore.get(ai_key)
    if not entity:
        entity = DATA.datastore.entity(key=ai_key)

    version = int(entity.get("version", 0)) + 1
    canonical = {
        name: value for name, value in data.items() if name in AI_PERSISTED_SETTING_KEYS
    }
    entity.clear()
    entity.update({**canonical, "version": version})
    DATA.datastore.put(entity)


def save_public_pages(data: Mapping[str, object]) -> None:
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


def bump_fingerprint(identifier: str) -> str:
    """Advance the stored site fingerprint for a singleton channel such as home."""
    record_key = key(identifier)
    entity = DATA.datastore.get(record_key)
    if not entity:
        entity = DATA.datastore.entity(key=record_key)
    fingerprint = str(uuid.uuid4())
    entity["fingerprint"] = fingerprint
    DATA.datastore.put(entity)
    return fingerprint
