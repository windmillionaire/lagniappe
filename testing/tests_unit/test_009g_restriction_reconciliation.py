"""Restriction sources, minimal loading, migrations and queued cache updates."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import UnloadedRelationError
from lagniappe.core.tools.auth.restrictions import combine_restrictions, permission_relation, prepare_permissions
from lagniappe.core.tools.cache import restrictions as reconcile
from lagniappe.core.tools.database import migrations
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.database.migration_steps.v1_3_permissions import migrate_file_ownership, migrate_local_restrictions
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


# @matrix permissions : page-precedence owner-fallback
@pytest.mark.parametrize("page,form,expected", [
    ([], [], []), ([], ["b", "a"], ["owner", "a", "b"]),
    (["a"], ["b"], ["owner", "a"]), (["owner"], ["a"], ["owner"]),
])
def test_page_restrictions_take_precedence(page, form, expected):
    assert combine_restrictions(page, form) == expected


# @matrix permissions relations : required-parent unloaded-relation
def test_required_permission_relation_does_not_hide_unloaded_page(monkeypatch):
    task = TestEntities.get("TASK", {"hash": "required-task"})
    task.db["page"] = "unloaded-page"
    task.properties.page.unset()
    monkeypatch.setattr(Entities, "fetch", Mock(side_effect=AssertionError("permission check must not read")))
    with pytest.raises(UnloadedRelationError):
        permission_relation(task, "page", required=True)
    task.db.pop("page")
    with pytest.raises(UnloadedRelationError):
        permission_relation(task, "page", required=True)


# @matrix permissions relations : batch explicit-fetch-depth no-group-expansion
def test_permission_preparation_only_loads_missing_sources(monkeypatch):
    form = TestEntities.get("FORM", {"hash": "permission-form", "restricted_to": ["owner", "group"]})
    form.db["groups"] = ["unloaded-group"]
    form.properties.groups.unset()
    page = TestEntities.get("PAGE", {"hash": "permission-page"})
    page.db["form"] = form.key
    page.properties.form.unset()
    task = TestEntities.get("TASK", {"hash": "permission-task"}, page=page)
    files = [TestEntities.get("FILE", {"hash": f"file-{index}"}) for index in range(2)]
    for file in files:
        file.db["task"] = task.key
        file.properties.task.unset()
    calls = []

    def fetch(*keys, request):
        calls.append((set(keys), request))
        return [{task.key: task, form.key: form}[key] for key in keys]

    monkeypatch.setattr(Entities, "fetch", fetch)
    prepare_permissions(*files)
    assert calls == [({task.key}, Fetch.root()), ({form.key}, Fetch.root())]
    assert all(file.owner is task and file.restricted_to == ["owner", "group"] for file in files)
    assert not form.properties.groups.is_set
    prepare_permissions(*files)
    assert len(calls) == 2


# @matrix permissions : local-restrictions materialization owner-only
def test_local_restrictions_materialize_without_persisting_inheritance():
    form = TestEntities.get("FORM", {"hash": "local-form", "restricted_to": ["owner", "form-group"]})
    page = TestEntities.get("PAGE", {"hash": "local-page"})
    page.form = form
    page.properties.restricted_to.materialize()
    assert page.restricted_to == ["owner", "form-group"]
    assert not page.properties.restricted_to.stored
    group = TestEntities.get("USER_GROUP", {"hash": "local-group"})
    page.groups = [group]
    page.properties.restricted_to.materialize(owner_only=False)
    assert page.db["restricted_to"] == ["owner", "local-group"]
    assert page.restricted_to == ["owner", "local-group"]
    page.properties.restricted_to.materialize(owner_only=True)
    assert page.restricted_to == ["owner"]


# @matrix files : ownership move reverse-links cardinality parent-key
def test_file_move_preserves_single_ownership():
    page = TestEntities.get("PAGE", {"hash": "move-page"})
    task = TestEntities.get("TASK", {"hash": "move-task"}, page=page)
    task.files = []
    file = TestEntities.get("FILE", {"hash": "move-file"})
    file.page = page
    with pytest.raises(ValueError):
        file.task = task
    file.move_to(task)
    assert file.page is None and file.task is task
    assert task.files == [file]
    assert {page.hash, task.hash, file.hash} <= set(file.required)
    file.move_to(page)
    assert file.page is page and file.task is None and task.files == []
    assert task.hash not in file.required


# @matrix permissions cache : cached-sources file-parent page-precedence
def test_cached_restrictions_resolve_file_task_page_and_form():
    details = {
        "page": {"kind": "page", "restricted_to": ["owner", "page-group"]},
        "form": {"kind": "form", "restricted_to": ["owner", "task-group"]},
        "task": {"kind": "task", "parent_key": "page", "form_key": "form"},
        "file": {"kind": "file", "parent_key": "task"},
    }
    assert reconcile.effective(details, "file") == ["owner", "page-group"]
    details["page"]["restricted_to"] = []
    assert reconcile.effective(details, "file") == ["owner", "task-group"]
    details["form"]["restricted_to"] = []
    assert reconcile.effective(details, "file") == []
    del details["task"]["form_key"]
    with pytest.raises(RuntimeError):
        reconcile.effective(details, "file")


# @matrix permissions cache : change-detection retry
def test_reconciliation_change_detection_and_forced_retry(monkeypatch):
    form = TestEntities.get("FORM", {"hash": "changed-form", "restricted_to": ["owner", "new"]})
    form._testing = False
    pipe = Mock()
    pipe.__enter__ = Mock(return_value=pipe)
    pipe.__exit__ = Mock(return_value=False)
    pipe.execute.return_value = [b"owner,old", None]
    monkeypatch.setattr(reconcile.cache, "pipeline", lambda: pipe)
    queued = []
    monkeypatch.setattr(reconcile, "enqueue", queued.append)
    previous = reconcile.previous_restrictions([form])
    reconcile.dispatch_changes(previous)
    assert queued == [{"source_key": form.urlsafe_key}]
    reconcile.dispatch_changes([(form, b"owner,new")])
    assert len(queued) == 1
    form._reconcile_restrictions = True
    reconcile.dispatch_changes([(form, b"owner,new")])
    assert len(queued) == 2
    monkeypatch.setattr(reconcile, "enqueue", Mock(side_effect=RuntimeError("queue offline")))
    form._reconcile_restrictions = True
    with pytest.raises(RuntimeError, match="queue offline"):
        reconcile.dispatch_changes([(form, b"owner,new")])
    assert form._reconcile_restrictions is True


# @matrix permissions : queue dispatch
def test_reconciliation_enqueue_uses_current_source_key(monkeypatch):
    monkeypatch.setattr(reconcile, "CONFIG", SimpleNamespace(local=False))
    monkeypatch.setattr(reconcile, "url_for", lambda *args, **kwargs: "https://example.test/process/reconcile-restrictions")
    create = Mock(return_value="queued-task")
    monkeypatch.setattr(reconcile.task_queue, "create_task", create)
    reconcile.enqueue({"source_key": "form-key"})
    assert create.call_args.args[1] == {"source_key": "form-key"}
    create.return_value = None
    with pytest.raises(RuntimeError, match="retry saving"):
        reconcile.enqueue({"source_key": "form-key"})


# @matrix files migrations : single-owner history conflict idempotence
# @pair database-migrations:actionable-links
def test_file_migration_normalizes_history_and_preserves_conflicts():
    from testing.tests_unit.test_018b_database_migrations import _Datastore, _entity, _key
    page = _entity(KINDS.instances.value, "page", {"type": "page", "hash": "page", "requires": ["page", "models"]})
    task = _entity(KINDS.instances.value, "task", {"type": "task", "hash": "task", "page": page.key, "requires": ["page", "models"]})
    history = _entity(KINDS.history.value, "history", {"type": "task_history", "task": task.key})
    file = _entity(KINDS.files.value, "file", {"type": "file", "hash": "file", "tasks": [task.key, history.key]})
    conflict = _entity(KINDS.files.value, "conflict", {"type": "file", "hash": "conflict", "name": "Conflicting attachment", "tasks": [task.key], "pages": [page.key]})
    missing_owner = _entity(KINDS.files.value, "missing-owner", {
        "type": "file", "filename": "scan.pdf", "pages": [_key(KINDS.instances.value, "gone-page")],
    })
    datastore = _Datastore([page, task, history, file, conflict, missing_owner])
    context = migrations.MigrationContext(datastore.query_factory, datastore.write, datastore)
    outcome = migrate_file_ownership(context)
    assert outcome["changed"] == 1 and outcome["failed"] == 2
    for detail, affected, label in zip(
        outcome["errors"], (conflict, missing_owner), ("Conflicting attachment", "scan.pdf")
    ):
        assert detail["url"] == f"/files/{migrations.encode_urlsafe_key(affected.key)}"
        assert detail["link_label"] == label
    stored = datastore.rows[file.key]
    assert stored["task"] == task.key and "tasks" not in stored and "pages" not in stored
    assert {"task", "page", "file"} <= set(stored["requires"])
    assert datastore.rows[conflict.key] == conflict
    assert datastore.rows[missing_owner.key] == missing_owner
    assert migrate_file_ownership(context)["changed"] == 0


# @matrix permissions migrations : local-restrictions owner-only idempotence
def test_restrictions_migration_only_persists_local_sources():
    from testing.tests_unit.test_018b_database_migrations import _Datastore, _entity
    group = _entity(KINDS.users.value, "group", {"type": "group", "hash": "group"})
    form = _entity(KINDS.models.value, "form", {"type": "form", "groups": [group.key]})
    inherited = _entity(KINDS.instances.value, "page", {"type": "page", "form": form.key})
    owner = _entity(KINDS.instances.value, "owner", {"type": "page", "restricted_to": ["owner"], "groups": [group.key]})
    datastore = _Datastore([group, form, inherited, owner])
    context = migrations.MigrationContext(datastore.query_factory, datastore.write, datastore)
    outcome = migrate_local_restrictions(context)
    assert outcome["changed"] == 1 and outcome["failed"] == 0
    assert datastore.rows[form.key]["restricted_to"] == ["owner", "group"]
    assert "restricted_to" not in datastore.rows[inherited.key]
    assert datastore.rows[owner.key]["restricted_to"] == ["owner"]
    assert migrate_local_restrictions(context)["changed"] == 0


# @matrix permissions search : reconciliation page-override removal batching
def test_reconcile_preserves_page_overrides_and_removes_restrictions(monkeypatch):
    from lagniappe.core.tools.cache.keys import Search
    from lagniappe.core.tools.database.filter import Results
    form = TestEntities.get("FORM", {"hash": "source-form", "restricted_to": ["owner", "new-group"]})
    page = TestEntities.get("PAGE", {"hash": "inherited-page"})
    page.form = form
    explicit = TestEntities.get("PAGE", {"hash": "explicit-page", "restricted_to": ["owner", "old-group"]})
    explicit.form = form
    metadata = {
        "child-task": {"kind": "task", "parent_key": page.hash, "form_key": None},
        "child-file": {"kind": "file", "parent_key": "child-task"},
        "page-file": {"kind": "file", "parent_key": page.hash},
    }
    docs = [SimpleNamespace(id=f"row-{h}", details_key=h, restricted_to="owner,old-group") for h in metadata]
    changes = []

    class Query:
        def __init__(self, kind):
            pass
        def filter(self, value):
            return self
        def limit(self, value):
            return self
        def cursor(self, value):
            return self
        def fetch(self):
            return Results([page, explicit])

    class Pipe:
        def __init__(self):
            self.reads = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def hgetall(self, key):
            self.reads.append(key)
        def eval(self, script, count, *args):
            changes.append(args)
        def execute(self):
            return [{"restricted_to": "owner,old-group"} for _ in self.reads]

    def search(query):
        args = query.get_args()
        assert page.hash in args[0] and explicit.hash not in args[0]
        start = int(args[args.index("LIMIT") + 1])
        return SimpleNamespace(total=3, docs=docs[start:start + 2])

    monkeypatch.setattr(reconcile, "BATCH_SIZE", 2)
    monkeypatch.setattr(reconcile, "Query", Query)
    monkeypatch.setattr(Entities, "fetch_one", lambda *args, **kwargs: form)
    monkeypatch.setattr(Entities, "fetch", lambda *args, **kwargs: list(args))
    monkeypatch.setattr(reconcile, "_load_cached_details", lambda hashes: {h: metadata[h] for h in hashes})
    monkeypatch.setattr(reconcile.cache, "search", search)
    monkeypatch.setattr(reconcile.cache, "pipeline", Pipe)

    following = reconcile.reconcile_batch(form.urlsafe_key)
    assert following == {"source_key": form.urlsafe_key, "cursor": None, "offset": 2}
    assert reconcile.reconcile_batch(**following) is None
    assert ("row-child-file", "owner,new-group") in changes
    assert ("row-page-file", "owner,new-group") in changes
    assert not any(args[0] == Search.page.key(explicit) for args in changes)
    # Repeating the job uses current source state and issues HDEL for removal.
    changes.clear()
    form.db.pop("restricted_to")
    form.properties.restricted_to.unset()
    page.properties.restricted_to.unset()
    following = reconcile.reconcile_batch(form.urlsafe_key)
    reconcile.reconcile_batch(**following)
    assert ("row-child-file", "") in changes
    assert ("row-page-file", "") in changes
    assert explicit.db["restricted_to"] == ["owner", "old-group"]


# @matrix permissions tasks : task-history live-task
def test_history_permissions_follow_live_task(monkeypatch):
    page = TestEntities.get("PAGE", {"hash": "history-page"})
    task = TestEntities.get("TASK", {"hash": "history-task"}, page=page)
    history = Entities.TASK_HISTORY(testing=True)
    history._key = "history"
    history.task = task
    allowed = Mock(return_value=False)
    monkeypatch.setattr(task, "allowed", allowed)
    assert not history.allowed(Action.VIEW, user="viewer")
    allowed.assert_called_once_with(Action.VIEW, user="viewer")
    allowed.return_value = True
    assert history.allowed(Action.EDIT, user="editor")


# @matrix files : ownership move reverse-links unloaded-relation
def test_file_move_does_not_load_previous_task_attachments():
    page = TestEntities.get("PAGE", {"hash": "previous-parent"})
    task = TestEntities.get("TASK", {"hash": "previous-task"}, page=page)
    task.db["files"] = ["moving-file", "unloaded-file"]
    task.properties.files.unset()
    file = TestEntities.get("FILE", {"hash": "moving-file"})
    file.task = task
    file.move_to(page)
    assert task.db["files"] == ["unloaded-file"]
    assert not task.properties.files.is_set
    assert file.owner is page


# @matrix files : ownership move reverse-links unloaded-relation
def test_file_move_does_not_load_destination_task_attachments():
    page = TestEntities.get("PAGE", {"hash": "destination-parent"})
    task = TestEntities.get("TASK", {"hash": "destination-task"}, page=page)
    task.db["files"] = ["unloaded-file"]
    task.properties.files.unset()
    file = TestEntities.get("FILE", {"hash": "moving-file"})
    file.page = page
    file.move_to(task)
    assert task.db["files"] == ["unloaded-file", file.key]
    assert not task.properties.files.is_set
    assert file.owner is task
