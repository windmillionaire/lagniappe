from types import SimpleNamespace

import pytest

from google.cloud.datastore import Key

from lagniappe import CONFIG
from lagniappe.core.tools.database import get, utility
from lagniappe.core.definitions import Restriction
from lagniappe.core.tools.database import filter as database_filter
from lagniappe.core.tools.database.filter import Filter, Query, Results


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


# @features database permissions
# @dimensions deny-all filter-composition
@pytest.mark.unit
def test_filter_preserves_explicit_deny_all_through_composition():
    denied = Filter().requires([])

    assert denied
    assert denied.is_denied
    assert denied.build() is not None
    assert not Filter().requires(Restriction.UNRESTRICTED)

    allowed_branch = Filter().eq("type", "page")
    mixed = Filter().any_of(denied, allowed_branch)
    assert not mixed.is_denied
    assert mixed.build() is not None

    only_denied = Filter().eq("active", True).any_of(
        Filter().requires([]),
        Filter(),
    )
    assert only_denied.is_denied
    assert only_denied.build() is not None


# @features database permissions
# @dimensions deny-all query-short-circuit terminal-results
@pytest.mark.unit
def test_denied_query_terminals_do_not_create_datastore_query(monkeypatch):
    class Datastore:
        def query(self, **kwargs):
            raise AssertionError(f"Denied query reached Datastore: {kwargs}")

    monkeypatch.setattr(
        database_filter,
        "DATA",
        SimpleNamespace(datastore=Datastore()),
    )

    def denied_query():
        return Query("instances").filter(Filter().requires([]))

    results = denied_query().limit(25).cursor("cursor").fetch()
    assert list(results) == []
    assert results.next_cursor is None
    assert denied_query().fetch_all() == []
    assert denied_query().fetch_one() is None
    assert list(denied_query().fetch_iter()) == []
    assert denied_query().count() == 0
    assert denied_query().exists() is False


# @features database permissions
# @dimensions deny-all group-query
@pytest.mark.unit
def test_groups_with_denied_hashes_does_not_query_datastore(monkeypatch):
    class Datastore:
        def query(self, **kwargs):
            raise AssertionError(f"Denied group query reached Datastore: {kwargs}")

    monkeypatch.setattr(
        database_filter,
        "DATA",
        SimpleNamespace(datastore=Datastore()),
    )

    assert get.groups([]) == []


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


# @pairs polling:channel polling:batching polling:mounted-scope
# @source lagniappe/core/tools/database/utility.py::site_fingerprints
@pytest.mark.unit
def test_site_fingerprints_batch_reads_only_resolved_paths(monkeypatch):
    class Record(dict):
        def __init__(self, key, **values):
            super().__init__(values)
            self.key = key

    loaded = []
    saved = []
    existing = Record(("site", "home"), fingerprint="home-current")

    class Datastore:
        def key(self, *parts):
            return parts

        def get_multi(self, keys, missing=None):
            loaded.append(keys)
            missing.append(Record(("site", "tasks")))
            return [existing]

        def put_multi(self, entities):
            saved.extend(entities)

    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=Datastore()))
    monkeypatch.setattr(utility.uuid, "uuid4", lambda: "tasks-created")

    fingerprints = utility.site_fingerprints(
        ("/", "/tasks/index", "/unmapped/index", "/tasks/index")
    )

    assert loaded == [[("site", "home"), ("site", "tasks")]]
    assert fingerprints == {
        "/": "home-current",
        "/tasks/index": "tasks-created",
    }
    assert [record.key for record in saved] == [("site", "tasks")]


# @pairs notifications:mutation notifications:site-fingerprint-isolation
# @source lagniappe/core/tools/database/utility.py::save_mutations
@pytest.mark.unit
def test_notification_save_and_delete_skip_site_fingerprints(monkeypatch):
    fingerprinted = []
    saved = []

    class Batch:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def put(self, entity):
            saved.append(("put", entity))

        def delete(self, key):
            saved.append(("delete", key))

    datastore = SimpleNamespace(batch=Batch)
    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=datastore))
    monkeypatch.setattr(
        utility,
        "update_site_fingerprints",
        lambda *entities: fingerprinted.extend(entities) or [],
    )
    notification = SimpleNamespace(
        key=("activity", "notification"),
        db={"type": "notification"},
    )

    utility.save_mutations(((notification, None),))
    utility.delete_entities((notification,))

    assert fingerprinted == []
    assert saved == [
        ("put", notification.db),
        ("delete", notification.key),
    ]


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
    document = SimpleNamespace(
        key=("instances", "document"),
        db={
            "type": "page",
            "assets": {"document": {"fingerprint": "next"}},
            "document_history": True,
        },
    )
    deferred_reference = SimpleNamespace(
        key=("instances", "deferred-reference"),
        db={"type": "page", "deferred_job": '{"key":"operation"}'},
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
            (document, ("assets", "document_history")),
            (deferred_reference, ("deferred_job",)),
        )
    )

    assert fingerprinted == [full.db, masked.db]
    assert batch.mutations[0].upsert is full.db
    assert batch.mutations[0].update is None
    assert batch.mutations[0].property_mask.paths == []
    assert batch.mutations[1].upsert is None
    assert batch.mutations[1].update is masked.db
    assert batch.mutations[1].property_mask.paths == ["modified", "forms"]
    assert batch.mutations[2].update is document.db
    assert batch.mutations[2].property_mask.paths == [
        "assets",
        "document_history",
    ]
    assert batch.mutations[3].update is deferred_reference.db
    assert batch.mutations[3].property_mask.paths == ["deferred_job"]
    assert batch.mutations[4].upsert is fingerprint


# @pair database:named-key-encoding
@pytest.mark.unit
def test_database_aware_urlsafe_key_round_trip():
    from config.datastore import decode_urlsafe_key, encode_urlsafe_key

    key = Key(
        "instances",
        "page-1",
        project=CONFIG.GOOGLE_CLOUD_PROJECT,
        namespace="owner-space",
        database="current-db",
    )
    decoded = decode_urlsafe_key(encode_urlsafe_key(key))
    assert decoded.flat_path == key.flat_path
    assert decoded.project == key.project
    assert decoded.namespace == key.namespace
    assert decoded.database == "current-db"


# @pair database:named-key-encoding
@pytest.mark.unit
def test_datastore_key_decodes_without_runtime_rebinding():
    from config.datastore import encode_urlsafe_key

    source = Key("instances", "page-1", project="source-proj1", database="source-db")
    decoded = get.datastore_key(encode_urlsafe_key(source))
    assert decoded == source
    assert get.datastore_key("not-a-key") is None
    assert get.datastore_key(source) is source
    holder = SimpleNamespace(key=source)
    assert get.datastore_key(holder) is source
