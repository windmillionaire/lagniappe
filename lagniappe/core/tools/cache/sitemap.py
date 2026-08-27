"""Revisioned Redis cache for the generated public-page sitemap."""

from redis.exceptions import WatchError

from lagniappe.core.exceptions import capture

from .core import cache
from .keys import Keys


SITEMAP_TTL_SECONDS = 60 * 60
SITEMAP_EPOCH_TTL_SECONDS = 7 * 24 * 60 * 60


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_sitemap_cache_only_publishes_for_unchanged_epoch
# @matrix cache sitemap : epoch redis-race ttl
def cached_sitemap(builder):
    """Return cached XML, publishing newly built XML only for a stable epoch."""
    try:
        cached = cache.redis.get(Keys.SITEMAP.value)
        if cached:
            return cached.decode("utf-8") if isinstance(cached, bytes) else cached

        for _attempt in range(2):
            with cache.redis.pipeline() as pipe:
                try:
                    pipe.watch(Keys.SITEMAP_EPOCH.value)
                    xml = builder()
                    pipe.multi()
                    pipe.setex(Keys.SITEMAP.value, SITEMAP_TTL_SECONDS, xml)
                    pipe.execute()
                    return xml
                except WatchError:
                    continue
        return builder()
    except Exception as error:
        capture(error, context={"operation": "public-sitemap-cache-read"})
        return builder()


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_sitemap_invalidation_advances_epoch_and_deletes_xml
# @matrix cache sitemap : invalidation redis-failure
def invalidate_sitemap():
    """Advance the sitemap epoch and remove cached XML without blocking a save."""
    try:
        with cache.redis.pipeline() as pipe:
            pipe.incr(Keys.SITEMAP_EPOCH.value)
            pipe.expire(Keys.SITEMAP_EPOCH.value, SITEMAP_EPOCH_TTL_SECONDS)
            pipe.delete(Keys.SITEMAP.value)
            pipe.execute()
        return True
    except Exception as error:
        capture(error, context={"operation": "public-sitemap-invalidate"})
        return False
