"""Revisioned Redis caches for anonymous public discovery surfaces."""

import json

from redis.exceptions import WatchError

from lagniappe.core.exceptions import capture

from .core import cache
from .keys import Keys


PUBLIC_DIRECTORY_SCHEMA = 1
PUBLIC_DIRECTORY_TTL_SECONDS = 15 * 60
SITEMAP_TTL_SECONDS = 60 * 60
PUBLIC_DISCOVERY_EPOCH_TTL_SECONDS = 7 * 24 * 60 * 60


# @testable false
# @covered-by lagniappe/core/tools/cache/public_discovery.py::cached_sitemap
# @covered-by lagniappe/core/tools/cache/public_discovery.py::invalidate_public_discovery
# @reason cache variants are exercised through cache publication and invalidation
def _sitemap_cache_key(public_manual):
    return f"{Keys.SITEMAP.value}:MANUAL:{int(bool(public_manual))}"


# @testable false
# @covered-by lagniappe/core/tools/cache/public_discovery.py::cached_public_directory
# @reason malformed cache rejection is exercised through the public cache reader
def _decode_directory(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        snapshot = json.loads(value)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema") != PUBLIC_DIRECTORY_SCHEMA
        or not isinstance(snapshot.get("site_indexing"), bool)
        or not isinstance(snapshot.get("groups"), list)
    ):
        return None
    for group in snapshot["groups"]:
        if (
            not isinstance(group, dict)
            or not isinstance(group.get("id"), str)
            or not isinstance(group.get("name"), str)
            or not isinstance(group.get("pages"), list)
        ):
            return None
        for page in group["pages"]:
            if (
                not isinstance(page, dict)
                or not isinstance(page.get("path"), str)
                or not isinstance(page.get("title"), str)
                or (
                    page.get("description") is not None
                    and not isinstance(page.get("description"), str)
                )
            ):
                return None
    return snapshot


# @testable false
# @covered-by lagniappe/core/tools/cache/public_discovery.py::cached_public_directory
# @covered-by lagniappe/core/tools/cache/public_discovery.py::cached_sitemap
# @reason shared revision publication is covered through both public cache APIs
def _cached_revision(key, builder, *, ttl, encode, decode, operation):
    try:
        cached = cache.redis.get(key)
    except Exception as error:
        capture(error, context={"operation": f"{operation}-read"})
        return builder()
    if cached:
        decoded = decode(cached)
        if decoded is not None:
            return decoded

    missing = object()
    for _attempt in range(2):
        value = missing
        builder_failed = False
        try:
            with cache.redis.pipeline() as pipe:
                pipe.watch(Keys.PUBLIC_DISCOVERY_EPOCH.value)
                try:
                    value = builder()
                except Exception:
                    builder_failed = True
                    raise
                pipe.multi()
                pipe.setex(key, ttl, encode(value))
                pipe.execute()
                return value
        except WatchError:
            continue
        except Exception as error:
            if builder_failed:
                raise
            capture(error, context={"operation": f"{operation}-publish"})
            return value if value is not missing else builder()
    return builder()


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_public_directory_cache_only_publishes_for_unchanged_epoch
# @tests tests_unit/test_017_cache_query.py::test_public_directory_publish_failure_does_not_repeat_durable_build
# @matrix cache public-directory : durable-fallback epoch json redis-failure redis-race single-rebuild ttl
def cached_public_directory(builder):
    """Return a privacy-bounded public catalog, rebuilding it after its TTL."""
    return _cached_revision(
        Keys.PUBLIC_DIRECTORY.value,
        builder,
        ttl=PUBLIC_DIRECTORY_TTL_SECONDS,
        encode=lambda value: json.dumps(value, separators=(",", ":"), sort_keys=True),
        decode=_decode_directory,
        operation="public-directory-cache",
    )


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_sitemap_cache_only_publishes_for_unchanged_epoch
# @matrix cache sitemap : epoch public-manual-variant redis-race ttl
def cached_sitemap(builder, *, public_manual=False):
    """Return cached XML, publishing newly built XML only for a stable epoch."""
    return _cached_revision(
        _sitemap_cache_key(public_manual),
        builder,
        ttl=SITEMAP_TTL_SECONDS,
        encode=lambda value: value,
        decode=lambda value: (
            value.decode("utf-8") if isinstance(value, bytes) else value
        ),
        operation="public-sitemap-cache",
    )


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_public_discovery_invalidation_advances_epoch_and_deletes_outputs
# @matrix cache public-directory sitemap : invalidation redis-failure shared-epoch
def invalidate_public_discovery():
    """Expire cached discovery outputs without blocking the durable mutation."""
    try:
        with cache.redis.pipeline() as pipe:
            pipe.incr(Keys.PUBLIC_DISCOVERY_EPOCH.value)
            pipe.expire(
                Keys.PUBLIC_DISCOVERY_EPOCH.value,
                PUBLIC_DISCOVERY_EPOCH_TTL_SECONDS,
            )
            pipe.delete(
                Keys.PUBLIC_DIRECTORY.value,
                _sitemap_cache_key(False),
                _sitemap_cache_key(True),
            )
            pipe.execute()
        return True
    except Exception as error:
        capture(error, context={"operation": "public-discovery-invalidate"})
        return False
