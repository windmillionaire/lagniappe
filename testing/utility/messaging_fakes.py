"""Small in-memory fakes shared by messaging-domain unit tests."""

from types import SimpleNamespace

from google.cloud.datastore import Key


class MemoryDatastore:
    """Transaction-compatible Datastore fake for one entity-group flow."""

    def __init__(self):
        self.rows = {}

    def key(self, kind, identifier=None, parent=None):
        return Key(kind, identifier, parent=parent, project="messaging-test")

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, key, transaction=None):
        return self.rows.get(key)

    def get_multi(self, keys, transaction=None):
        return [self.rows.get(key) for key in keys]

    def put(self, row):
        self.rows[row.key] = row

    def delete(self, key):
        self.rows.pop(key, None)


class HashRedis:
    def __init__(self):
        self.values = {}

    def hgetall(self, key):
        return dict(self.values.get(key, {}))

    def hset(self, key, mapping):
        self.values.setdefault(key, {}).update(mapping)
        return len(mapping)


def managed_user(identifier, name, *, owner_user=False, public=False):
    key = Key("users", identifier, project="messaging-test")
    return SimpleNamespace(
        key=key,
        urlsafe_key=key.to_legacy_urlsafe().decode(),
        name=name,
        hash=f"hash-{identifier}",
        is_authenticated=True,
        is_public=public,
        is_owner=owner_user,
        allow_messages_and_mentions=False,
        allow_task_assignments=False,
        requires=["users", f"group-{identifier}"],
    )
