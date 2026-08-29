"""Unit coverage for the expiring Redis notification projection."""

from types import SimpleNamespace

import pytest
from redis import WatchError

from lagniappe.core.tools.cache import notifications


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

    def get(self, key):
        return self._run_or_queue("get", key)

    def expire(self, key, seconds):
        return self._run_or_queue("expire", key, seconds)

    def set(self, key, value):
        return self._run_or_queue("set", key, value)

    def delete(self, key):
        return self._run_or_queue("delete", key)

    def hset(self, key, *args, mapping=None):
        return self._run_or_queue("hset", key, *args, mapping=mapping)

    def incr(self, key):
        return self._run_or_queue("incr", key)

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
        self.values = {}
        self.expirations = {}
        self.versions = {}

    def pipeline(self):
        return FakePipeline(self)

    def touch(self, key):
        self.versions[key] = self.versions.get(key, 0) + 1

    def apply(self, name, key, *args, **kwargs):
        if name == "hgetall":
            return dict(self.hashes.get(key, {}))
        if name == "get":
            return self.values.get(key)
        if name == "expire":
            self.expirations[key] = args[0]
            return key in self.hashes or key in self.values
        if name == "set":
            self.values[key] = str(args[0])
            self.touch(key)
            return True
        if name == "delete":
            self.hashes.pop(key, None)
            self.values.pop(key, None)
            self.touch(key)
            return 1
        if name == "hset":
            mapping = kwargs.get("mapping") or {}
            self.hashes.setdefault(key, {}).update(
                {str(field): str(value) for field, value in mapping.items()}
            )
            self.touch(key)
            return len(mapping)
        if name == "incr":
            value = int(self.values.get(key) or 0) + 1
            self.values[key] = str(value)
            self.touch(key)
            return value
        raise AssertionError(f"Unsupported fake Redis command: {name}")


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(notifications.cache, "_redis", fake)
    notifications.clear_recorded_notification_states()
    return fake


def user(key="user-key"):
    return SimpleNamespace(urlsafe_key=key)


def item(key, owner=None):
    return SimpleNamespace(urlsafe_key=key, parent=owner or user())


class NotificationKey:
    def __init__(self, value):
        self.value = value

    def to_legacy_urlsafe(self):
        return self.value.encode("utf-8")


# @matrix notifications : cold-seed keys-only race-safety
def test_cold_seed_runs_one_keys_only_query_and_is_race_safe(redis):
    queries = []
    owner = user()
    created = item("notification-a", owner)

    state = notifications.seed_notification_state(
        owner,
        keys_loader=lambda current: queries.append(current)
        or [NotificationKey(created.urlsafe_key)],
    )

    assert queries == [owner]
    assert state["count"] == 1
    assert state["members"] == {"notification-a"}

    redis.hashes.clear()
    redis.values.clear()
    redis.versions.clear()
    queries.clear()

    def raced_loader(current):
        queries.append(current)
        if len(queries) == 1:
            notifications.update_notification_projection(upserts=[created])
            return []
        return [created]

    raced = notifications.seed_notification_state(owner, keys_loader=raced_loader)
    assert len(queries) == 2
    assert raced["count"] == 1
    assert raced["revision"] == 1


# @matrix notifications : datastore-read-isolation redis-projection ttl
def test_warm_notification_state_is_redis_only_and_refreshes_ttl(redis):
    owner = user()
    notifications.seed_notification_state(
        owner,
        notification_keys=[item("notification-a", owner)],
    )

    state = notifications.peek_notification_state(owner)

    state_key, epoch_key = notifications._redis_keys(owner)
    assert state["count"] == 1
    assert redis.expirations[state_key] == notifications.NOTIFICATION_TTL_SECONDS
    assert redis.expirations[epoch_key] == notifications.NOTIFICATION_TTL_SECONDS


# @matrix notifications : cold-seed expiry generation
def test_expired_notification_state_gets_a_new_generation(redis):
    owner = user()
    first = notifications.seed_notification_state(owner, notification_keys=[])
    state_key, epoch_key = notifications._redis_keys(owner)
    redis.hashes.pop(state_key)
    redis.values.pop(epoch_key)
    redis.touch(state_key)
    redis.touch(epoch_key)

    assert notifications.peek_notification_state(owner) is None
    second = notifications.seed_notification_state(owner, notification_keys=[])

    assert second["generation"] != first["generation"]


# @matrix notifications : idempotent-count mutation revision
def test_notification_mutations_are_idempotent_and_advance_once(redis):
    owner = user()
    first = item("notification-a", owner)
    missing = item("notification-missing", owner)
    notifications.seed_notification_state(owner, notification_keys=[first])

    first_update = notifications.update_notification_projection(upserts=[first])[
        owner.urlsafe_key
    ]
    content_update = notifications.update_notification_projection(upserts=[first])[
        owner.urlsafe_key
    ]
    missing_delete = notifications.update_notification_projection(deletes=[missing])[
        owner.urlsafe_key
    ]
    deleted = notifications.update_notification_projection(deletes=[first])[
        owner.urlsafe_key
    ]

    assert (first_update["revision"], first_update["count"]) == (1, 1)
    assert (content_update["revision"], content_update["count"]) == (2, 1)
    assert (missing_delete["revision"], missing_delete["count"]) == (3, 1)
    assert (deleted["revision"], deleted["count"]) == (4, 0)


# @matrix notifications : cold-cache datastore-read-isolation mutation
def test_absent_projection_mutation_updates_epoch_without_querying(redis):
    owner = user()
    result = notifications.update_notification_projection(
        upserts=[item("notification-a", owner)]
    )[owner.urlsafe_key]
    state_key, epoch_key = notifications._redis_keys(owner)

    assert result == {"generation": None, "revision": None, "count": None}
    assert state_key not in redis.hashes
    assert redis.values[epoch_key] == "1"


# @matrix notifications : aggregate-count redis-projection revision
def test_durable_aggregate_publish_preserves_members_and_exact_combined_count(redis):
    owner = user()
    existing = item("notification-a", owner)
    notifications.seed_notification_state(
        owner,
        notification_keys=[existing],
        aggregate_loader=lambda _user: {
            "ordinary_count": 1,
            "unread_message_count": 0,
            "message_revision": 2,
        },
    )

    state = notifications.publish_notification_aggregate(
        owner,
        {
            "ordinary_count": 7,
            "unread_message_count": 3,
            "aggregate_revision": 4,
            "message_revision": 5,
        },
    )

    assert state["ordinary_count"] == 7
    assert state["unread_message_count"] == 3
    assert state["message_revision"] == 5
    assert state["count"] == 10
    assert state["members"] == {"notification-a"}
    assert state["revision"] >= 4


# @matrix notifications : authoritative-repair membership revision
def test_notification_list_keys_repair_warm_projection(redis):
    owner = user()
    first = item("notification-a", owner)
    second = item("notification-b", owner)
    seeded = notifications.seed_notification_state(owner, notification_keys=[first])

    repaired = notifications.repair_notification_state(owner, [first, second])

    assert repaired["generation"] == seeded["generation"]
    assert repaired["revision"] == seeded["revision"] + 1
    assert repaired["members"] == {"notification-a", "notification-b"}
