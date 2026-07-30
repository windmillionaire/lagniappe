from types import SimpleNamespace

import pytest

from lagniappe.core.tools.database import get, utility
from lagniappe.core.tools.database.filter import Results


# @pairs database:restricted-results database:empty-page
@pytest.mark.unit
def test_empty_results_has_no_items_or_cursor():
    results = get._empty_results()

    assert list(results) == []
    assert results.next_cursor is None


# @features database
# @dimensions query-results indexing slicing pagination
@pytest.mark.unit
def test_results_use_normal_list_indexing_and_keep_cursor_metadata():
    results = Results(["first", "second", "third"], "next-page")

    assert results[0] == "first"
    assert results[-1] == "third"
    assert results[1:] == ["second", "third"]
    assert list(results) == ["first", "second", "third"]
    assert results.next_cursor == "next-page"


# @features users caching
# @dimensions site-fingerprint save
@pytest.mark.unit
def test_save_persists_user_and_users_fingerprint_record(monkeypatch):
    saved = []
    missing_record = {"key": ("site", "users")}

    class Datastore:
        def key(self, *parts):
            return parts

        def get_multi(self, keys, missing=None):
            missing.append(missing_record)
            return []

        def put_multi(self, entities):
            saved.append(entities)

    user = SimpleNamespace(key=("users", "user-1"), db={"type": "user"})

    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=Datastore()))
    monkeypatch.setattr(utility.uuid, "uuid4", lambda: "users-fingerprint")

    utility.save(user)

    assert saved == [
        [
            {"type": "user"},
            {"key": ("site", "users"), "fingerprint": "users-fingerprint"},
        ]
    ]


# @features database migrations
# @dimensions raw-save site-fingerprint
@pytest.mark.unit
def test_save_raw_persists_datastore_entities_without_typed_save_hooks(
    monkeypatch,
):
    saved = []
    missing_record = {"key": ("site", "tasks")}

    class Datastore:
        def key(self, *parts):
            return parts

        def get_multi(self, keys, missing=None):
            missing.append(missing_record)
            return []

        def put_multi(self, entities):
            saved.append(entities)

    class RawEntity(dict):
        key = ("instances", "task-1")

    task = RawEntity(type="task", completed=True)

    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=Datastore()))
    monkeypatch.setattr(utility.uuid, "uuid4", lambda: "tasks-fingerprint")

    utility.save_raw(task)

    assert saved == [
        [
            task,
            {"key": ("site", "tasks"), "fingerprint": "tasks-fingerprint"},
        ]
    ]


# @features users caching
# @dimensions site-fingerprint invalidation
@pytest.mark.unit
def test_update_site_fingerprints_upserts_missing_users_fingerprint(monkeypatch):
    missing_record = {"key": ("site", "users")}
    generated = iter(["users-fingerprint"])

    class Datastore:
        def key(self, *parts):
            return parts

        def get_multi(self, keys, missing=None):
            assert keys == [("site", "users")]
            missing.append(missing_record)
            return []

    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=Datastore()))
    monkeypatch.setattr(utility.uuid, "uuid4", lambda: next(generated))

    records = utility.update_site_fingerprints({"type": "user"})

    assert records == [{"key": ("site", "users"), "fingerprint": "users-fingerprint"}]


# @features mutations database
# @dimensions property-mask update full-upsert site-fingerprint document-checkpoint
# @source lagniappe/core/tools/database/utility.py::save_mutations
@pytest.mark.unit
def test_save_mutations_applies_property_masks_and_fingerprints(monkeypatch):
    class Mutation:
        def __init__(self, entity):
            self.upsert = entity
            self._update = None
            self.property_mask = SimpleNamespace(paths=[])

        @property
        def update(self):
            return self._update

        @update.setter
        def update(self, entity):
            self._update = entity
            self.upsert = None

    class Batch:
        def __init__(self):
            self.mutations = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def put(self, entity):
            self.mutations.append(Mutation(entity))

    batch = Batch()
    datastore = SimpleNamespace(batch=lambda: batch)
    full = SimpleNamespace(key=("instances", "full"), db={"type": "page"})
    masked = SimpleNamespace(
        key=("instances", "masked"),
        db={"type": "category", "modified": "now"},
    )
    activity = SimpleNamespace(
        key=("users", "activity"),
        db={"type": "user", "notification_revision": 3},
    )
    document = SimpleNamespace(
        key=("instances", "document"),
        db={
            "type": "page",
            "assets": {"document": {"fingerprint": "next"}},
            "document_history": True,
        },
    )
    fingerprint = {"type": "site", "fingerprint": "next"}
    fingerprinted = []

    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=datastore))
    monkeypatch.setattr(
        utility,
        "update_site_fingerprints",
        lambda *entities: fingerprinted.extend(entities) or [fingerprint],
    )

    utility.save_mutations(
        (
            (full, None),
            (masked, ("modified", "forms")),
            (activity, ("notification_revision",)),
            (document, ("assets", "document_history")),
        )
    )

    assert fingerprinted == [full.db, masked.db]
    assert batch.mutations[0].upsert is full.db
    assert batch.mutations[0].update is None
    assert batch.mutations[0].property_mask.paths == []
    assert batch.mutations[1].upsert is None
    assert batch.mutations[1].update is masked.db
    assert batch.mutations[1].property_mask.paths == ["modified", "forms"]
    assert batch.mutations[2].update is activity.db
    assert batch.mutations[2].property_mask.paths == ["notification_revision"]
    assert batch.mutations[3].update is document.db
    assert batch.mutations[3].property_mask.paths == [
        "assets",
        "document_history",
    ]
    assert batch.mutations[4].upsert is fingerprint
