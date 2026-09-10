"""Restriction sources, minimal loading, migrations and queued cache updates."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lagniappe.core.definitions import Action
from lagniappe.core.entities import Entities
from lagniappe.core.definitions.fingerprints import base_fingerprint, restricted_fingerprint
from lagniappe.core.tools.cache.add import _redis_details
from lagniappe.core.exceptions import UnloadedRelationError
from lagniappe.core.tools.auth.restrictions import normalize_restrictions, permission_relation
from lagniappe.core.tools.cache import restrictions as reconcile
from lagniappe.core.tools.cache.keys import Keys, Search
from lagniappe.core.tools.database import migrations
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.database.migration_steps.v2_0_permissions import migrate_file_ownership, migrate_local_restrictions
from testing.utility.test_entities import TestEntities

pytestmark = pytest.mark.unit


class _HashPipeline:
    """Apply the worker's small Redis command set at execute()."""

    def __init__(self, values):
        self.values = values
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def exists(self, key):
        self.commands.append(lambda: key in self.values)

    def hset(self, key, field, value):
        self.commands.append(lambda: self.values.setdefault(key, {}).__setitem__(field, value))

    def hdel(self, key, field):
        self.commands.append(lambda: self.values.get(key, {}).pop(field, None))

    def delete(self, key):
        self.commands.append(lambda: self.values.pop(key, None))

    def execute(self):
        results = [command() for command in self.commands]
        self.commands.clear()
        return results


# @matrix permissions : source-clauses stable-order admin-only
@pytest.mark.parametrize("policy,expected", [
    ({}, {}),
    ({"page": ["b", "a", "b"], "page_form": []}, {"page": ["a", "b"]}),
    ({"page": ["a"], "task_form": ["a", "b"]}, {"page": ["a"], "task_form": ["a", "b"]}),
    ({"page": ["admin", "a"], "page_form": ["b"]}, {"page": ["admin"], "page_form": ["b"]}),
])
def test_restrictions_normalize_source_clauses(policy, expected):
    assert normalize_restrictions(policy) == expected


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


# @matrix permissions : local-restrictions materialization owner-only
def test_local_restrictions_materialize_without_persisting_inheritance():
    form = TestEntities.get("FORM", {"hash": "local-form", "restricted_to": ["form-group"]})
    page = TestEntities.get("PAGE", {"hash": "local-page"})
    page.form = form
    page.properties.restricted_to.materialize()
    assert page.restricted_to == {"page_form": ["form-group"]}
    assert not page.properties.restricted_to.stored
    group = TestEntities.get("USER_GROUP", {"hash": "local-group"})
    page.groups = [group]
    page.properties.restricted_to.materialize(admin_only=False)
    assert page.db["restricted_to"] == ["local-group"]
    assert page.restricted_to == {"page": ["local-group"], "page_form": ["form-group"]}
    page.properties.restricted_to.materialize(admin_only=True)
    assert page.restricted_to == {"page": ["admin"], "page_form": ["form-group"]}


# @matrix files : ownership move reverse-links cardinality parent-key
def test_file_move_preserves_single_ownership():
    page = TestEntities.get("PAGE", {"hash": "move-page"})
    task = TestEntities.get("TASK", {"hash": "move-task"}, page=page)
    task.files = []
    file = TestEntities.get("FILE", {"hash": "move-file"})
    file.page = page
    file.move_to(task)
    assert file.page is None and file.task_page is page and file.task is task
    assert task.files == [file]
    assert {page.hash, task.hash, file.hash} <= set(file.required)
    file.move_to(page)
    assert file.page is page and file.task is None and task.files == []
    assert file.task_page is None
    assert task.hash not in file.required
    file.task = task
    assert file.page is None and file.task_page is page
    file.page = page
    assert file.owner is page and file.task is None and file.task_page is None


# @matrix permissions cache : source-clauses preserved-fields
@pytest.mark.parametrize("kind,form_type,source_policy,expected", [
    ("form", "page", {"page_form": ["new"]}, {"page": ["admin"], "page_form": ["new"], "task_form": ["task"]}),
    ("form", "task", {}, {"page": ["admin"], "page_form": ["old"]}),
    ("page", None, {"page": ["new"]}, {"page": ["new"], "task_form": ["task"]}),
    ("task", None, {"task_form": ["new"]}, {"task_form": ["new"]}),
])
def test_cached_restrictions_resolve_file_task_page_and_form(kind, form_type, source_policy, expected):
    current = {"kind": "file", "modified": "base", "restricted_to": {
        "page": ["admin"], "page_form": ["old"], "task_form": ["task"],
    }}
    source = SimpleNamespace(kind=kind, form_type=form_type, restricted_to=source_policy)
    assert reconcile._projection(current, source)["restricted_to"] == expected
    assert current["restricted_to"] == {"page": ["admin"], "page_form": ["old"], "task_form": ["task"]}


# @matrix permissions cache : change-detection retry form-version
def test_reconciliation_change_detection_and_forced_retry(monkeypatch):
    form = TestEntities.get("FORM", {"hash": "changed-form", "restricted_to": ["new"], "version": "v2"})
    form.version = "v2"
    form._testing = False
    pipe = Mock()
    pipe.__enter__ = Mock(return_value=pipe)
    pipe.__exit__ = Mock(return_value=False)
    pipe.execute.return_value = [json.dumps({"restricted_to": {"page_form": ["new"]}, "form_version": "v1"}), None]
    monkeypatch.setattr(reconcile.cache, "pipeline", lambda: pipe)
    queued = []
    monkeypatch.setattr(reconcile, "enqueue", queued.append)
    previous = reconcile.previous_restrictions([form])
    reconcile.dispatch_changes(previous)
    assert queued == [{"source_key": form.urlsafe_key, "owner_keys": []}]
    reconcile.dispatch_changes([(form, ({"page_form": ["new"]}, "v2"))])
    assert len(queued) == 1
    form._reconcile_restrictions = True
    reconcile.dispatch_changes([(form, ({"page_form": ["new"]}, "v2"))])
    assert len(queued) == 2
    monkeypatch.setattr(reconcile, "enqueue", Mock(side_effect=RuntimeError("queue offline")))
    form._reconcile_restrictions = True
    with pytest.raises(RuntimeError, match="queue offline"):
        reconcile.dispatch_changes([(form, ({"page_form": ["new"]}, "v2"))])
    assert form._reconcile_restrictions is True


# @matrix permissions cache : fingerprint modified form-version stable-order
def test_restricted_fingerprints_share_the_entity_and_cache_formula():
    modified = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    base = base_fingerprint(modified)
    assert base == hashlib.md5(modified.isoformat().encode("utf-8")).hexdigest()
    assert restricted_fingerprint(base, {"page": ["b", "a", "b"]}, form_version="v1") == restricted_fingerprint(base, {"page": ["a", "b"]}, form_version="v1")
    assert restricted_fingerprint(base, {}, form_version="") != restricted_fingerprint(base, {})
    form = TestEntities.get("FORM", {"hash": "fingerprint-form", "restricted_to": ["a"]})
    form.version = "v1"
    page = TestEntities.get("PAGE", {"hash": "fingerprint-page", "modified": modified})
    page.form = form
    task = TestEntities.get("TASK", {"hash": "fingerprint-task", "modified": modified}, page=page)
    task.form = form
    file = TestEntities.get("FILE", {"hash": "fingerprint-file", "modified": modified})
    file.page = page
    for entity in (page, task, file):
        entity._details = {"id": entity.urlsafe_key, "kind": entity.entity_kind}
        cached = _redis_details(entity)
        version = "v1" if entity.entity_kind in {"page", "task"} else None
        assert cached["modified"] == base
        assert cached["fingerprint"] == entity.fingerprint == restricted_fingerprint(base, entity.restricted_to, form_version=version)
        assert cached.get("form_version") == version
        assert cached["id"] == entity.urlsafe_key
        assert entity.modified == modified


# @matrix permissions cache : identity user-page form-version no-extra-read
def test_user_page_cache_identity_preserves_permission_projection(monkeypatch):
    from lagniappe.core.tools.cache.details import identify_entity

    modified = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    page = TestEntities.get("PAGE", {
        "hash": "user-page", "modified": modified,
        "user": {"email": "cache-identity@example.com"},
    })
    page.form = None
    assert page.kind == page.entity_kind == "page"
    assert page.details["kind"] == "user"
    file = TestEntities.get("FILE", {"hash": "user-page-file", "modified": modified})
    file.page = page
    file._details = {"id": file.urlsafe_key, "kind": "file"}
    cached = {entity.hash: _redis_details(entity) for entity in (page, file)}
    assert identify_entity(cached[page.hash]) == (page.urlsafe_key, "page")
    assert cached[page.hash]["kind"] == "user"
    assert all("entity_key" not in row and "entity_kind" not in row for row in cached.values())

    monkeypatch.setattr(Entities, "fetch", Mock(side_effect=AssertionError("identity needs no entity reads")))
    monkeypatch.setattr(reconcile, "Query", Mock(side_effect=AssertionError("cached identity needs no recovery")))
    monkeypatch.setattr(reconcile, "_load_cached_details", lambda hashes: {h: cached[h] for h in hashes})
    page.groups = [TestEntities.get("USER_GROUP", {"hash": "new-group"})]
    page.properties.restricted_to.materialize()
    projections = {entity.hash: reconcile._projection(cached[entity.hash], page) for entity in (page, file)}

    assert projections[page.hash]["form_version"] == ""
    assert projections[file.hash]["form_version"] is None
    for entity in (page, file):
        assert projections[entity.hash]["restricted_to"] == {"page": ["new-group"]}
        assert projections[entity.hash]["fingerprint"] == entity.fingerprint
    assert cached[page.hash]["id"] == page.urlsafe_key
    assert cached[page.hash]["kind"] == "user"


# @matrix permissions cache : fingerprint form-version no-descendant-writes
@pytest.mark.parametrize("form_type", ["page", "task"])
def test_restriction_projection_preserves_own_form_versions_and_base_modified(form_type):
    base = "b" * 32
    clause = f"{form_type}_form"
    source = SimpleNamespace(kind="form", form_type=form_type, version="source-v2",
                             restricted_to={clause: ["new"]})
    targets = [(form_type, True, "source-v2"), ("file", False, None)]
    if form_type == "page":
        targets.append(("task", False, "task-v1"))
    for kind, own_form, version in targets:
        current = {"kind": kind, "modified": base, "form_version": "task-v1", "restricted_to": {
            "page": ["admin"], "page_form": ["old"], "task_form": ["task"],
        }}
        expected = {**current["restricted_to"], clause: ["new"]}
        assert reconcile._projection(current, source, own_form=own_form) == {
            "restricted_to": expected, "form_version": version,
            "fingerprint": restricted_fingerprint(base, expected, form_version=version),
        }
        assert current["form_version"] == "task-v1"
        assert current["modified"] == base


# @matrix permissions cache : channel-invalidation reconciliation
def test_reconciliation_completion_publishes_existing_collection_revisions(monkeypatch):
    from lagniappe.core.tools.database import utility

    row = {"fingerprint": "after-reconciliation"}
    loader = Mock(return_value=[row])
    datastore = SimpleNamespace(put_multi=Mock())
    monkeypatch.setattr(utility, "update_site_fingerprints", loader)
    monkeypatch.setattr(utility, "DATA", SimpleNamespace(datastore=datastore))
    owner = SimpleNamespace(kind="category", key="category")
    touch = Mock()
    update = Mock()
    monkeypatch.setattr(Entities, "touch", touch)
    monkeypatch.setattr(reconcile, "update", update)
    reconcile._publish_completion([owner])
    loader.assert_called_once_with({"type": "task"})
    datastore.put_multi.assert_called_once_with([row])
    touch.assert_called_once_with(owner)
    update.assert_called_once_with(owner)


# @matrix permissions cache : owner-reuse no-extra-read
@pytest.mark.parametrize("kind", ["PAGE", "TASK"])
def test_reconciliation_collects_owner_keys_without_loading_relations(monkeypatch, kind):
    from google.cloud.datastore import Key
    from config.datastore import encode_urlsafe_key

    first = Key(KINDS.models.value, "first-owner", project="owner-discovery")
    second = Key(KINDS.models.value, "second-owner", project="owner-discovery")
    roots = [TestEntities.get(kind, {"hash": f"root-owner-{number}"}) for number in range(3)]
    if kind == "PAGE":
        roots[0].db.update(model=first, categories=[first, second, second])
        roots[1].db.update(categories=[second])
    else:
        roots[0].db.update(project=first)
        roots[1].db.update(project=second)
    monkeypatch.setattr(Entities, "fetch", Mock(side_effect=AssertionError("owner discovery must not fetch")))
    monkeypatch.setattr(Entities, "fetch_one", Mock(side_effect=AssertionError("owner discovery must not fetch")))

    assert reconcile._collection_owner_keys(roots) == {
        encode_urlsafe_key(first), encode_urlsafe_key(second),
    }


# @matrix permissions : queue dispatch
def test_reconciliation_enqueue_uses_current_source_key(monkeypatch):
    monkeypatch.setattr(reconcile, "CONFIG", SimpleNamespace(local=False))
    monkeypatch.setattr(reconcile, "url_for", lambda *args, **kwargs: "https://example.test/process/reconcile-restrictions")
    create = Mock(return_value="queued-task")
    monkeypatch.setattr(reconcile.task_queue, "create_task", create)
    reconcile.enqueue({"source_key": "form-key", "owner_keys": ["category-key"]})
    assert create.call_args.args[1] == {"source_key": "form-key", "owner_keys": ["category-key"]}
    create.return_value = None
    with pytest.raises(RuntimeError, match="retry saving"):
        reconcile.enqueue({"source_key": "form-key", "owner_keys": []})


# @matrix files migrations : single-owner history conflict idempotence
# @pair database-migrations:actionable-links
def test_file_migration_normalizes_history_and_preserves_conflicts():
    from testing.tests_unit.test_018b_database_migrations import _Datastore, _entity, _key
    page = _entity(KINDS.instances.value, "page", {"type": "page", "hash": "page", "requires": ["page", "models"]})
    task = _entity(KINDS.instances.value, "task", {"type": "task", "hash": "task", "page": page.key, "requires": ["page", "models"]})
    history = _entity(KINDS.history.value, "history", {"type": "task_history", "task": task.key})
    file = _entity(KINDS.files.value, "file", {"type": "file", "hash": "file", "tasks": [task.key, history.key]})
    other_page = _entity(KINDS.instances.value, "other-page", {"type": "page", "hash": "other-page"})
    conflict = _entity(KINDS.files.value, "conflict", {"type": "file", "hash": "conflict", "name": "Conflicting attachment", "tasks": [task.key], "pages": [other_page.key]})
    canonical = _entity(KINDS.files.value, "canonical", {"type": "file", "hash": "canonical", "task": task.key, "page": page.key})
    missing_owner = _entity(KINDS.files.value, "missing-owner", {
        "type": "file", "filename": "scan.pdf", "pages": [_key(KINDS.instances.value, "gone-page")],
    })
    same_page_conflict = _entity(KINDS.files.value, "same-page-conflict", {
        "type": "file", "hash": "same-page-conflict", "name": "Separate legacy attachments",
        "pages": [page.key], "tasks": [task.key],
    })
    datastore = _Datastore([page, other_page, task, history, file, conflict, canonical, missing_owner, same_page_conflict])
    context = migrations.MigrationContext(datastore.query_factory, datastore.write, datastore)
    outcome = migrate_file_ownership(context)
    assert outcome["changed"] == 2 and outcome["failed"] == 3
    for detail, affected, label in zip(
        outcome["errors"], (conflict, missing_owner, same_page_conflict),
        ("Conflicting attachment", "scan.pdf", "Separate legacy attachments")
    ):
        assert detail["url"] == f"/files/{migrations.encode_urlsafe_key(affected.key)}"
        assert detail["link_label"] == label
    stored = datastore.rows[file.key]
    assert stored["task"] == task.key and "tasks" not in stored and "pages" not in stored
    assert {"task", "page", "file"} <= set(stored["requires"])
    assert datastore.rows[conflict.key] == conflict
    assert datastore.rows[missing_owner.key] == missing_owner
    assert datastore.rows[same_page_conflict.key] == same_page_conflict
    assert datastore.rows[canonical.key]["page"] == page.key
    assert datastore.rows[canonical.key]["task"] == task.key
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


# @matrix permissions search : reconciliation local-restrictions removal batching source-clauses
# @matrix permissions cache : owner-reuse
@pytest.mark.parametrize("separate_batch", [False, True])
def test_reconcile_preserves_local_page_groups_and_removes_form_restrictions(monkeypatch, separate_batch):
    from google.cloud.datastore import Entity as DatastoreEntity, Key
    from lagniappe.core.tools.database.filter import Results
    modified = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    form = TestEntities.get("FORM", {"hash": "source-form", "restricted_to": ["new-group"], "version": "v2", "modified": modified})
    form.version = "v2"
    page = TestEntities.get("PAGE", {"hash": "inherited-page", "modified": modified})
    page.form = form
    explicit = TestEntities.get("PAGE", {"hash": "explicit-page", "restricted_to": ["explicit-group"], "modified": modified})
    explicit.form = form
    category, additional, last_owner = (
        Entities.CATEGORY(DatastoreEntity(key=Key(KINDS.models.value, name, project="owner-discovery")), testing=True)
        for name in ("page-category", "additional-category", "last-category")
    )
    for owner in (category, additional, last_owner):
        owner.kind = "category"
    page.db["model"] = category.key
    explicit.db.update(model=category.key, categories=[category.key, additional.key, additional.key])
    owner_keys = sorted([category.urlsafe_key, additional.urlsafe_key])
    last_page = TestEntities.get("PAGE", {"hash": "last-page", "modified": modified})
    last_page.form = form
    last_page.db["model"] = last_owner.key
    task_form = TestEntities.get("FORM", {"hash": "task-form", "restricted_to": ["task-group"], "modified": modified})
    task_form.version = "task-v1"
    task = TestEntities.get("TASK", {"hash": "child-task", "modified": modified}, page=page)
    task.form = task_form
    file = TestEntities.get("FILE", {"hash": "child-file", "modified": modified})
    file.task = task
    page_file = TestEntities.get("FILE", {"hash": "page-file", "modified": modified})
    page_file.page = page
    entities = {entity.urlsafe_key: entity for entity in (form, page, explicit, last_page, task_form, task, file, page_file)}
    values = {Keys.ENTITY_HASHES.value: {}}
    for entity in entities.values():
        entity._details = {"id": entity.urlsafe_key, "kind": entity.entity_kind}
        if entity is task:
            entity._details["parent"] = {"hash": page.hash}
        details = _redis_details(entity)
        if entity in (page, explicit):
            details["form_version"] = "v1"
            details["fingerprint"] = restricted_fingerprint(details["modified"], entity.restricted_to, form_version="v1")
        values[Keys.ENTITY_HASHES.value][entity.hash] = json.dumps(details)
        values[Search[entity.kind].key(entity)] = {"name": entity.hash}
    docs = [SimpleNamespace(id=Search[entity.kind].key(entity), details_key=entity.hash) for entity in (task, file, page_file)]
    entities.update({owner.urlsafe_key: owner for owner in (category, additional, last_owner)})
    calls = []
    completed = []

    class Query:
        def __init__(self, kind):
            pass
        def filter(self, value):
            return self
        def limit(self, value):
            return self
        def cursor(self, value):
            self.current_cursor = value
            return self
        def fetch(self):
            if self.current_cursor:
                assert self.current_cursor == "more-roots"
                return Results([last_page])
            return Results([page, explicit], next_cursor="more-roots" if separate_batch else None)

    def search(query):
        args = query.get_args()
        if last_page.hash in args[0]:
            return SimpleNamespace(total=0, docs=[])
        assert page.hash in args[0] and explicit.hash in args[0]
        start = int(args[args.index("LIMIT") + 1])
        return SimpleNamespace(total=3, docs=docs[start:start + 2])

    def fetch(*rows, request):
        calls.append(request)
        if request.depth.value == 1:
            assert list(rows) == sorted([*owner_keys, *([last_owner.urlsafe_key] if separate_batch else [])])
        return [entities[row] if isinstance(row, str) else row for row in rows]

    def cached(hashes):
        return {h: json.loads(values[Keys.ENTITY_HASHES.value][h]) for h in hashes if h in values[Keys.ENTITY_HASHES.value]}

    monkeypatch.setattr(reconcile, "BATCH_SIZE", 2)
    monkeypatch.setattr(reconcile, "Query", Query)
    monkeypatch.setattr(Entities, "fetch_one", lambda *args, **kwargs: form)
    monkeypatch.setattr(Entities, "fetch", fetch)
    monkeypatch.setattr(reconcile, "_load_cached_details", cached)
    monkeypatch.setattr(reconcile, "_publish_completion", completed.append)
    monkeypatch.setattr(reconcile, "_membership_revision", lambda: "membership")
    monkeypatch.setattr(reconcile.cache, "search", search)
    monkeypatch.setattr(reconcile.cache, "pipeline", lambda: _HashPipeline(values))
    monkeypatch.setattr(reconcile, "update", Mock(side_effect=AssertionError("unchanged authoritative rows need no repair")))
    following = reconcile.reconcile_batch(form.urlsafe_key)
    assert following == {"source_key": form.urlsafe_key, "owner_keys": owner_keys, "cursor": None, "offset": 2, "revision": "membership"}
    assert completed == []
    following = reconcile.reconcile_batch(**following)
    if separate_batch:
        assert following == {"source_key": form.urlsafe_key, "owner_keys": owner_keys, "cursor": "more-roots", "offset": 0, "revision": "membership"}
        assert completed == []
        following = reconcile.reconcile_batch(**following)
    assert following is None
    expected_keys = sorted([*owner_keys, *([last_owner.urlsafe_key] if separate_batch else [])])
    assert completed == [[entities[key] for key in expected_keys]]
    assert {call.depth.value for call in calls} == {0, 1, 2}
    assert sum(call.depth.value == 1 for call in calls) == 1
    updated = cached(entities)
    assert updated[file.hash]["restricted_to"] == {"page_form": ["new-group"], "task_form": ["task-group"]}
    assert values[Search.file.key(file)]["restricted_to_page_form"] == "new-group"
    assert values[Search.file.key(file)]["restricted_to_task_form"] == "task-group"
    assert updated[task.hash]["form_version"] == "task-v1"
    assert updated[explicit.hash]["restricted_to"] == {"page": ["explicit-group"], "page_form": ["new-group"]}
    assert updated[explicit.hash]["form_version"] == "v2"
    form.db.pop("restricted_to")
    form.properties.restricted_to.unset()
    page.properties.restricted_to.unset()
    last_page.properties.restricted_to.unset()
    task.properties.restricted_to.unset()
    file.properties.restricted_to.unset()
    page_file.properties.restricted_to.unset()
    following = reconcile.reconcile_batch(form.urlsafe_key)
    while following:
        following = reconcile.reconcile_batch(**following)
    assert cached([file.hash])[file.hash]["restricted_to"] == {"task_form": ["task-group"]}
    assert "restricted_to_page_form" not in values[Search.file.key(page_file)]
    assert explicit.db["restricted_to"] == ["explicit-group"]


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


# @matrix permissions cache : preserved-fields restriction-removal batch-write
def test_restriction_batch_updates_only_projection_fields(monkeypatch):
    details = {
        "page": {"id": "page-key", "kind": "page", "fingerprint": "old-page", "modified": "page-base",
                 "name": "Page name", "form_version": "v1", "parent_key": "category"},
        "file": {"id": "file-key", "kind": "file", "fingerprint": "old-file", "modified": "file-base",
                 "name": "File name", "restricted_to": {"page_form": ["old"]}, "form_version": "obsolete", "parent_key": "task"},
        "hidden": {"id": "hidden-key", "kind": "file", "fingerprint": "old-hidden", "modified": "hidden-base"},
    }
    rows = {h: f"search-{h}" for h in details}
    projections = {
        "page": {"restricted_to": {"page": ["a", "b"], "task_form": ["admin"]}, "form_version": "v2", "fingerprint": "new-page"},
        "file": {"restricted_to": {}, "form_version": None, "fingerprint": "new-file"},
        "hidden": {"restricted_to": {"page": ["a"]}, "form_version": None, "fingerprint": "new-hidden"},
    }
    values = {
        Keys.ENTITY_HASHES.value: {h: json.dumps(item) for h, item in details.items()},
        "search-page": {"name": "Indexed page name", "requires": "untouched"},
        "search-file": {"name": "Indexed file name", "restricted_to_page_form": "old"},
    }
    monkeypatch.setattr(reconcile.cache, "pipeline", lambda: _HashPipeline(values))
    reconcile._write_projections(details, rows, projections)
    updated = {h: json.loads(raw) for h, raw in values[Keys.ENTITY_HASHES.value].items()}
    for entity_hash in details:
        assert updated[entity_hash]["fingerprint"] == projections[entity_hash]["fingerprint"]
        for field in ("id", "kind", "modified", "name", "parent_key"):
            assert updated[entity_hash].get(field) == details[entity_hash].get(field)
    assert updated["page"]["restricted_to"] == {"page": ["a", "b"], "task_form": ["admin"]}
    assert updated["page"]["form_version"] == "v2"
    assert "restricted_to" not in updated["file"]
    assert "form_version" not in updated["file"]
    assert values["search-page"] == {"name": "Indexed page name", "requires": "untouched", "restricted_to_page": "a,b", "restricted_to_task_form": "admin"}
    assert values["search-file"] == {"name": "Indexed file name"}
    assert "search-hidden" not in values
    assert details["file"]["restricted_to"] == {"page_form": ["old"]}


# @matrix permissions cache : cache-miss no-extra-read
def test_reconciliation_reads_available_cache_details_without_recovery(monkeypatch):
    source = TestEntities.get("PAGE", {"hash": "available-source", "restricted_to": ["a"]})
    source.form = None
    file = TestEntities.get("FILE", {"hash": "available-file"})
    file.page = source
    entities = {entity.urlsafe_key: entity for entity in (source, file)}
    cached = {}
    for entity in entities.values():
        entity._details = {"id": entity.urlsafe_key, "kind": entity.entity_kind}
        cached[entity.hash] = _redis_details(entity)
    cached[source.hash]["parent_key"] = "not-a-worker-dependency"
    reads = []

    def load(hashes):
        reads.append(set(hashes))
        assert "not-a-worker-dependency" not in hashes
        return {h: cached[h] for h in hashes if h in cached}

    monkeypatch.setattr(reconcile, "Query", Mock(side_effect=AssertionError("no cache-hole Datastore query")))
    monkeypatch.setattr(Entities, "fetch_one", lambda *args, **kwargs: source)
    monkeypatch.setattr(Entities, "fetch", lambda *ids, **kwargs: [entities[key] for key in ids])
    monkeypatch.setattr(reconcile, "update", Mock(side_effect=AssertionError("no cache-hole writes")))
    monkeypatch.setattr(reconcile, "_load_cached_details", load)
    monkeypatch.setattr(reconcile, "_membership_revision", lambda: "stable")
    monkeypatch.setattr(reconcile, "_publish_completion", Mock())
    write = Mock()
    monkeypatch.setattr(reconcile, "_write_projections", write)
    monkeypatch.setattr(reconcile.cache, "search", lambda query: SimpleNamespace(total=2, docs=[
        SimpleNamespace(id=Search.file.key(file), details_key=file.hash),
        SimpleNamespace(id="missing-search-row", details_key="missing-target"),
    ]))
    assert reconcile.reconcile_batch(source.urlsafe_key) is None
    assert reads == [{source.hash, file.hash, "missing-target"}, {source.hash, file.hash}]
    assert set(write.call_args.args[1]) == {source.hash, file.hash}


# @matrix permissions cache : batching concurrent-move continuation-restart
def test_reconciliation_restarts_when_membership_changes_between_or_during_batches(monkeypatch):
    source = TestEntities.get("PAGE", {"hash": "membership-source"})
    source.form = None
    source._details = {"id": source.urlsafe_key, "kind": source.entity_kind}
    details = {source.hash: _redis_details(source)}
    search = Mock(return_value=SimpleNamespace(total=0, docs=[]))
    complete = Mock()
    write = Mock()
    monkeypatch.setattr(Entities, "fetch_one", lambda *args, **kwargs: source)
    monkeypatch.setattr(Entities, "fetch", lambda *args, **kwargs: [source])
    monkeypatch.setattr(reconcile.cache, "search", search)
    monkeypatch.setattr(reconcile, "_load_cached_details", lambda *args: details)
    monkeypatch.setattr(reconcile, "_write_projections", write)
    monkeypatch.setattr(reconcile, "_publish_completion", complete)
    monkeypatch.setattr(reconcile, "_membership_revision", lambda: "new-membership")
    restart = {"source_key": source.urlsafe_key, "owner_keys": ["category-key"]}
    assert reconcile.reconcile_batch(**restart, offset=100, revision="old-membership") == restart
    search.assert_not_called()
    write.assert_not_called()
    monkeypatch.setattr(reconcile, "_membership_revision", Mock(side_effect=["before", "after"]))
    assert reconcile.reconcile_batch(**restart) == restart
    write.assert_called_once()
    complete.assert_not_called()


# @matrix permissions cache : concurrent-save deleted-row fingerprint reconciliation retry
@pytest.mark.parametrize("change", ["repair", "cache-overwrite", "retry", "source-change", "deleted", "missing-target"])
def test_reconciliation_verifies_repairs_and_retries(monkeypatch, change):
    from google.cloud.datastore import Entity as DatastoreEntity, Key

    modified = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    source_key = Key(KINDS.instances.value, "verification-page", project="permissions-unit")
    file_key = Key(KINDS.files.value, "verification-file", project="permissions-unit")
    owner_key = Key(KINDS.models.value, "verification-owner", project="permissions-unit")

    def make_page(groups):
        row = DatastoreEntity(key=source_key)
        row.update(type="page", hash="verification-source", modified=modified, restricted_to=groups)
        entity = Entities.PAGE(row, testing=True)
        entity.form = None
        entity._details = {"id": entity.urlsafe_key, "kind": "page"}
        return entity

    def make_file(parent, revision=0):
        row = DatastoreEntity(key=file_key)
        row.update(type="file", hash="verification-target", modified=modified + timedelta(seconds=revision),
                   name=f"File revision {revision}")
        entity = Entities.FILE(row, testing=True)
        entity.page = parent
        entity._details = {"id": entity.urlsafe_key, "kind": "file", "name": entity.name}
        return entity

    source = make_page(["a"])
    target = make_file(source)
    owner = SimpleNamespace(kind="category", key=owner_key)
    owner_keys = [owner_key.to_legacy_urlsafe().decode()]
    details = {entity.hash: _redis_details(entity) for entity in (source, target)}
    values = {
        Keys.ENTITY_HASHES.value: {h: json.dumps(item) for h, item in details.items()},
        Search.page.key(source): {"name": "Source"},
        Search.file.key(target): {"name": "File revision 0"},
    }
    if change == "missing-target":
        values[Keys.ENTITY_HASHES.value].pop(target.hash)
    reads, repairs, completed = [], [], []
    latest = {}

    def cached(hashes):
        return {h: json.loads(values[Keys.ENTITY_HASHES.value][h]) for h in hashes if h in values[Keys.ENTITY_HASHES.value]}

    def fetch(*identifiers, request):
        if request.depth.value == 1:
            assert list(identifiers) == owner_keys
            return [owner]
        assert request.depth.value == 2
        assert all(isinstance(identifier, str) for identifier in identifiers)
        assert set(identifiers) <= {source.urlsafe_key, target.urlsafe_key}
        assert source.hash not in identifiers and target.hash not in identifiers
        reads.append(identifiers)
        fresh_source = make_page(["b"] if change == "source-change" else ["a"])
        revision = len(reads) if change == "retry" else int(change == "repair")
        fresh_target = make_file(fresh_source, revision)
        latest.update(source=fresh_source, target=fresh_target)
        if change == "cache-overwrite" and len(reads) == 1:
            stale = cached([target.hash])[target.hash]
            stale.update(fingerprint="another-worker-stale-revision", restricted_to={"page": ["stale"]})
            values[Keys.ENTITY_HASHES.value][target.hash] = json.dumps(stale)
        available = {fresh_source.urlsafe_key: fresh_source}
        if change != "deleted":
            available[fresh_target.urlsafe_key] = fresh_target
        return [available[identifier] for identifier in identifiers if identifier in available]

    def update(*entities, **kwargs):
        assert kwargs == {"update": False}
        repairs.append(tuple(entity.hash for entity in entities))
        for entity in entities:
            values[Keys.ENTITY_HASHES.value][entity.hash] = json.dumps(_redis_details(entity))

    monkeypatch.setattr(Entities, "fetch_one", lambda identifier, **kwargs: source)
    monkeypatch.setattr(Entities, "fetch", fetch)
    monkeypatch.setattr(reconcile.cache, "search", lambda query: SimpleNamespace(
        total=1, docs=[SimpleNamespace(id=Search.file.key(target), details_key=target.hash)],
    ))
    monkeypatch.setattr(reconcile.cache, "pipeline", lambda: _HashPipeline(values))
    monkeypatch.setattr(reconcile, "_load_cached_details", cached)
    monkeypatch.setattr(reconcile, "_membership_revision", lambda: "membership")
    monkeypatch.setattr(reconcile, "_publish_completion", completed.append)
    monkeypatch.setattr(reconcile, "update", update)

    if change == "retry":
        with pytest.raises(RuntimeError, match="kept changing"):
            reconcile.reconcile_batch(source.urlsafe_key, owner_keys=owner_keys)
        assert len(reads) == len(repairs) == reconcile.VERIFICATION_ATTEMPTS
        assert completed == []
        return

    result = reconcile.reconcile_batch(source.urlsafe_key, owner_keys=owner_keys, cursor="old-cursor")
    if change == "source-change":
        assert result == {"source_key": source.urlsafe_key, "owner_keys": owner_keys}
        assert completed == []
        assert len(reads) == 2
        assert set(repairs[0]) == {source.hash, target.hash}
    else:
        assert result is None
        assert completed == [[owner]]
    if change == "deleted":
        assert target.hash not in values[Keys.ENTITY_HASHES.value]
        assert Search.file.key(target) not in values
        assert repairs == []
    elif change == "missing-target":
        assert target.hash not in cached([target.hash])
        assert all(target.urlsafe_key not in identifiers for identifiers in reads)
        assert repairs == []
    else:
        stored = cached([target.hash])[target.hash]
        assert stored["fingerprint"] == latest["target"].fingerprint
        assert stored["restricted_to"] == latest["target"].restricted_to
        assert len(reads) == 2 and len(repairs) == 1


# @matrix permissions cache : reserved-form form-version no-extra-read
def test_reserved_form_is_not_a_cached_permission_source(monkeypatch):
    from lagniappe.core.properties import common_entity
    from lagniappe.core.tools.cache import add
    from lagniappe.core.tools.database.defaults import DEFAULT_USER_FORM

    default = Entities.FORM(testing=True)
    default._key = default._urlsafe_key = "installation-form"
    default.db.update(DEFAULT_USER_FORM)
    page = TestEntities.get("PAGE", {"hash": "default-page", "restricted_to": ["a"]})
    page.form = default
    task_form = TestEntities.get("FORM", {"hash": "task-form", "restricted_to": ["b"]})
    task_form.version = "v1"
    task = TestEntities.get("TASK", {"hash": "default-task"}, page=page)
    task.form = task_form
    file = TestEntities.get("FILE", {"hash": "default-file"})
    file.task = task

    monkeypatch.setattr(common_entity, "short_hash", Mock(side_effect=AssertionError("default form needs no hash")))
    monkeypatch.setattr(add.cache, "pipeline", Mock(side_effect=AssertionError("default form must not be cached")))
    monkeypatch.setattr(reconcile, "Query", Mock(side_effect=AssertionError("no dependency Datastore reads")))
    monkeypatch.setattr(Entities, "fetch", Mock(side_effect=AssertionError("reuse attached dependencies")))
    add.update(default, update=False)

    cached = {}
    for entity in (page, task, file, task_form):
        entity._details = {"id": entity.urlsafe_key, "kind": entity.entity_kind}
        if entity is task:
            entity._details["parent"] = {"hash": page.hash}
        cached[entity.hash] = _redis_details(entity)
    assert cached[page.hash]["form_version"] == (default.version or "")
    assert cached[task.hash]["form_version"] == "v1"
    page.groups = [TestEntities.get("USER_GROUP", {"hash": "c"})]
    page.properties.restricted_to.materialize()
    assert reconcile._projection(cached[task.hash], page)["restricted_to"] == {"page": ["c"], "task_form": ["b"]}
    assert reconcile._projection(cached[task.hash], page)["form_version"] == "v1"
    assert reconcile._projection(cached[file.hash], page)["restricted_to"] == {"page": ["c"], "task_form": ["b"]}
    assert "hash" not in default.db


# @matrix permissions cache : cache-miss source-intent programmatic-save
@pytest.mark.parametrize("kind", ["page", "task"])
def test_cold_source_details_preserve_programmatic_restriction_changes(monkeypatch, kind):
    from lagniappe.core.definitions import MutationEffectType
    from lagniappe.core.mutations.executor import consume_mutation_intents

    page = TestEntities.get("PAGE", {"hash": "cold-programmatic-page"})
    if kind == "page":
        source = page
        source.db["restricted_to"] = ["old-group"]
        source.properties.restricted_to.materialize(admin_only=False)
    else:
        source = TestEntities.get("TASK", {"hash": "cold-programmatic-task"}, page=page)
        source.form = TestEntities.get("FORM", {"hash": "old-form", "restricted_to": ["old-group"]})
        source._permission_sources_changed = False
        source.form = None
    assert source._permission_sources_changed is True
    assert not source.restricted_to
    consume_mutation_intents(SimpleNamespace(
        consumed_intents=[], effects=[SimpleNamespace(
            effect=MutationEffectType.UPSERT, property_mask=None, entity=source,
        )],
    ))
    assert source._permission_sources_changed is False
    assert source._reconcile_restrictions is True
    source._testing = False
    pipe = Mock()
    pipe.__enter__ = Mock(return_value=pipe)
    pipe.__exit__ = Mock(return_value=False)
    pipe.execute.return_value = [None, None]
    queued = []
    monkeypatch.setattr(reconcile.cache, "pipeline", lambda: pipe)
    monkeypatch.setattr(reconcile, "enqueue", queued.append)
    reconcile.dispatch_changes(reconcile.previous_restrictions([source]))
    assert queued == [{"source_key": source.urlsafe_key, "owner_keys": []}]
