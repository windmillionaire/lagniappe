"""In-memory persistence and task fakes for notification-email tests."""

from google.cloud.datastore import Entity as DatastoreEntity
from google.cloud.datastore import Key

from lagniappe.core.entities import Entities
from lagniappe.core.tools.notification_email import dispatch as email_dispatch
from lagniappe.core.tools.database.core import KINDS


class MemoryDatastore:
    def __init__(self):
        self.rows = {}

    def key(self, kind, identifier=None, parent=None):
        return Key(kind, identifier, parent=parent, project="notification-email-test")

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, key, transaction=None):
        return self.rows.get(key)

    def put(self, row):
        self.rows[row.key] = row

    def put_multi(self, rows):
        for row in rows:
            self.put(row)


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, ex=None):
        self.values[key] = str(value).encode("utf-8")
        self.expirations[key] = ex
        return True


def user_row(identifier, now, *, mode="IMMEDIATE", public=False, logged_in=True):
    key = Key(KINDS.users.value, identifier, project="notification-email-test")
    row = DatastoreEntity(key=key)
    row.update(
        {
            "type": "user",
            "kind": "user",
            "name": identifier.title(),
            "email": f"{identifier}@example.test",
            "last_login": now if logged_in else None,
            "public": public,
            "active": True,
            "notification_email_mode": mode,
        }
    )
    return Entities.USER(row)


def task_recorder(monkeypatch):
    tasks = []

    def create_task(endpoint, payload, delay_seconds=0, *, task_id=None, **_kwargs):
        tasks.append(
            {
                "endpoint": endpoint,
                "payload": payload,
                "delay": delay_seconds,
                "task_id": task_id,
            }
        )
        return task_id

    monkeypatch.setattr(email_dispatch.task_queue, "create_task", create_task)
    return tasks
