"""Shared fail-closed projection of the canonical site owner."""

from contextvars import ContextVar
import unicodedata

from config.datastore import encode_urlsafe_key
from lagniappe import CONFIG

from .core import cache
from .keys import Keys


OWNER_SCHEMA_VERSION = "1"
_REQUEST_OWNER = ContextVar("owner_projection", default=None)


# @testable true
# @tests tests_unit/test_027d_collaboration.py::test_owner_projection_normalizes_and_round_trips
# @pair owner-projection:normalization
def normalize_owner_name(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(value.casefold().split())


# @testable true
# @tests tests_unit/test_027d_collaboration.py::test_owner_projection_normalizes_and_round_trips
# @pair owner-projection:request-memo
def clear_request_owner_projection():
    _REQUEST_OWNER.set(None)


# @testable false
# @covered-by lagniappe/core/tools/cache/owner.py::get_owner_projection
# @reason Redis byte normalization is internal to projection reads
def _decode_map(values):
    return {
        (key.decode() if isinstance(key, bytes) else str(key)): (
            value.decode() if isinstance(value, bytes) else str(value)
        )
        for key, value in (values or {}).items()
    }


# @testable false
# @covered-by lagniappe/core/tools/cache/owner.py::get_owner_projection
# @reason schema validation is internal to projection reads and repair
def _project(values):
    values = _decode_map(values)
    if values.get("schema") != OWNER_SCHEMA_VERSION:
        return None
    if not values.get("key") or not values.get("page_key"):
        return None
    return {
        "key": values["key"],
        "page_key": values["page_key"],
        "hash": values.get("hash", ""),
        "name": values.get("name", ""),
        "normalized_name": values.get("normalized_name", ""),
        "allow_messages_and_mentions": values.get(
            "allow_messages_and_mentions"
        )
        == "1",
        "allow_task_assignments": values.get("allow_task_assignments") == "1",
        "revision": int(values.get("revision") or 0),
    }


# @testable false
# @covered-by lagniappe/core/tools/cache/owner.py::update_owner_projection
# @reason mapping construction is asserted through the published projection
def _mapping(user, revision):
    page_key = encode_urlsafe_key(user.properties.page.key)
    return {
        "schema": OWNER_SCHEMA_VERSION,
        "key": user.urlsafe_key,
        "page_key": page_key,
        "hash": user.hash or "",
        "name": user.name or "",
        "normalized_name": normalize_owner_name(user.name),
        "allow_messages_and_mentions": (
            "1" if user.allow_messages_and_mentions else "0"
        ),
        "allow_task_assignments": "1" if user.allow_task_assignments else "0",
        "revision": str(revision),
    }


# @testable true
# @tests tests_unit/test_027d_collaboration.py::test_owner_projection_normalizes_and_round_trips
# @matrix owner-projection : fail-closed revision
def update_owner_projection(*users):
    """Publish an owner row only after its durable mutation has committed."""
    owner = next((user for user in users if getattr(user, "is_owner", False)), None)
    if not owner or not owner.properties.page.key:
        return None
    current = _project(cache.redis.hgetall(Keys.OWNER_PROJECTION.value))
    projection = _mapping(owner, (current or {}).get("revision", 0) + 1)
    cache.redis.hset(Keys.OWNER_PROJECTION.value, mapping=projection)
    projected = _project(projection)
    _REQUEST_OWNER.set(projected)
    return projected


# @testable true
# @tests tests_unit/test_027d_collaboration.py::test_owner_projection_normalizes_and_round_trips
# @matrix owner-projection : repair request-memo
def get_owner_projection(*, repair=True):
    """Read the request memo/Redis projection and repair from User on a miss."""
    memo = _REQUEST_OWNER.get()
    if memo:
        return memo
    projected = _project(cache.redis.hgetall(Keys.OWNER_PROJECTION.value))
    if projected or not repair:
        _REQUEST_OWNER.set(projected)
        return projected

    from lagniappe.core.entities import Entities
    from lagniappe.core.definitions import Fetch
    from lagniappe.core.tools.database import get as database_get

    raw = database_get.user(CONFIG.ADMIN_EMAIL)
    owner = Entities.fetch_one(raw, request=Fetch.root()) if raw else None
    if owner and not owner.is_owner and not owner.db.get("owner"):
        # Schema-compatible repair for an old canonical row that predates the
        # stored flag. IsOwner rejects every noncanonical email.
        owner.is_owner = True
        owner.save()
    if not owner or not owner.is_owner:
        return None
    return update_owner_projection(owner)


# @testable true
# @tests tests_unit/test_027d_collaboration.py::test_owner_projection_normalizes_and_round_trips
# @pair owner-projection:selector-shape
def owner_search_result(projection):
    """Return the selector shape used by user facets."""
    if not projection:
        return None
    details = {
        "id": projection["page_key"],
        "recipient_key": projection["key"],
        "hash": projection.get("hash"),
        "kind": "user",
        "name": projection.get("name"),
    }
    return {
        "id": projection["page_key"],
        "kind": "user",
        "name": projection.get("name"),
        "details": details,
    }
