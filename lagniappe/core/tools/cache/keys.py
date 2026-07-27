"""Redis key templates and search index enums for the cache layer."""

import hashlib
import json
from enum import Enum

from lagniappe import CONFIG

from ...definitions import DefaultEnum, Restriction

SEARCH_SCORE_FIELD = "search_score"


class Keys(Enum):
    """Redis key templates for indexes, hashes, and imports."""

    SEARCH_INDEX = f"{CONFIG.PREFIX}INDEX"
    JSON_INDEX = f"{CONFIG.PREFIX}JSON_INDEX"
    ENTITY_HASHES = f"{CONFIG.PREFIX}HASHES"
    AI_RESOURCE_INVENTORY = f"{CONFIG.PREFIX}AI:RESOURCES:{{}}"
    FILTER = f"{CONFIG.PREFIX}JSON:{{}}:{{}}"
    RATE_LIMIT = f"{CONFIG.PREFIX}RATE_LIMIT:{{}}:{{}}"

    # @testable infrastructure
    def key(self, entity):
        return self.value.format(entity.hash)

    # @testable infrastructure
    def access_key(self, entity, access):
        access = "models" if Restriction.is_unrestricted(access) else access
        access_hash = hashlib.md5(json.dumps(sorted(access)).encode()).hexdigest()
        return self.value.format(entity.hash, access_hash)


class Sync(Enum):
    """Redis key templates for sync state.

    ``WIDGET`` registrations target a specific syncable widget (e.g. the form
    or document on a page) and drive update broadcasts. ``ENTITY`` viewers
    target the owning entity and drive delete broadcasts to anyone looking at
    the entity in any widget.
    """

    WIDGET = f"{CONFIG.PREFIX}SYNC:WIDGET:{{}}"
    ENTITY = f"{CONFIG.PREFIX}SYNC:ENTITY:{{}}"
    STATE = f"{CONFIG.PREFIX}SYNC:STATE"
    USERS = f"{CONFIG.PREFIX}SYNC:USERS"

    # @testable infrastructure
    def key(self, key):
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

    # @testable infrastructure
    def key(self, entity):
        if not self.value:
            return None

        return self.value.format(entity.urlsafe_key)
