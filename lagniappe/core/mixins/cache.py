# @testable true
# @tests tests_unit/test_006_file_properties.py::test_summary
# @pair file:cache
class CacheMixin:
    """Adds entity cache output. Collected by Entity.to_cache.

    Provides:
        cache_value: Value to store in cache (default: self.value).
        cache_key (str): Key in the cache dict (default: self.id).

    Override:
        _cache_key (str): Set to use a different cache key than self.id.
    """

    @property
    def cache_value(self):
        return self.value

    @property
    def cache_key(self):
        return getattr(self, "_cache_key", self.id)
