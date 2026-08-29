"""Unit coverage for expiring deferred-operation Redis revisions."""

from types import SimpleNamespace

import pytest
from redis import WatchError

from lagniappe.core.tools.cache import operations
from lagniappe.core.tools.cache import notifications
from lagniappe.core.tools.cache import notification_state as notification_projection


pytestmark = pytest.mark.unit


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []
        self.watched = {}
        self.watching = False
        self.transaction = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def watch(self, *keys):
        self.watching = True
        self.watched = {key: self.redis.versions.get(key, 0) for key in keys}

    def multi(self):
        self.transaction = True

    def _run_or_queue(self, name, *args, **kwargs):
        if self.watching and not self.transaction:
            return self.redis.apply(name, *args, **kwargs)
        self.commands.append((name, args, kwargs))
        return self

    def hgetall(self, key):
        return self._run_or_queue("hgetall", key)

    def expire(self, key, seconds):
        return self._run_or_queue("expire", key, seconds)

    def delete(self, *keys):
        return self._run_or_queue("delete", *keys)

    def hset(self, key, *args, mapping=None):
        return self._run_or_queue("hset", key, *args, mapping=mapping)

    def execute(self):
        if any(
            self.redis.versions.get(key, 0) != version
            for key, version in self.watched.items()
        ):
            raise WatchError("changed")
        return [
            self.redis.apply(name, *args, **kwargs)
            for name, args, kwargs in self.commands
        ]


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.expirations = {}
        self.versions = {}

    def pipeline(self):
        return FakePipeline(self)

    def touch(self, key):
        self.versions[key] = self.versions.get(key, 0) + 1

    def delete(self, *keys):
        return self.apply("delete", *keys)

    def apply(self, name, key, *args, **kwargs):
        if name == "hgetall":
            return dict(self.hashes.get(key, {}))
        if name == "expire":
            self.expirations[key] = args[0]
            return key in self.hashes
        if name == "delete":
            deleted = 0
            for current in (key, *args):
                deleted += int(current in self.hashes)
                self.hashes.pop(current, None)
                self.touch(current)
            return deleted
        if name == "hset":
            mapping = kwargs.get("mapping") or {}
            self.hashes.setdefault(key, {}).update(
                {str(field): str(value) for field, value in mapping.items()}
            )
            self.touch(key)
            return len(mapping)
        raise AssertionError(f"Unsupported fake Redis command: {name}")


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(operations.cache, "_redis", fake)
    return fake


def job(key="job-one", *, revision=1, status="running"):
    return SimpleNamespace(
        urlsafe_key=key,
        status_revision=revision,
        status=status,
    )


# @matrix deferred-jobs : redis-projection ttl
# @pair polling:batching
def test_operation_projection_is_revisioned_and_slides_ttl(redis):
    current = job()
    operations.update_operation_projection(current, now=100)

    state = operations.peek_operation_states([current.urlsafe_key])[current.urlsafe_key]
    key = operations._redis_key(current)

    assert state == {"revision": 1, "terminal": False, "verified_at": 100.0}
    assert redis.expirations[key] == operations.OPERATION_TTL_SECONDS
    assert operations.operation_state_current(state, 1, now=159) is True
    assert operations.operation_state_current(state, 1, now=160) is False


# @matrix deferred-jobs : concurrency redis-projection revision
def test_operation_projection_rejects_delayed_older_revision(redis):
    latest = job(revision=5, status="succeeded")
    operations.update_operation_projection(latest, now=200)
    operations.update_operation_projection(job(revision=4), now=300)

    state = operations.peek_operation_states([latest.urlsafe_key])[latest.urlsafe_key]

    assert state == {"revision": 5, "terminal": True, "verified_at": 200.0}


# @pair deferred-jobs:redis-projection
def test_operation_projection_deletes_with_durable_job(redis):
    current = job()
    operations.update_operation_projection(current, now=100)

    operations.delete_operation_projection(current)

    assert operations.peek_operation_states([current.urlsafe_key]) == {
        current.urlsafe_key: None
    }


# @matrix deferred-jobs notifications : redis-projection
# @pair polling:batching
def test_poll_state_read_batches_notifications_and_operations(redis, monkeypatch):
    user = SimpleNamespace(urlsafe_key="user-one")
    current = job()
    operations.update_operation_projection(current, now=100)
    notification_key, epoch_key = notifications._redis_keys(user)
    redis.hashes[notification_key] = {
        "schema": notification_projection.NOTIFICATION_SCHEMA_VERSION,
        "generation": "generation-one",
        "revision": "3",
        "message_revision": "2",
        "ordinary_count": "1",
        "unread_message_count": "0",
        "member:notice-one": "1",
    }
    pipeline_calls = 0
    original_pipeline = redis.pipeline

    def count_pipeline():
        nonlocal pipeline_calls
        pipeline_calls += 1
        return original_pipeline()

    monkeypatch.setattr(redis, "pipeline", count_pipeline)

    notification_state, operation_states = operations.peek_poll_states(
        user,
        [current.urlsafe_key],
    )

    assert pipeline_calls == 1
    assert notification_state == {
        "generation": "generation-one",
        "revision": 3,
        "message_revision": 2,
        "ordinary_count": 1,
        "unread_message_count": 0,
        "count": 1,
        "members": {"notice-one"},
    }
    assert operation_states[current.urlsafe_key]["revision"] == 1
    assert redis.expirations[notification_key] == notifications.NOTIFICATION_TTL_SECONDS
    assert redis.expirations[epoch_key] == notifications.NOTIFICATION_TTL_SECONDS
