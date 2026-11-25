"""Redis key templates and search index enums for the cache layer."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...entities.entity import Entity
    from ...restrictions import QueryHashes

import hashlib
import json
from enum import Enum

from lagniappe import CONFIG

from ...definitions.default import DefaultEnum
from ...restrictions import Restriction

SEARCH_SCORE_FIELD = "search_score"
HELP_PREFIX = f"{CONFIG.PREFIX}help:"


class Keys(Enum):
    """Redis key templates for indexes, hashes, and imports."""

    SEARCH_INDEX = f"{CONFIG.PREFIX}INDEX"
    SEARCH_INDEX_LOCK = f"{CONFIG.PREFIX}INDEX:UPGRADE"
    HELP_READY = f"{CONFIG.PREFIX}HELP:READY:{{}}"
    HELP_LOCK = f"{CONFIG.PREFIX}HELP:POPULATE:{{}}"
    JSON_INDEX = f"{CONFIG.PREFIX}JSON_INDEX"
    RESTRICTION_PENDING = f"{CONFIG.PREFIX}RESTRICTION_PENDING"
    ENTITY_HASHES = f"{CONFIG.PREFIX}HASHES"
    AI_RESOURCE_INVENTORY = f"{CONFIG.PREFIX}AI:RESOURCES:{{}}"
    FILTER = f"{CONFIG.PREFIX}JSON:{{}}:{{}}"
    PROJECT_FILTER_CHANGES = f"{CONFIG.PREFIX}PROJECT_FILTER_CHANGES"
    RATE_LIMIT = f"{CONFIG.PREFIX}RATE_LIMIT:{{}}:{{}}"
    NOTIFICATIONS = f"{CONFIG.PREFIX}NOTIFICATIONS:{{}}"
    NOTIFICATION_EPOCH = f"{CONFIG.PREFIX}NOTIFICATIONS:EPOCH:{{}}"
    OPERATION = f"{CONFIG.PREFIX}OPERATIONS:{{}}"
    OWNER_PROJECTION = f"{CONFIG.PREFIX}OWNER_PROJECTION"
    PUBLIC_DIRECTORY = f"{CONFIG.PREFIX}PUBLIC:DIRECTORY"
    PUBLIC_DISCOVERY_EPOCH = f"{CONFIG.PREFIX}PUBLIC:DISCOVERY:EPOCH"
    SITEMAP = f"{CONFIG.PREFIX}PUBLIC:SITEMAP"

    def key(self, entity: Entity) -> str:
        return self.value.format(entity.hash)

    def access_key(self, entity: Entity, access: QueryHashes) -> str:
        values = "models" if Restriction.is_unrestricted(access) else access
        access_hash = hashlib.md5(json.dumps(sorted(values)).encode()).hexdigest()
        return self.value.format(entity.hash, access_hash)


class Sync(Enum):
    """Redis key templates for revisioned documents and expiring presence."""

    DOCUMENTS = f"{CONFIG.PREFIX}SYNC:DOCUMENTS:{{}}"
    PRESENCE = f"{CONFIG.PREFIX}SYNC:PRESENCE:{{}}"
    CLIENTS = f"{CONFIG.PREFIX}SYNC:CLIENTS"

    def key(self, key: str) -> str:
        return self.value.format(key)


class Search(Enum, metaclass=DefaultEnum):
    """Redis key templates for per-kind entity search entries."""

    form = f"{CONFIG.PREFIX}form:{{}}"
    category = f"{CONFIG.PREFIX}category:{{}}"
    project = f"{CONFIG.PREFIX}project:{{}}"
    page = f"{CONFIG.PREFIX}page:{{}}"
    task = f"{CONFIG.PREFIX}task:{{}}"
    user = f"{CONFIG.PREFIX}user:{{}}"
    model = f"{CONFIG.PREFIX}model:{{}}"
    group = f"{CONFIG.PREFIX}group:{{}}"
    file = f"{CONFIG.PREFIX}file:{{}}"

    DEFAULT = None

    def key(self, entity: Entity) -> str | None:
        if not self.value:
            return None

        return self.value.format(entity.urlsafe_key)
