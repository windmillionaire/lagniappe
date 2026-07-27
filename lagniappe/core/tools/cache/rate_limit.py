"""Minimal Redis-backed fixed-window rate limiting helpers."""

import hashlib

from .core import cache
from .keys import Keys


# @testable false
# @covered-by lagniappe/core/tools/cache/rate_limit.py::check_limit
# @reason client identifier selection is exercised through the live limiter path
def client_ip(request):
    """Return the most useful client IP from App Engine / proxy headers."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()

    if getattr(request, "access_route", None):
        return request.access_route[0]

    return request.remote_addr or "unknown"


# @testable true
# @tests tests_e2e/001_site/test_001b_login.py::test_login_identity_returns_rate_limit_response
# @features login
# @dimensions identity-platform rate-limit
def check_limit(scope, identifier, limit, window_seconds):
    """Increment and evaluate a fixed-window rate limit."""
    digest = hashlib.sha256(str(identifier).encode("utf-8")).hexdigest()[:16]
    key = Keys.RATE_LIMIT.value.format(scope, digest)

    count = cache.redis.incr(key)
    if count == 1:
        cache.redis.expire(key, window_seconds)

    retry_after = cache.redis.ttl(key)
    if retry_after < 0:
        retry_after = window_seconds
        cache.redis.expire(key, window_seconds)

    return {
        "allowed": count <= limit,
        "count": count,
        "remaining": max(limit - count, 0),
        "retry_after": retry_after,
    }
