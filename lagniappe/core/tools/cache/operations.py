"""Expiring Redis revision projections for durable deferred operations."""

import hashlib
import time

from redis import WatchError

from .core import cache
from .keys import Keys


OPERATION_TTL_SECONDS = 30 * 60
OPERATION_VERIFY_SECONDS = 60
OPERATION_SCHEMA_VERSION = "1"
MAX_TRANSACTION_ATTEMPTS = 8


# @testable infrastructure
def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value) if value is not None else None


# @testable infrastructure
def _decode_map(values):
    return {_decode(key): _decode(value) for key, value in (values or {}).items()}


# @testable infrastructure
def _operation_id(operation):
    if isinstance(operation, str):
        return operation
    if isinstance(operation, dict):
        return str(operation.get("key") or "") or None
    identifier = getattr(operation, "urlsafe_key", None)
    if identifier:
        return identifier
    key = getattr(operation, "key", None)
    if key and hasattr(key, "to_legacy_urlsafe"):
        encoded = key.to_legacy_urlsafe()
        return encoded.decode("utf-8") if isinstance(encoded, bytes) else str(encoded)
    return str(key) if key else None


# @testable infrastructure
def _redis_key(operation):
    identifier = _operation_id(operation)
    if not identifier:
        raise ValueError("Operation state requires a deferred-job key.")
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return Keys.OPERATION.value.format(digest)


# @testable infrastructure
def _project(raw):
    values = _decode_map(raw)
    if values.get("schema") != OPERATION_SCHEMA_VERSION:
        return None
    try:
        revision = int(values["revision"])
        verified_at = float(values["verified_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "revision": max(revision, 0),
        "terminal": values.get("terminal") == "1",
        "verified_at": verified_at,
    }


# @testable infrastructure
def _values(operation):
    if isinstance(operation, dict):
        revision = operation.get("revision", operation.get("status_revision", 0))
        terminal = operation.get("terminal")
        if terminal is None:
            terminal = operation.get("status") in {
                "succeeded",
                "failed",
                "cancelled",
                "superseded",
            }
    else:
        revision = getattr(operation, "status_revision", 0)
        status = getattr(operation, "status", None)
        terminal = status in {"succeeded", "failed", "cancelled", "superseded"}
    return max(int(revision or 0), 0), bool(terminal)


# @testable true
# @tests tests_unit/test_025b_operation_state.py::test_operation_projection_is_revisioned_and_slides_ttl
# @pairs deferred-jobs:redis-projection deferred-jobs:ttl polling:batching
def peek_operation_states(operations):
    """Read known job revisions in one Redis round trip and slide their TTLs."""
    identifiers = list(dict.fromkeys(filter(None, map(_operation_id, operations or ()))))
    if not identifiers:
        return {}
    with cache.redis.pipeline() as pipe:
        for identifier in identifiers:
            key = _redis_key(identifier)
            pipe.hgetall(key)
            pipe.expire(key, OPERATION_TTL_SECONDS)
        values = pipe.execute()
    return {
        identifier: _project(values[index * 2])
        for index, identifier in enumerate(identifiers)
    }


# @testable true
# @tests tests_unit/test_025b_operation_state.py::test_operation_projection_is_revisioned_and_slides_ttl
def operation_state_current(state, revision, *, now=None):
    """Return whether a cached revision is equal and recently durable."""
    if not state or int(state["revision"]) != int(revision or 0):
        return False
    current = time.time() if now is None else float(now)
    return current - float(state["verified_at"]) < OPERATION_VERIFY_SECONDS


# @testable true
# @tests tests_unit/test_025b_operation_state.py::test_operation_projection_rejects_delayed_older_revision
# @pairs deferred-jobs:redis-projection deferred-jobs:revision deferred-jobs:concurrency
def update_operation_projection(*operations, now=None):
    """Publish committed job revisions without allowing an older writer to win."""
    observed_at = time.time() if now is None else float(now)
    grouped = {}
    for operation in operations:
        identifier = _operation_id(operation)
        if not identifier:
            continue
        revision, terminal = _values(operation)
        current = grouped.get(identifier)
        if current is None or revision >= current[0]:
            grouped[identifier] = (revision, terminal)

    results = {}
    for identifier, (revision, terminal) in grouped.items():
        key = _redis_key(identifier)
        for _attempt in range(MAX_TRANSACTION_ATTEMPTS):
            with cache.redis.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    current = _project(pipe.hgetall(key))
                    pipe.multi()
                    if current and int(current["revision"]) > revision:
                        pipe.expire(key, OPERATION_TTL_SECONDS)
                        state = current
                    else:
                        pipe.delete(key)
                        pipe.hset(
                            key,
                            mapping={
                                "schema": OPERATION_SCHEMA_VERSION,
                                "revision": str(revision),
                                "terminal": "1" if terminal else "0",
                                "verified_at": str(observed_at),
                            },
                        )
                        pipe.expire(key, OPERATION_TTL_SECONDS)
                        state = {
                            "revision": revision,
                            "terminal": terminal,
                            "verified_at": observed_at,
                        }
                    pipe.execute()
                    results[identifier] = state
                    break
                except WatchError:
                    continue
        else:
            raise RuntimeError("Operation state changed too frequently.")
    return results


# @testable true
# @tests tests_unit/test_025b_operation_state.py::test_operation_projection_deletes_with_durable_job
# @pair deferred-jobs:redis-projection
def delete_operation_projection(*operations):
    """Delete cache projections for durably deleted job records."""
    keys = list(
        dict.fromkeys(
            _redis_key(value) for value in operations if _operation_id(value)
        )
    )
    if keys:
        cache.redis.delete(*keys)


# @testable true
# @tests tests_unit/test_025b_operation_state.py::test_poll_state_read_batches_notifications_and_operations
# @pairs polling:batching notifications:redis-projection deferred-jobs:redis-projection
def peek_poll_states(user, operations):
    """Read notification and operation projections through one Redis pipeline."""
    from .notifications import (
        NOTIFICATION_TTL_SECONDS,
        _project as project_notifications,
        _redis_keys as notification_redis_keys,
    )

    identifiers = list(
        dict.fromkeys(filter(None, map(_operation_id, operations or ())))
    )
    notification_key, notification_epoch_key = notification_redis_keys(user)
    with cache.redis.pipeline() as pipe:
        pipe.hgetall(notification_key)
        pipe.expire(notification_key, NOTIFICATION_TTL_SECONDS)
        pipe.expire(notification_epoch_key, NOTIFICATION_TTL_SECONDS)
        for identifier in identifiers:
            key = _redis_key(identifier)
            pipe.hgetall(key)
            pipe.expire(key, OPERATION_TTL_SECONDS)
        values = pipe.execute()
    return (
        project_notifications(values[0]),
        {
            identifier: _project(values[3 + index * 2])
            for index, identifier in enumerate(identifiers)
        },
    )
