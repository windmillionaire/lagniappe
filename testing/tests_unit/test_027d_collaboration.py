"""Managed-user collaboration and Owner projection contracts."""

from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe.core.definitions import Restriction
from lagniappe.core.entities.page import Page
from lagniappe.core.entities.user import User
from lagniappe.core.tools import collaboration
from lagniappe.core.tools.cache import owner
from testing.utility.messaging_fakes import HashRedis, managed_user


pytestmark = pytest.mark.unit


# @pairs messaging:permission messaging:self-exclusion messaging:public-exclusion
# @pairs messaging:owner-opt-in messaging:managed-user messaging:recipient-resolution
# @pairs mentions:document-view mentions:permission task-assignment:permission
# @source lagniappe/core/tools/collaboration.py::managed_user
# @source lagniappe/core/tools/collaboration.py::can_initiate_messages
# @source lagniappe/core/tools/collaboration.py::recipient_allowed
# @source lagniappe/core/tools/collaboration.py::mention_recipient_allowed
def test_collaboration_permissions_use_current_recipient_and_document_access(
    monkeypatch,
):
    actor = managed_user("actor", "Actor")
    actor.properties = SimpleNamespace(
        restrictions=SimpleNamespace(
            user_message_restrictions=["shared"],
            user_assign_restrictions=["assigned"],
            can_initiate_messages=True,
        )
    )
    assert collaboration.can_initiate_messages(actor)
    actor.properties.restrictions.can_initiate_messages = False
    assert not collaboration.can_initiate_messages(actor)
    actor.properties.restrictions.can_initiate_messages = True
    recipient = managed_user("recipient", "Recipient")
    recipient.requires = ["users", "shared"]

    assert collaboration.recipient_allowed(actor, recipient, channel="message")
    assert not collaboration.recipient_allowed(actor, actor, channel="message")
    public = managed_user("public", "Public", public=True)
    assert not collaboration.recipient_allowed(actor, public, channel="message")

    owner_recipient = managed_user("owner", "Owner", owner_user=True)
    assert not collaboration.recipient_allowed(
        actor, owner_recipient, channel="message"
    )
    owner_recipient.allow_messages_and_mentions = True
    assert collaboration.recipient_allowed(
        actor, owner_recipient, channel="message"
    )

    viewers = []
    document = SimpleNamespace(
        allowed=lambda _action, user: viewers.append(user) or user is recipient
    )
    assert collaboration.mention_recipient_allowed(actor, recipient, document)
    assert viewers == [recipient]

    actor.properties.restrictions.user_message_restrictions = Restriction.UNRESTRICTED
    stranger = managed_user("stranger", "Stranger")
    assert collaboration.recipient_allowed(actor, stranger, channel="message")

    stored_user = User(testing=True)
    stored_page = Page(testing=True)
    stored_page.properties.user._value = stored_user
    monkeypatch.setattr(
        collaboration.Entities,
        "fetch_one",
        lambda identifier, request: stored_user if identifier == "user" else stored_page,
    )
    assert collaboration.resolve_user("user") is stored_user
    assert collaboration.resolve_user("page") is stored_user
# @pairs owner-projection:normalization owner-projection:repair owner-projection:request-memo
# @pairs owner-projection:fail-closed owner-projection:selector-shape owner-projection:revision
# @source lagniappe/core/tools/cache/owner.py::normalize_owner_name
# @source lagniappe/core/tools/cache/owner.py::update_owner_projection
# @source lagniappe/core/tools/cache/owner.py::get_owner_projection
# @source lagniappe/core/tools/cache/owner.py::owner_search_result
def test_owner_projection_normalizes_and_round_trips(monkeypatch):
    redis = HashRedis()
    monkeypatch.setattr(owner.cache, "_redis", redis)
    owner.clear_request_owner_projection()
    user = managed_user("owner", "  JOSÉ   Example  ", owner_user=True)
    page_key = Key("pages", "owner-page", project="messaging-test")
    user.properties = SimpleNamespace(page=SimpleNamespace(key=page_key))
    user.allow_messages_and_mentions = True

    projection = owner.update_owner_projection(user)
    owner.clear_request_owner_projection()
    loaded = owner.get_owner_projection(repair=False)

    assert owner.normalize_owner_name("  Jose\u0301  EXAMPLE ") == "josé example"
    assert projection == loaded
    assert loaded["allow_messages_and_mentions"] is True
    assert loaded["allow_task_assignments"] is False
    result = owner.owner_search_result(loaded)
    assert result["details"]["recipient_key"] == user.urlsafe_key
    assert result["id"] == page_key.to_legacy_urlsafe().decode()


# @pairs messaging:owner-search messaging:self-exclusion messaging:recipient-key
# @pair mentions:recipient-search
# @pairs owner-projection:normalization owner-projection:deduplication
# @source lagniappe/core/tools/collaboration.py::collaboration_user_results
def test_collaboration_search_excludes_self_owner_and_stale_rows(monkeypatch):
    class SearchPage:
        def __init__(self, identifier, user):
            self.urlsafe_key = identifier
            self.user = user

    actor = managed_user("search-actor", "Actor")
    actor.page = SimpleNamespace(urlsafe_key="self-page")
    allowed_user = managed_user("allowed", "Allowed")
    denied_user = managed_user("denied", "Denied")
    pages = {
        "allowed-page": SearchPage("allowed-page", allowed_user),
        "denied-page": SearchPage("denied-page", denied_user),
    }
    projection = {
        "key": "owner-user",
        "page_key": "owner-page",
        "hash": "owner-hash",
        "name": "José Example",
        "normalized_name": "josé example",
        "allow_messages_and_mentions": True,
        "allow_task_assignments": False,
        "revision": 1,
    }
    rows = [
        {"id": "self-page", "name": "Actor", "kind": "user", "details": {}},
        {"id": "owner-page", "name": "Owner", "kind": "user", "details": {}},
        {
            "id": "allowed-page",
            "name": "Allowed",
            "kind": "user",
            "details": {"hash": "allowed-hash"},
        },
        {
            "id": "denied-page",
            "name": "Denied",
            "kind": "user",
            "details": {"hash": "denied-hash"},
        },
        {
            "id": "deleted-page",
            "name": "Deleted",
            "kind": "user",
            "details": {"hash": "deleted-hash"},
        },
    ]
    monkeypatch.setattr(collaboration.cache, "get_owner_projection", lambda: projection)
    monkeypatch.setattr(collaboration.Entities, "PAGE", SearchPage)
    monkeypatch.setattr(
        collaboration.Entities,
        "fetch",
        lambda *identifiers, **_kwargs: [
            pages[identifier] for identifier in identifiers if identifier in pages
        ],
    )
    message_results = collaboration.collaboration_user_results(
        [dict(row) for row in rows], "SÉ ex", "message", actor
    )
    mention_results = collaboration.collaboration_user_results(
        [dict(row) for row in rows],
        "example",
        "mention",
        actor,
        document_identifier="document-key",
    )
    blank_results = collaboration.collaboration_user_results(
        [dict(row) for row in rows], "", "message", actor
    )

    assert [row["id"] for row in message_results] == [
        "allowed-page",
        "denied-page",
        "owner-page",
    ]
    assert message_results[0]["details"]["recipient_key"] == allowed_user.urlsafe_key
    assert [row["id"] for row in mention_results] == [
        "allowed-page",
        "denied-page",
        "owner-page",
    ]
    assert [row["id"] for row in blank_results] == [
        "allowed-page",
        "denied-page",
    ]

