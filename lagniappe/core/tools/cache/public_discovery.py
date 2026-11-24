"""Revisioned Redis caches for anonymous public discovery surfaces."""

from collections.abc import Callable
from typing import NotRequired, TypedDict, cast

import json

from redis.exceptions import WatchError

from lagniappe.core.exceptions import capture

from .core import cache
from .keys import Keys


class DirectoryPage(TypedDict):
    path: str
    title: str
    description: NotRequired[str | None]
    order: NotRequired[int | None]


class DirectoryGroup(TypedDict):
    id: str
    name: str
    pages: list[DirectoryPage]


class DirectorySnapshot(TypedDict):
    schema: int
    site_indexing: bool
    groups: list[DirectoryGroup]


PUBLIC_DIRECTORY_SCHEMA = 1
PUBLIC_DIRECTORY_TTL_SECONDS = 15 * 60
SITEMAP_TTL_SECONDS = 60 * 60
PUBLIC_DISCOVERY_EPOCH_TTL_SECONDS = 7 * 24 * 60 * 60


def _sitemap_cache_key(public_manual):
    return f"{Keys.SITEMAP.value}:MANUAL:{int(bool(public_manual))}"


def _decode_directory(value: str | bytes) -> DirectorySnapshot | None:
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
                or (
                    page.get("order") is not None
                    and (
                        isinstance(page.get("order"), bool)
                        or not isinstance(page.get("order"), int)
                    )
                )
            ):
                return None
    return cast(DirectorySnapshot, snapshot)  # Every nested field is validated above.


def _cached_revision[T: (str, DirectorySnapshot)](
    key: str,
    builder: Callable[[], T],
    *,
    ttl: int,
    encode: Callable[[T], str],
    decode: Callable[[str | bytes], T | None],
    operation: str,
) -> T:
    try:
        cached = cache.redis.get(key)
    except Exception as error:
        capture(error, context={"operation": f"{operation}-read"})
        return builder()
    if cached:
        decoded = decode(cached)
        if decoded is not None:
            return decoded

    for _attempt in range(2):
        value: T | None = None
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
            return value if value is not None else builder()
    return builder()


def cached_public_directory(
    builder: Callable[[], DirectorySnapshot],
) -> DirectorySnapshot:
    """Return a privacy-bounded public catalog, rebuilding it after its TTL."""
    return _cached_revision(
        Keys.PUBLIC_DIRECTORY.value,
        builder,
        ttl=PUBLIC_DIRECTORY_TTL_SECONDS,
        encode=lambda value: json.dumps(value, separators=(",", ":"), sort_keys=True),
        decode=_decode_directory,
        operation="public-directory-cache",
    )


def cached_sitemap(builder: Callable[[], str], *, public_manual: bool = False) -> str:
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


def invalidate_public_discovery() -> bool:
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
