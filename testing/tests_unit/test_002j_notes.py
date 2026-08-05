"""Unit coverage for note visibility, queries, and mutation ownership."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import Action, MutationEffectType, MutationOperation
from lagniappe.core.entities import Entities
from lagniappe.core.entities import entity as entity_module
from lagniappe.core.mutations.delete import DeleteCollector
from lagniappe.core.mutations import plan_mutation
from lagniappe.core.tools.database import get as database_get
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


def _user(name, key, *, owner=False, permissions=None):
    return TestEntities.get(
        "USER",
        {
            "name": name,
            "hash": key,
            "owner": owner,
            "permissions": permissions or {},
        },
    )


def _note(parent, author, *, visibility="private", scope="home", body="Note"):
    note = TestEntities.get(
        "NOTE",
        {
            "hash": f"note-{author.key}-{scope}-{visibility}",
            "parent": parent,
            "user": author,
        },
    )
    note.body = body
    note.visibility = visibility
    note.scope = scope
    return note


# @features notes
# @dimensions create body photo parent visibility scope
# @source lagniappe/core/entities/note.py::Note.create
def test_note_create_persists_body_photo_visibility_and_scope(monkeypatch):
    author = _user("Author", "note-create-author")
    photo = SimpleNamespace(filename="note.jpg")

    monkeypatch.setattr(
        entity_module.database,
        "create_key",
        lambda kind, parent=None: f"created-{kind}",
    )
    monkeypatch.setattr(
        Entities.NOTE,
        "save_asset",
        lambda self, value, name, asset_type: {
            "filename": value.filename,
            "name": name,
            "type": asset_type,
        },
    )

    note = Entities.NOTE.create(
        {
            "parent": author,
            "user": author,
            "body": "Body and photo",
            "photo": photo,
            "visibility": "everyone",
            "scope": "home",
        }
    )

    assert note.body == "Body and photo"
    assert note.visibility == "everyone"
    assert note.scope == "home"
    assert note.properties.parent.key == author.key
    assert note.properties.user.key == author.key
    assert note.photo == {"filename": "note.jpg", "name": "photo", "type": "image"}


# @features notes
# @dimensions visibility scope persistence validation
# @source lagniappe/core/properties/activity.py::Visibility
# @source lagniappe/core/properties/activity.py::Scope
def test_note_visibility_and_scope_validate_values():
    author = _user("Author", "note-values-author")
    note = _note(author, author)

    assert note.visibility == "private"
    assert note.scope == "home"

    note.visibility = "everyone"
    note.scope = "page"
    assert note.db["visibility"] == "everyone"
    assert note.db["scope"] == "page"

    with pytest.raises(ValueError, match="visibility"):
        note.visibility = "friends"
    with pytest.raises(ValueError, match="scope"):
        note.scope = "category"


# @features notes permissions
# @dimensions private shared home page creator owner
# @source lagniappe/core/entities/note.py::Note.allowed
def test_note_permissions_follow_visibility_scope_and_authorship():
    author = _user("Author", "note-permission-author")
    viewer = _user("Viewer", "note-permission-viewer")
    owner = _user("Owner", "note-permission-owner", owner=True)
    anonymous = SimpleNamespace(is_authenticated=False, is_owner=False)

    private_home = _note(author, author)
    assert private_home.allowed(Action.VIEW, author) is True
    assert private_home.allowed(Action.DELETE, author) is True
    assert private_home.allowed(Action.VIEW, owner) is True
    assert private_home.allowed(Action.DELETE, owner) is True
    assert private_home.allowed(Action.VIEW, viewer) is False
    assert private_home.allowed(Action.VIEW, anonymous) is False

    shared_home = _note(author, author, visibility="everyone")
    assert shared_home.allowed(Action.VIEW, viewer) is True
    assert shared_home.allowed(Action.EDIT, viewer) is False
    assert shared_home.allowed(Action.DELETE, viewer) is False

    page = TestEntities.get("PAGE", {"name": "Notes Page", "hash": "notes-page"})
    page.allowed = lambda action, user=None: user is viewer and action is Action.VIEW
    shared_page = _note(page, author, visibility="everyone", scope="page")
    assert shared_page.allowed(Action.VIEW, viewer) is True

    page.allowed = lambda action, user=None: False
    assert shared_page.allowed(Action.VIEW, viewer) is False


class _RawActivity(dict):
    def __init__(self, key, **values):
        super().__init__(values)
        self.key = key


class _ActivityQuery:
    def __init__(self, rows):
        self.rows = rows
        self.ancestor_key = None
        self.ordering = None
        self.keys_only_requested = False

    def ancestor(self, key):
        self.ancestor_key = key
        return self

    def filter(self, _filter):
        return self

    def order(self, field):
        self.ordering = field
        return self

    def keys_only(self):
        self.keys_only_requested = True
        return self

    def fetch_all(self):
        return list(self.rows)


class _ActivityFilter:
    def __init__(self):
        self.calls = []

    def eq(self, field, value):
        self.calls.append(("eq", field, value))
        return self

    def contains(self, field, value):
        self.calls.append(("contains", field, value))
        return self


# @features activity
# @dimensions query ancestor type-order
# @source lagniappe/core/tools/database/get.py::activity
def test_activity_query_filters_requested_types(monkeypatch):
    query = _ActivityQuery([_RawActivity("notification", type="notification")])
    activity_filter = _ActivityFilter()
    monkeypatch.setattr(database_get, "datastore_key", lambda _parent: "parent-key")
    monkeypatch.setattr(database_get, "Filter", lambda: activity_filter)
    monkeypatch.setattr(
        database_get,
        "Query",
        lambda kind: query if kind == database_get.KINDS.activity else None,
    )

    results = database_get.activity(object(), types="notification")

    assert [item.key for item in results] == ["notification"]
    assert query.ancestor_key == "parent-key"
    assert query.ordering == "-created"
    assert activity_filter.calls == [("eq", "type", "notification")]


# @pairs notifications:cold-seed notifications:keys-only
# @source lagniappe/core/tools/database/get.py::notification_keys
def test_notification_keys_query_returns_only_ancestor_keys(monkeypatch):
    query = _ActivityQuery(
        [
            _RawActivity("notification-one"),
            _RawActivity("notification-two"),
        ]
    )
    activity_filter = _ActivityFilter()
    monkeypatch.setattr(database_get, "datastore_key", lambda _parent: "parent-key")
    monkeypatch.setattr(database_get, "Filter", lambda: activity_filter)
    monkeypatch.setattr(database_get, "Query", lambda _kind: query)

    results = database_get.notification_keys(object())

    assert results == ["notification-one", "notification-two"]
    assert query.ancestor_key == "parent-key"
    assert query.keys_only_requested is True
    assert activity_filter.calls == [("eq", "type", "notification")]


# @features notes permissions
# @dimensions home shared private owner ordering
# @source lagniappe/core/tools/database/get.py::home_notes
def test_home_notes_return_only_visible_notes(monkeypatch):
    now = datetime.now(timezone.utc)
    public = _RawActivity(
        "public",
        type="note",
        user="other",
        visibility="everyone",
        created=now,
    )
    own_private = _RawActivity(
        "own-private",
        type="note",
        user="viewer",
        visibility="private",
        created=now - timedelta(minutes=1),
    )
    hidden_private = _RawActivity(
        "hidden-private",
        type="note",
        user="other",
        visibility="private",
        created=now - timedelta(minutes=2),
    )
    rows = [public, own_private, hidden_private]

    monkeypatch.setattr(database_get, "Query", lambda _kind: _ActivityQuery(rows))

    viewer = SimpleNamespace(key="viewer", is_owner=False)
    assert [item.key for item in database_get.home_notes(viewer)] == [
        "public",
        "own-private",
    ]

    owner = SimpleNamespace(key="owner", is_owner=True)
    assert [item.key for item in database_get.home_notes(owner)] == [
        "public",
        "own-private",
        "hidden-private",
    ]


# @features notes mutations
# @dimensions delete owner-invalidation page-cascade user-cascade
# @source lagniappe/core/mutations/delete.py::DeleteCollector.note
def test_note_delete_repairs_owners_and_parent_cascades(monkeypatch):
    author = _user("Author", "note-delete-author")
    page = TestEntities.get("PAGE", {"name": "Delete Notes", "hash": "delete-notes"})
    note = _note(page, author, visibility="everyone", scope="page")

    note_plan = plan_mutation(MutationOperation.DELETE, note, registry=Entities)
    effects = {(effect.effect, effect.entity.key) for effect in note_plan.effects if effect.entity}
    assert (MutationEffectType.DELETE, note.key) in effects
    assert (MutationEffectType.UNLINK, page.key) in effects
    assert (MutationEffectType.UNLINK, author.key) in effects

    monkeypatch.setattr(database_get, "page_notes", lambda _page: [note])
    monkeypatch.setattr(database_get, "page_files", lambda _page: [])
    monkeypatch.setattr(database_get, "page_tasks_with_history", lambda _page: [])
    monkeypatch.setattr(
        Entities,
        "fetch",
        lambda *entities, **_kwargs: [
            entity for entity in entities if hasattr(entity, "db")
        ],
    )

    page_plan = plan_mutation(MutationOperation.DELETE, page, registry=Entities)
    deleted = {
        effect.entity.key
        for effect in page_plan.effects
        if effect.effect is MutationEffectType.DELETE
    }
    assert {page.key, note.key}.issubset(deleted)

    home_note = _note(author, author, body="Delete with author")
    monkeypatch.setattr(database_get, "notes_by_user", lambda _user: [home_note])
    collector = DeleteCollector(Entities)
    collector.user_notes(author)
    assert home_note in collector.to_delete
    assert any(survivor.entity is author for survivor in collector.survivors)
