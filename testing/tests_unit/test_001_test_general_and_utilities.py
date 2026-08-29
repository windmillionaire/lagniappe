"""Unit tests for general infrastructure and core utility functions."""

from types import SimpleNamespace

from flask import Flask, g
import pytest
import sentry_sdk
from lagniappe import CONFIG
from lagniappe.core import exceptions as core_exceptions
from lagniappe.core.definitions import (
    Action,
    Fetch,
    FetchDepth,
    FetchReason,
    MutationEffectType,
    Restriction,
)
from lagniappe.core.definitions import identifiers
from lagniappe.core.entities import Entities
from lagniappe.core import entities as entities_module
from lagniappe.core.mutations import delete as delete_module
from lagniappe.core.mutations import executor as mutation_executor
from lagniappe.core.exceptions import entity_load as entity_load_module
from lagniappe.core.exceptions import unloaded_relations as unloaded_relations_module
from lagniappe.core.exceptions import UnloadedRelationError
from lagniappe.core.mixins.related import RelatedEntityListMixin, RelatedEntityMixin
from lagniappe.core.properties.base_db import DBProperty
from lagniappe.core.tools import diagnostics
from lagniappe.core.tools.auth import agent_access
from lagniappe.core.tools.auth import context as user_context
from lagniappe.core.tools.database.filter import Filter
from lagniappe.core.tools.files import html as html_tools
from lagniappe.core.tools.tasks import ordering
from testing.utility.test_entities import TestEntities, TestUser as _TestUser

pytestmark = pytest.mark.unit


class _TraceListRelation(RelatedEntityListMixin, DBProperty):
    _id = "items"
    _label = "Items"


class _TraceSingleRelation(RelatedEntityMixin, DBProperty):
    _id = "owner"
    _label = "Owner"


# @matrix deferred-jobs error-handling : sentry terminal-delivery
def test_error_capture_can_wait_for_sentry_delivery(monkeypatch):
    error = ValueError("terminal failure")
    captured = []
    flushed = []
    monkeypatch.setattr(
        core_exceptions,
        "CONFIG",
        SimpleNamespace(capture_errors=True),
    )
    monkeypatch.setattr(sentry_sdk, "capture_exception", captured.append)
    monkeypatch.setattr(
        sentry_sdk,
        "flush",
        lambda *, timeout: flushed.append(timeout),
    )

    core_exceptions.capture(error, wait_for_delivery=True)

    assert captured == [error]
    assert flushed == [2.0]


# @matrix error-reporting : payload-bounds privacy redaction
def test_error_context_sanitizer_redacts_nested_secrets_and_bounds_payloads():
    context = {
        "password": "top-level-secret",
        "nested": [
            {
                "apiKey": "nested-secret",
                "detail": "request failed with password=inline-secret",
                "authorization_note": "Bearer bearer-secret",
                "quoted_detail": 'password="quoted secret value"',
                "refreshTokens": ["plural-token-secret"],
                "input_tokens": 42,
            }
        ],
        "private_material": (
            "-----BEGIN PRIVATE KEY-----\nprivate-key-secret\n-----END PRIVATE KEY-----"
        ),
        "body": {"safe-looking": "body-secret"},
        "long_text": "x" * 700,
        "many": list(range(40)),
        "large_mapping": {f"field_{index}": index for index in range(40)},
    }

    sanitized = core_exceptions.sanitize_error_context(context)
    serialized = repr(sanitized)

    for secret in (
        "top-level-secret",
        "nested-secret",
        "inline-secret",
        "quoted secret value",
        "bearer-secret",
        "plural-token-secret",
        "private-key-secret",
        "body-secret",
    ):
        assert secret not in serialized
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"][0]["apiKey"] == "[REDACTED]"
    assert sanitized["nested"][0]["refreshTokens"] == "[REDACTED]"
    assert sanitized["nested"][0]["input_tokens"] == 42
    assert sanitized["body"] == "[REDACTED]"
    assert sanitized["long_text"].endswith("… [truncated]")
    assert len(sanitized["many"]) == 25
    assert sanitized["large_mapping"]["_truncated_items"] == 15


# @matrix error-reporting : privacy redaction url-metadata
def test_error_context_sanitizer_replaces_urls_with_bounded_metadata():
    context = {
        "URL": (
            "HTTPS://private-user:private-password@Example.COM:8443/secret/path"
            "?signed=private-query#private-fragment"
        ),
        "nested": {"url": "http://[invalid-host"},
    }

    sanitized = core_exceptions.sanitize_error_context(context)
    serialized = repr(sanitized)

    for secret in (
        "private-user",
        "private-password",
        "secret/path",
        "private-query",
        "private-fragment",
    ):
        assert secret not in serialized
    assert sanitized["URL"] == {
        "parseable": True,
        "has_path": True,
        "has_query": True,
        "has_fragment": True,
        "has_credentials": True,
        "scheme": "https",
        "host": "example.com",
        "port": 8443,
    }
    assert sanitized["nested"]["url"] == {
        "parseable": False,
        "has_path": False,
        "has_query": False,
        "has_fragment": False,
        "has_credentials": False,
    }


# @matrix error-reporting : payload-bounds privacy request-context
def test_request_info_uses_bounded_structural_allowlist():
    app = Flask("request-privacy-test")

    @app.post("/items/<item_key>")
    def update_item(item_key):
        return item_key

    query = "&".join(
        [
            "search=query-secret",
            "password=password-secret",
            "repeated=one",
            "repeated=two",
            *(f"field_{index}=value-{index}" for index in range(30)),
        ]
    )
    with app.test_request_context(
        f"/items/private-route-value?{query}",
        method="POST",
        json={
            "password": "json-secret",
            "document": "document-secret",
        },
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer authorization-secret",
            "Cookie": "session=cookie-secret",
            "User-Agent": "Lagniappe Privacy Test",
            "X-Api-Key": "header-secret",
            "X-Lagniappe-Request": "true",
            "X-Unlisted": "unlisted-secret",
        },
    ):
        info = core_exceptions.extract_request_info()

    serialized = repr(info)
    for secret in (
        "query-secret",
        "password-secret",
        "private-route-value",
        "json-secret",
        "document-secret",
        "authorization-secret",
        "cookie-secret",
        "header-secret",
        "unlisted-secret",
    ):
        assert secret not in serialized
    assert info["method"] == "POST"
    assert info["endpoint"] == "update_item"
    assert info["route"] == "/items/<item_key>"
    assert info["route_parameters"] == ["item_key"]
    assert info["query_parameters"]["field_count"] == 33
    assert len(info["query_parameters"]["fields"]) == 25
    assert info["query_parameters"]["truncated"] is True
    assert {"Accept", "User-Agent", "X-Lagniappe-Request"} <= info["headers"].keys()
    assert "url" not in info
    assert "view_args" not in info
    assert "form" not in info
    assert "json" not in info
    assert "files" not in info
    assert info["body_metadata"]["content_type"] == "application/json"


# @matrix error-reporting : payload-bounds privacy redaction request-context sentry-event
def test_sentry_event_sanitizer_removes_sdk_request_payloads():
    event = {
        "request": {
            "url": "https://example.test/items/private-id?token=query-secret",
            "method": "POST",
            "query_string": "token=query-secret",
            "data": {"document": "request-body-secret"},
            "cookies": {"session": "cookie-secret"},
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer authorization-secret",
                "User-Agent": "Lagniappe Privacy Test",
                "X-Api-Key": "header-secret",
            },
        },
        "user": {"email": "private@example.test"},
        "contexts": {
            "auth": {
                "password": "context-secret",
                "email": "nested-email-secret@example.test",
            }
        },
        "exception": {
            "values": [
                {
                    "value": "failed with password=exception-secret",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "example.py",
                                "vars": {"secret": "frame-secret"},
                            }
                        ]
                    },
                }
            ]
        },
        "spans": [
            {
                "description": "provider request",
                "data": {
                    "prompt": "prompt-secret",
                    "http.response.status_code": 500,
                },
            }
        ],
    }

    sanitized = core_exceptions.sanitize_sentry_event(event)
    serialized = repr(sanitized)

    for secret in (
        "private-id",
        "query-secret",
        "request-body-secret",
        "cookie-secret",
        "authorization-secret",
        "header-secret",
        "private@example.test",
        "context-secret",
        "nested-email-secret@example.test",
        "exception-secret",
        "frame-secret",
        "prompt-secret",
    ):
        assert secret not in serialized
    assert sanitized["request"] == {
        "method": "POST",
        "headers": {
            "Accept": "application/json",
            "User-Agent": "Lagniappe Privacy Test",
        },
    }
    assert "user" not in sanitized
    assert sanitized["contexts"]["auth"]["password"] == "[REDACTED]"
    assert sanitized["spans"][0]["data"]["prompt"] == "[REDACTED]"
    assert sanitized["spans"][0]["data"]["http.response.status_code"] == 500


# @matrix error-handling : privacy redaction request-context sentry
def test_error_capture_sanitizes_context_without_duplicate_request(monkeypatch):
    class Scope:
        def __init__(self):
            self.contexts = {}
            self.extras = {}

        def set_context(self, key, value):
            self.contexts[key] = value

        def set_extra(self, key, value):
            self.extras[key] = value

    class ScopeManager:
        def __init__(self, scope):
            self.scope = scope

        def __enter__(self):
            return self.scope

        def __exit__(self, *_args):
            return False

    error = ValueError("terminal failure")
    scope = Scope()
    captured = []
    request_extractions = []
    monkeypatch.setattr(
        core_exceptions,
        "CONFIG",
        SimpleNamespace(capture_errors=True),
    )
    monkeypatch.setattr(
        core_exceptions,
        "extract_request_info",
        lambda: request_extractions.append(True),
    )
    monkeypatch.setattr(sentry_sdk, "push_scope", lambda: ScopeManager(scope))
    monkeypatch.setattr(sentry_sdk, "capture_exception", captured.append)

    core_exceptions.capture(
        error,
        {
            "request": {
                "method": "POST",
                "query_parameters": {"field_count": 2},
                "body_metadata": {"content_type": "application/json"},
            },
            "api_token": "capture-secret",
            "detail": "password=inline-secret",
        },
    )

    assert captured == [error]
    assert request_extractions == []
    assert scope.contexts == {
        "request": {
            "method": "POST",
            "query_parameters": {"field_count": 2},
            "body_metadata": {"content_type": "application/json"},
        }
    }
    assert scope.extras["api_token"] == "[REDACTED]"
    assert "inline-secret" not in scope.extras["detail"]


# @pair entities:initialization
def test_entities_initialized():
    """Verify Entities registry is initialized by unit-test conftest."""
    assert hasattr(Entities, "PROJECT")
    assert hasattr(Entities, "PAGE")
    assert hasattr(Entities, "TASK")
    assert hasattr(Entities, "_load")
    assert not hasattr(Entities, "load")
    assert not hasattr(Entities, "get")


# @matrix mutations : batch dedupe delete
def test_entities_delete_accepts_batch_and_dedupes(monkeypatch):
    class DB(dict):
        pass

    class Modified:
        def update(self):
            return None

    def entity(key):
        return SimpleNamespace(
            key=key,
            entity_kind="file",
            assets={},
            db=DB(),
            properties={"modified": Modified()},
            exclude_from_index=frozenset(),
        )

    first = entity("first")
    second = entity("second")
    child = entity("child")
    update = entity("update")
    captured = {}

    class Planner:
        def collect(self, root, collector):
            collector.delete(root)
            collector.delete(child)
            if root is first:
                collector.repair(update, reason="dependent-owner")

    events = []

    def database_delete(to_delete):
        events.append("delete")
        captured["delete"] = to_delete

    monkeypatch.setattr(delete_module, "delete_planner_for", lambda _entity: Planner())
    monkeypatch.setattr(mutation_executor.database_utility, "delete_entities", database_delete)
    monkeypatch.setattr(
        mutation_executor.database_utility,
        "save_mutations",
        lambda writes: (
            events.append("survivors"),
            captured.setdefault("save", list(writes)),
        ),
    )
    monkeypatch.setattr(
        mutation_executor.cache,
        "delete",
        lambda to_delete: (
            events.append("cache-delete"),
            captured.setdefault("cache_delete", to_delete),
        ),
    )
    monkeypatch.setattr(
        mutation_executor.cache,
        "update",
        lambda *entities: events.append("cache-refresh"),
    )

    outcome = Entities.delete(first, second)

    assert list(captured["delete"]) == [first, child, second]
    assert list(captured["cache_delete"]) == [first, child, second]
    assert captured["save"] == [(update, ("modified",))]
    assert events == [
        "survivors",
        "delete",
        "cache-refresh",
        "cache-delete",
    ]
    assert outcome.complete is True


# @matrix entities : cascade delete user-page
def test_collect_entities_deletes_user_and_page_together(monkeypatch):
    user = Entities.USER(testing=True)
    user._key = "delete-user"
    user.kind = "user"
    user.name = "Delete User"

    page = Entities.PAGE(testing=True)
    page._key = "delete-user-page"
    page.kind = "page"
    page.name = "Delete User Page"

    users_model = Entities.USERS(testing=True)
    users_model._key = "users-model"
    users_model.kind = "users"
    users_model.name = "Users"
    users_model.db["reserved"] = True

    page.model = users_model
    user.page = page

    assert page.model is users_model
    assert page.categories == []

    monkeypatch.setattr(delete_module.DeleteCollector, "page_tasks", lambda *_: None)
    monkeypatch.setattr(delete_module.DeleteCollector, "page_files", lambda *_: None)
    monkeypatch.setattr(delete_module.DeleteCollector, "page_notes", lambda *_: None)
    monkeypatch.setattr(delete_module.DeleteCollector, "user_notes", lambda *_: None)
    monkeypatch.setattr(delete_module.DeleteCollector, "user_messages", lambda *_: None)

    collector = delete_module.DeleteCollector(Entities)
    collector.collect(page)

    assert collector.to_delete == [user, page]
    assert collector.survivors == []

    collector = delete_module.DeleteCollector(Entities)
    collector.collect(user)

    assert collector.to_delete == [user, page]
    assert collector.survivors == []

    stored_user = Entities.USER(testing=True)
    stored_user._key = "stored-user"
    stored_page = Entities.PAGE(testing=True)
    stored_page._key = "stored-page"
    stored_page.db["user"] = stored_user.key
    monkeypatch.setattr(
        entities_module.Entities,
        "fetch_one",
        lambda key, *, request: stored_user,
    )

    collector = delete_module.DeleteCollector(Entities)
    collector.collect(stored_page)

    assert collector.to_delete == [stored_user, stored_page]
    assert collector.survivors == []


# @matrix entities pages users : category-fallback delete preserve-page search-cache user-unlink
# @pair mutations:preserve-user-pages
def test_collect_user_delete_can_preserve_page(monkeypatch):
    monkeypatch.setattr(delete_module.DeleteCollector, "user_notes", lambda *_: None)
    monkeypatch.setattr(delete_module.DeleteCollector, "user_messages", lambda *_: None)

    users_model = Entities.USERS(testing=True)
    users_model._key = "preserve-users-model"
    users_model.kind = "users"
    users_model.name = "Users"
    users_model.db["reserved"] = True

    uncategorized = Entities.CATEGORY(testing=True)
    uncategorized._key = "preserve-uncategorized"
    uncategorized.kind = "category"
    uncategorized.name = "Uncategorized Pages"
    monkeypatch.setattr(
        Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: uncategorized,
    )

    user = Entities.USER(testing=True)
    user._key = "preserve-user"
    user.kind = "user"
    user.name = "Preserved Page User"

    page = Entities.PAGE(testing=True)
    page._key = "preserved-user-page"
    page.kind = "page"
    page.name = "Preserved User Page"
    page.model = users_model
    page.categories = []
    user.page = page

    collector = delete_module.DeleteCollector(
        Entities,
        preserve_user_pages=True,
    )
    collector.collect(user)

    assert collector.to_delete == [user]
    assert [survivor.entity for survivor in collector.survivors] == [
        page,
        users_model,
    ]
    assert collector.search_deletes == [("user", page)]
    assert page.user is None
    assert page.model is uncategorized
    assert page.categories == [uncategorized]

    category = Entities.CATEGORY(testing=True)
    category._key = "preserve-existing-category"
    category.kind = "category"
    category.name = "Existing Category"

    categorized_user = Entities.USER(testing=True)
    categorized_user._key = "preserve-categorized-user"
    categorized_user.kind = "user"
    categorized_user.name = "Categorized User"

    categorized_page = Entities.PAGE(testing=True)
    categorized_page._key = "preserved-categorized-page"
    categorized_page.kind = "page"
    categorized_page.name = "Preserved Categorized Page"
    categorized_page.model = users_model
    categorized_page.categories = [category]
    categorized_user.page = categorized_page

    plan = delete_module.plan_delete(
        categorized_user,
        registry=Entities,
        preserve_user_pages=True,
    )

    assert categorized_page.user is None
    assert categorized_page.model is None
    assert categorized_page.categories == [category]
    assert any(
        effect.effect is MutationEffectType.DELETE and effect.entity is categorized_user
        for effect in plan.effects
    )
    assert any(
        effect.effect is MutationEffectType.UNLINK and effect.entity is categorized_page
        for effect in plan.effects
    )
    assert any(
        effect.effect is MutationEffectType.CACHE_SEARCH_DELETE
        and effect.entity is categorized_page
        and effect.cache_kind == "user"
        for effect in plan.effects
    )


# @matrix entities tasks : cascade delete list-owner-fingerprint
def test_collect_task_delete_updates_task_list_owners(monkeypatch):
    page = TestEntities.get("PAGE", {"name": "Task Page", "hash": "tskownerpg"})
    project = TestEntities.get(
        "PROJECT",
        {"name": "Task Project", "hash": "tskownerprj"},
    )
    assigned_page = TestEntities.get(
        "PAGE",
        {"name": "Assigned Page", "hash": "tskownerasg"},
    )
    linked_page = TestEntities.get(
        "PAGE",
        {"name": "Linked Page", "hash": "tskownerlnk"},
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Delete Owner Task",
            "hash": "tskowner",
            "page": {"name": page.name, "hash": page.hash},
            "project": {"name": project.name, "hash": project.hash},
        },
    )
    task.properties.page._value = page
    task.properties.project._value = project
    task.properties.assigned_to._value = assigned_page
    task.properties.linked_pages._value = [linked_page]

    monkeypatch.setattr(delete_module.DeleteCollector, "task_files", lambda *_: None)
    collector = delete_module.DeleteCollector(Entities)
    collector.collect(task)

    assert collector.to_delete == [task]
    assert [survivor.entity for survivor in collector.survivors] == [
        page,
        project,
        assigned_page,
        linked_page,
    ]
    assert all(
        survivor.property_updates == {"modified"} for survivor in collector.survivors
    )


# @matrix entities forms : cascade delete forms list-owner-fingerprint
def test_collect_form_delete_updates_form_users(monkeypatch):
    form = TestEntities.get("FORM", {"name": "Deleted Form", "hash": "formowner"})
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Form Category", "hash": "formownercat"},
    )
    project = TestEntities.get(
        "PROJECT",
        {"name": "Form Project", "hash": "formownerprj"},
    )

    monkeypatch.setattr(
        entities_module.database_get,
        "form_users",
        lambda *forms: [category, project],
    )
    monkeypatch.setattr(
        entities_module.Entities,
        "fetch",
        lambda *identifiers, request: [category, project],
    )

    collector = delete_module.DeleteCollector(Entities)
    collector.collect(form)

    assert collector.to_delete == [form]
    assert [survivor.entity for survivor in collector.survivors] == [
        category,
        project,
    ]


# @matrix testing users : current-user resolver
def test_current_user_prefers_explicit_user():
    explicit = _TestUser(owner=False)
    CONFIG.TEST_CURRENT_USER = _TestUser(owner=True)

    assert user_context.current_context_user(explicit) is explicit


# @matrix testing users : config-mutable current-user resolver
def test_current_user_uses_config_test_user_without_request():
    configured = _TestUser(owner=False)
    CONFIG.TEST_CURRENT_USER = configured

    assert user_context.current_context_user() is configured


# @matrix testing users : current-user flask-request resolver
def test_current_user_prefers_flask_user_over_config(monkeypatch):
    app = Flask(__name__)
    request_user = _TestUser(owner=False)
    CONFIG.TEST_CURRENT_USER = _TestUser(owner=True)
    monkeypatch.setattr(user_context, "current_user", request_user)

    with app.test_request_context("/demo", method="GET"):
        assert user_context.current_context_user() is request_user


# @matrix property : current-user propagation
def test_property_defaults_to_config_test_user():
    configured = _TestUser(owner=False)
    CONFIG.TEST_CURRENT_USER = configured
    entity = SimpleNamespace(db={})

    prop = _TraceSingleRelation(entity=entity)

    assert prop.user is configured


# @matrix login : agent-access code-validation config
def test_agent_access_config_and_user_helpers(monkeypatch):
    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_ENABLED", False, raising=False)
    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_CODE", "secret-code", raising=False)
    monkeypatch.setattr(
        CONFIG, "AGENT_ACCESS_EMAIL", "Agent@Example.COM", raising=False
    )
    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_NAME", "Review Agent", raising=False)

    assert not agent_access.enabled()

    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_ENABLED", "False", raising=False)
    assert not agent_access.enabled()

    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_ENABLED", "True", raising=False)
    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_CODE", " ", raising=False)
    assert not agent_access.enabled()

    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_CODE", "secret-code", raising=False)
    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_ENABLED", True, raising=False)

    assert agent_access.enabled()
    assert agent_access.code_matches(" secret-code ")
    assert not agent_access.code_matches("wrong-code")


# @matrix login : agent-access groups user user-page
def test_agent_access_user_helper_creates_or_loads_user_with_groups(monkeypatch):
    monkeypatch.setattr(
        CONFIG, "AGENT_ACCESS_EMAIL", "Agent@Example.COM", raising=False
    )
    monkeypatch.setattr(CONFIG, "AGENT_ACCESS_NAME", "Review Agent", raising=False)

    events = []
    existing_user = None

    class FakeUser:
        def __init__(self, db, groups=None, permissions=None):
            self.db = db
            self.groups = groups or []
            self.page = SimpleNamespace(hash="agent-page")
            self._permissions = dict(permissions or db.get("permissions", {}))
            self.last_login = None

        @property
        def permissions(self):
            return self._permissions

        @permissions.setter
        def permissions(self, value):
            self._permissions = value
            self.db["permissions"] = value

        def has_permission(self, resource, action=Action.ALL):
            return Action[self.permissions.get(resource.hash)].implies(action)

        def save(self):
            events.append(
                (
                    "save",
                    self.db["email"],
                    [group.name for group in self.groups],
                    dict(self.permissions),
                    self.last_login is not None,
                )
            )

    class FakeUserFactory:
        def __call__(self, db):
            events.append(("load", db["email"]))
            return FakeUser(db)

        def create(self, data):
            events.append(("create", data))
            return FakeUser(data, permissions={"agent-page": "EDIT"})

    class FakeEntities:
        USER = FakeUserFactory()

        @staticmethod
        def fetch_one(db, *, request):
            events.append(
                ("load-user", db["email"], request.depth is FetchDepth.NESTED)
            )
            return FakeUser(db, [SimpleNamespace(name="Assigned Group")])

    def fake_get_user(email):
        events.append(("get", email))
        return existing_user

    monkeypatch.setattr(agent_access.database_get, "user", fake_get_user)
    monkeypatch.setattr(agent_access, "Entities", FakeEntities)

    created = agent_access.get_or_create_user()

    assert created.db == {
        "email": "agent@example.com",
        "name": "Review Agent",
    }
    assert created.groups == []
    assert created.permissions == {"agent-page": "EDIT"}
    assert events == [
        ("get", "agent@example.com"),
        ("create", {"email": "agent@example.com", "name": "Review Agent"}),
        ("save", "agent@example.com", [], {"agent-page": "EDIT"}, True),
    ]

    events.clear()
    existing_user = {"email": "agent@example.com", "name": "Existing Agent"}

    loaded = agent_access.get_or_create_user()

    assert loaded.db == existing_user
    assert [group.name for group in loaded.groups] == ["Assigned Group"]
    assert loaded.permissions == {"agent-page": "EDIT"}
    assert events == [
        ("get", "agent@example.com"),
        ("load-user", "agent@example.com", True),
        (
            "save",
            "agent@example.com",
            ["Assigned Group"],
            {"agent-page": "EDIT"},
            True,
        ),
    ]


# @matrix permissions testing : entity-allowed no-testing-shortcut
def test_testing_entity_allowed_uses_real_permissions():
    entity = TestEntities.get(
        "CATEGORY",
        {"name": "Locked Category", "hash": "locked", "requires": ["locked"]},
    )
    user = _TestUser(owner=False, permissions={})

    assert entity._testing is True
    assert entity.allowed(Action.VIEW, user=user) is False


# @matrix entities : fetch no-extra-read typed-entity
def test_entities_fetch_root_reuses_typed_entity_without_database_fetch(monkeypatch):
    entity = TestEntities.get(
        "CATEGORY",
        {"name": "Loaded Category", "hash": "loaded-category"},
    )

    def fail_database_read(identifier):
        raise AssertionError(f"unexpected database read for {identifier!r}")

    monkeypatch.setattr(entities_module.database_get, "entity", fail_database_read)

    assert Entities.fetch_one(entity, request=Fetch.root()) is entity


# @pair relations:attach-cache
def test_related_attach_caches_attached_entity_map():
    page = TestEntities.get(
        "PAGE",
        {"name": "Attach Cache Page", "hash": "attach-cache-page"},
    )
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Attach Cache Category", "hash": "attach-cache-category"},
    )
    page.db["model"] = category.key

    page.properties.model.attach({category.key: category})

    assert page.properties.model.attached_entities == {category.key: category}


# @matrix entities relations : attached-cache load no-extra-read
def test_entities_fetch_reuses_cached_attached_relations(monkeypatch):
    page = TestEntities.get(
        "PAGE",
        {"name": "Loaded Page", "hash": "loaded-page"},
    )
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Loaded Category", "hash": "loaded-category"},
    )
    extra = TestEntities.get(
        "CATEGORY",
        {"name": "Extra Category", "hash": "extra-category"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Loaded Form", "hash": "loaded-form"},
    )

    category.db["form"] = form.key
    category.properties.form.attach({form.key: form})
    page.model = category
    page.db["categories"] = [extra.key]
    page.properties.categories.attach({extra.key: extra})

    def fail_database_read(keys):
        if keys:
            raise AssertionError(f"unexpected database read for {keys!r}")
        return []

    monkeypatch.setattr(entities_module.database_get, "entities", fail_database_read)

    assert Entities.fetch(page, request=Fetch.direct()) == [page]


# @matrix relations : attached-cache root-precedence
# @pair entities:explicit-fetch-depth
def test_entities_fetch_preserves_explicit_root_over_shallow_attached_copy(monkeypatch):
    authoritative_page = TestEntities.get(
        "PAGE",
        {
            "name": "Authoritative Page",
            "hash": "authoritative-page",
            "model": {"name": "Loaded Model", "hash": "loaded-model"},
        },
    )
    shallow_page = TestEntities.get(
        "PAGE",
        {"name": "Shallow Page", "hash": "shallow-page"},
    )
    shallow_page.db["hash"] = authoritative_page.key
    shallow_page.db["model"] = authoritative_page.model.key
    shallow_page.properties.model.unset()

    task = TestEntities.get(
        "TASK",
        {
            "name": "Task With Shallow Page",
            "hash": "task-with-shallow-page",
        },
    )
    task.page = shallow_page

    def fail_database_read(keys):
        if keys:
            raise AssertionError(f"unexpected database read for {keys!r}")
        return []

    monkeypatch.setattr(entities_module.database_get, "entities", fail_database_read)

    loaded = Entities.fetch(task, authoritative_page, request=Fetch.direct())

    assert loaded == [task, authoritative_page]
    assert task.page is authoritative_page
    assert task.page.model.name == "Loaded Model"


# @pairs entities:explicit-fetch-depth permissions:registered-reason
def test_fetch_requires_registered_reason_for_nested_depth():
    assert Fetch.root().depth is FetchDepth.ROOT
    assert Fetch.direct().depth is FetchDepth.DIRECT

    nested = Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)
    assert nested.depth is FetchDepth.NESTED
    assert nested.reason is FetchReason.TASK_SAVE_REQUIREMENTS

    with pytest.raises(ValueError, match="registered FetchReason"):
        Fetch(FetchDepth.NESTED)
    with pytest.raises(ValueError, match="registered FetchReason"):
        Fetch.nested(because="unregistered-reason")
    with pytest.raises(ValueError, match="Only nested"):
        Fetch(FetchDepth.DIRECT, FetchReason.TASK_SAVE_REQUIREMENTS)


# @matrix relations : direct nested root
# @pair entities:explicit-fetch-depth
@pytest.mark.parametrize(
    ("fetch", "expected_calls", "has_category", "has_form"),
    [
        (Fetch.root(), [], False, False),
        (Fetch.direct(), [["fetch-category"]], True, False),
        (
            Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
            [["fetch-category"], ["fetch-form"]],
            True,
            True,
        ),
    ],
)
@pytest.mark.parametrize("identifier_kind", ["typed", "key"])
def test_entities_fetch_applies_total_depth_to_key_and_typed_entity(
    monkeypatch,
    fetch,
    expected_calls,
    has_category,
    has_form,
    identifier_kind,
):
    page = TestEntities.get(
        "PAGE",
        {"name": "Fetch Page", "hash": "fetch-page"},
    )
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Fetch Category", "hash": "fetch-category"},
    )
    form = TestEntities.get(
        "FORM",
        {"name": "Fetch Form", "hash": "fetch-form"},
    )
    page.db["model"] = category.key
    category.db["form"] = form.key

    entities = {page.key: page, category.key: category, form.key: form}
    calls = []

    monkeypatch.setattr(
        entities_module.database_get,
        "datastore_key",
        lambda identifier: identifier,
    )

    def load_entities(keys):
        calls.append(list(keys))
        return [entities[key] for key in keys if key in entities]

    monkeypatch.setattr(entities_module.database_get, "entities", load_entities)

    identifier = page if identifier_kind == "typed" else page.key
    assert Entities.fetch(identifier, request=fetch) == [page]
    root_calls = [] if identifier_kind == "typed" else [[page.key]]
    assert calls == root_calls + expected_calls
    assert (page.model is category) is has_category
    if has_form:
        assert category.form is form
    else:
        assert category.properties.form.is_set is False


# @matrix relations : direct stale-key
# @pair entities:explicit-fetch-depth
def test_entities_fetch_attaches_survivors_from_fully_resolved_relation(monkeypatch):
    page = TestEntities.get(
        "PAGE",
        {"name": "Page With Deleted Category", "hash": "page-stale-category"},
    )
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Surviving Category", "hash": "surviving-category"},
    )
    model = TestEntities.get(
        "CATEGORY",
        {"name": "Page Model", "hash": "page-model"},
    )
    deleted_key = "deleted-category"
    page.db["model"] = model.key
    page.db["categories"] = [category.key, deleted_key]
    calls = []

    def load_entities(keys):
        calls.append(list(keys))
        return [entity for entity in (model, category) if entity.key in keys]

    monkeypatch.setattr(entities_module.database_get, "entities", load_entities)

    assert Entities.fetch(page, request=Fetch.direct()) == [page]
    assert len(calls) == 1
    assert set(calls[0]) == {model.key, category.key, deleted_key}
    assert page.categories == [model, category]


# @pairs entities:batch relations:root
def test_entities_fetch_batches_unresolved_roots_once(monkeypatch):
    first = TestEntities.get(
        "CATEGORY",
        {"name": "First Root", "hash": "first-root"},
    )
    second = TestEntities.get(
        "FORM",
        {"name": "Second Root", "hash": "second-root"},
    )
    entities = {first.key: first, second.key: second}
    calls = []

    monkeypatch.setattr(
        entities_module.database_get,
        "datastore_key",
        lambda identifier: identifier,
    )

    def load_entities(keys):
        calls.append(list(keys))
        return [entities[key] for key in keys]

    monkeypatch.setattr(entities_module.database_get, "entities", load_entities)

    loaded = Entities.fetch(first.key, second.key, request=Fetch.root())

    assert {entity.key for entity in loaded} == {first.key, second.key}
    assert calls == [[first.key, second.key]]


# @matrix entities : batch explicit-fetch-depth
# @pair relations:root
def test_entities_fetch_deduplicates_mixed_roots_and_skips_missing(monkeypatch):
    first = TestEntities.get(
        "CATEGORY",
        {"name": "Typed Root", "hash": "typed-root"},
    )
    second = TestEntities.get(
        "FORM",
        {"name": "Stored Root", "hash": "stored-root"},
    )
    missing = "missing-root"
    calls = []

    monkeypatch.setattr(
        entities_module.database_get,
        "datastore_key",
        lambda identifier: identifier,
    )

    def load_entities(keys):
        calls.append(list(keys))
        return [second] if second.key in keys else []

    monkeypatch.setattr(entities_module.database_get, "entities", load_entities)

    loaded = Entities.fetch(
        first,
        second.key,
        second.key,
        missing,
        request=Fetch.root(),
    )

    assert {entity.key for entity in loaded} == {first.key, second.key}
    assert calls == [[second.key, missing]]


# @pairs entities:explicit-fetch-depth relations:root
def test_entities_fetch_root_does_not_attach_cross_root_relations(monkeypatch):
    page = TestEntities.get(
        "PAGE",
        {"name": "Partial Root Page", "hash": "partial-root-page"},
    )
    model = TestEntities.get(
        "CATEGORY",
        {"name": "Root Model", "hash": "root-model"},
    )
    other = TestEntities.get(
        "CATEGORY",
        {"name": "Unloaded Category", "hash": "unloaded-category"},
    )
    page.db["model"] = model.key
    page.db["categories"] = [other.key]
    page.properties.model.unset()
    page.properties.categories.unset()

    monkeypatch.setattr(
        entities_module.database_get,
        "entities",
        lambda keys: (_ for _ in ()).throw(
            AssertionError(f"unexpected database read for {keys!r}")
        ),
    )

    assert Entities.fetch(page, model, request=Fetch.root()) == [page, model]
    assert page.properties.model.is_set is False
    assert page.properties.categories.is_set is False


# @pairs entities:reference-details relations:direct
def test_reference_details_does_not_derive_requirements_from_unloaded_relations():
    page = TestEntities.get(
        "PAGE",
        {"name": "Shallow Reference Page", "hash": "shallow-reference-page"},
    )
    page.db["model"] = "unloaded-model"
    page.db.pop("requires", None)

    details = page.reference_details

    assert details["name"] == page.name
    assert "requires" not in details
    assert page.properties.model.is_set is False


# @pairs entities:explicit-fetch-depth relations:direct
def test_entities_fetch_reuses_attached_direct_relations(monkeypatch):
    page = TestEntities.get(
        "PAGE",
        {"name": "Attached Page", "hash": "attached-page"},
    )
    category = TestEntities.get(
        "CATEGORY",
        {"name": "Attached Category", "hash": "attached-category"},
    )
    page.db["model"] = category.key
    page.properties.model.attach({category.key: category})

    def fail_database_read(keys):
        if keys:
            raise AssertionError(f"unexpected database read for {keys!r}")
        return []

    monkeypatch.setattr(entities_module.database_get, "entities", fail_database_read)

    assert Entities.fetch(page, request=Fetch.direct()) == [page]
    assert page.model is category


# @pairs entities:explicit-fetch-depth relations:root
def test_entities_fetch_one_returns_entity_or_none(monkeypatch):
    form = TestEntities.get(
        "FORM",
        {"name": "One Form", "hash": "one-form"},
    )
    monkeypatch.setattr(
        entities_module.database_get,
        "datastore_key",
        lambda identifier: identifier,
    )
    monkeypatch.setattr(
        entities_module.database_get,
        "entities",
        lambda keys: [form] if form.key in keys else [],
    )

    assert Entities.fetch_one(form.key, request=Fetch.root()) is form
    assert Entities.fetch_one("missing-form", request=Fetch.root()) is None


# @pair entities:load-tracing
def test_record_entity_load_trace_uses_request_context(monkeypatch):
    app = Flask(__name__)
    monkeypatch.setattr(
        entity_load_module, "CONFIG", SimpleNamespace(DEBUG_TRACING=True)
    )
    monkeypatch.setattr(entity_load_module, "_trace_caller", lambda: "demo.py:1 caller")

    with app.test_request_context("/demo", method="GET"):
        entity_load_module.record_entity_load_trace(
            primary={},
            secondary={
                "model-1": SimpleNamespace(kind="models", name="Task Model"),
                "page-1": SimpleNamespace(kind="instances", name="Caleb Page"),
            },
            related={"model-2": SimpleNamespace(kind="models", name="Page Model")},
            first_batch_key_count=2,
            related_key_count=1,
        )

        assert g.entity_loads == [
            {
                "operation": "load",
                "caller": "demo.py:1 caller",
                "primary": [],
                "secondary": ["models:Task Model", "instances:Caleb Page"],
                "related": ["models:Page Model"],
                "first_batch_keys": 2,
                "related_batch_keys": 1,
                "first_batch_calls": 1,
                "related_batch_calls": 1,
                "db_reads": 2,
            }
        ]


# @pair entities:load-tracing
def test_record_entity_load_trace_skips_no_database_work(monkeypatch):
    app = Flask(__name__)
    monkeypatch.setattr(
        entity_load_module, "CONFIG", SimpleNamespace(DEBUG_TRACING=True)
    )

    with app.test_request_context("/demo", method="GET"):
        entity_load_module.record_entity_load_trace(
            primary={"category-1": SimpleNamespace(kind="category", name="Projects")},
            secondary={},
            related={},
            first_batch_key_count=0,
            related_key_count=0,
        )

        assert not hasattr(g, "entity_loads")


# @matrix permissions : explicit-fetch-depth registered-reason
# @pair entities:load-tracing
def test_record_entity_load_trace_includes_fetch_scope(monkeypatch):
    app = Flask(__name__)
    monkeypatch.setattr(
        entity_load_module, "CONFIG", SimpleNamespace(DEBUG_TRACING=True)
    )
    monkeypatch.setattr(entity_load_module, "_trace_caller", lambda: "auth.py:1")

    with app.test_request_context("/tasks/demo", method="GET"):
        entity_load_module.record_entity_load_trace(
            primary={},
            secondary={"task": SimpleNamespace(kind="task", name="Demo")},
            related={},
            first_batch_key_count=1,
            related_key_count=0,
            fetch_depth="NESTED",
            fetch_reason="report-route-projection",
            fetch_stage="roots",
        )

        assert g.entity_loads[0]["fetch_depth"] == "NESTED"
        assert g.entity_loads[0]["fetch_reason"] == "report-route-projection"
        assert g.entity_loads[0]["fetch_stage"] == "roots"


# @pair entities:load-tracing
def test_print_entity_load_trace_outputs_request_summary(monkeypatch, capsys):
    app = Flask(__name__)
    monkeypatch.setattr(
        entity_load_module, "CONFIG", SimpleNamespace(DEBUG_TRACING=True)
    )

    with app.test_request_context("/categories/demo?cursor=abc", method="GET"):
        g.entity_loads = [
            {
                "operation": "get",
                "caller": "lagniappe/web/auth.py:59 wrapped",
                "primary": ["category:Books"],
                "secondary": [],
                "related": [],
                "first_batch_keys": 1,
                "related_batch_keys": 0,
                "first_batch_calls": 1,
                "related_batch_calls": 0,
                "db_reads": 1,
            },
            {
                "operation": "load",
                "caller": "lagniappe/core/entities/index.py:42 pages",
                "primary": [],
                "secondary": ["models:Task Model", "instances:Caleb Page"],
                "related": ["models:Page Model"],
                "first_batch_keys": 2,
                "related_batch_keys": 1,
                "first_batch_calls": 1,
                "related_batch_calls": 1,
                "db_reads": 2,
            },
            {
                "operation": "load",
                "primary": [],
                "secondary": [],
                "related": [],
                "first_batch_keys": 0,
                "related_batch_keys": 0,
                "first_batch_calls": 0,
                "related_batch_calls": 0,
            },
        ]

        entity_load_module.print_entity_load_trace(SimpleNamespace(status_code=200))
        assert g.entity_load_trace_printed is True

    output = capsys.readouterr().out
    assert (
        "[entity-loads] GET /categories/demo?cursor=abc "
        "status=200 endpoint=- rule=-: "
        "2 entity calls, 3 db reads, 3 first-batch keys, 1 related keys"
    ) in output
    assert (
        "[entity-loads]   #1 get caller=lagniappe/web/auth.py:59 wrapped "
        "primary=category:Books secondary=- related=-"
    ) in output
    assert (
        "[entity-loads]   #2 load caller=lagniappe/core/entities/index.py:42 pages "
        "primary=- secondary=models:Task Model, instances:Caleb Page "
        "related=models:Page Model"
    ) in output
    assert "category:Projects" not in output


# @matrix relations : diagnostics unloaded-fallback
def test_related_list_value_reports_unloaded_relation_without_loading(monkeypatch):
    captured = []
    monkeypatch.setattr(
        unloaded_relations_module,
        "CONFIG",
        SimpleNamespace(CAPTURE_UNLOADED_RELATIONS=True, STRICT_RELATION_LOADS=False),
    )
    monkeypatch.setattr(
        unloaded_relations_module,
        "capture",
        lambda error, context=None, level="error": captured.append(
            (error, context, level)
        ),
    )

    entity = SimpleNamespace(
        entity_kind="page",
        kind="page",
        name="Demo Page",
        id="page-1",
        hash="page-hash",
        urlsafe_key="page-key",
        db={"items": [SimpleNamespace(kind="task", name="Follow-up")]},
    )
    prop = _TraceListRelation(entity=entity)

    assert prop.value == []
    assert prop.value == []

    assert len(captured) == 1
    error, context, level = captured[0]
    assert isinstance(error, UnloadedRelationError)
    assert level == "warning"
    assert context["relation_type"] == "list"
    assert context["fallback"] == []
    assert context["entity"]["kind"] == "page"
    assert context["property"]["id"] == "items"
    assert context["keys"] == ["task:Follow-up"]
    assert (
        "test_related_list_value_reports_unloaded_relation_without_loading"
        in (context["caller"])
    )


# @matrix relations : diagnostics unloaded-fallback
def test_related_single_value_reports_unloaded_relation_without_loading(monkeypatch):
    captured = []
    monkeypatch.setattr(
        unloaded_relations_module,
        "CONFIG",
        SimpleNamespace(CAPTURE_UNLOADED_RELATIONS=True, STRICT_RELATION_LOADS=False),
    )
    monkeypatch.setattr(
        unloaded_relations_module,
        "capture",
        lambda error, context=None, level="error": captured.append(
            (error, context, level)
        ),
    )
    app = Flask(__name__)

    entity = SimpleNamespace(
        entity_kind="task",
        kind="task",
        name="Write summary",
        id="task-1",
        hash="task-hash",
        urlsafe_key="task-key",
        db={"owner": SimpleNamespace(kind="page", id="page-1")},
    )
    prop = _TraceSingleRelation(entity=entity)

    with app.test_request_context("/tasks/demo", method="GET"):
        assert prop.value is None
        assert prop.value is None

    assert len(captured) == 1
    error, context, level = captured[0]
    assert isinstance(error, UnloadedRelationError)
    assert level == "warning"
    assert context["relation_type"] == "single"
    assert context["fallback"] is None
    assert context["entity"]["kind"] == "task"
    assert context["property"]["id"] == "owner"
    assert context["keys"] == ["page:page-1"]
    assert context["request"]["path"] == "/tasks/demo"


# @matrix relations : diagnostics strict-mode
def test_related_value_strict_mode_raises_after_reporting(monkeypatch):
    captured = []
    monkeypatch.setattr(
        unloaded_relations_module,
        "CONFIG",
        SimpleNamespace(CAPTURE_UNLOADED_RELATIONS=False, STRICT_RELATION_LOADS=True),
    )
    monkeypatch.setattr(
        unloaded_relations_module,
        "capture",
        lambda error, context=None, level="error": captured.append(
            (error, context, level)
        ),
    )

    entity = SimpleNamespace(
        entity_kind="category",
        kind="category",
        name="Contacts",
        id="category-1",
        hash="category-hash",
        urlsafe_key="category-key",
        db={"owner": SimpleNamespace(kind="form", id="form-1")},
    )
    prop = _TraceSingleRelation(entity=entity)

    with pytest.raises(UnloadedRelationError, match="category.owner"):
        prop.value

    assert len(captured) == 1
    error, context, level = captured[0]
    assert isinstance(error, UnloadedRelationError)
    assert level == "warning"
    assert context["property"]["id"] == "owner"
    assert context["keys"] == ["form:form-1"]


# @pair entities:load-tracing
def test_print_entity_load_trace_prints_once_per_request(monkeypatch, capsys):
    app = Flask(__name__)
    monkeypatch.setattr(
        entity_load_module, "CONFIG", SimpleNamespace(DEBUG_TRACING=True)
    )

    with app.test_request_context("/categories/demo", method="GET"):
        g.entity_loads = [
            {
                "operation": "load",
                "primary": ["user:Caleb Wright"],
                "secondary": [],
                "related": [],
                "first_batch_keys": 1,
                "related_batch_keys": 0,
                "first_batch_calls": 1,
                "related_batch_calls": 0,
                "db_reads": 1,
            },
        ]

        entity_load_module.print_entity_load_trace()
        entity_load_module.print_entity_load_trace()

    output = capsys.readouterr().out
    assert output.count("[entity-loads] GET /categories/demo") == 1


# @pair utility:html-stripping
def test_strip_tags():
    """Test html_tools.strip_tags removes HTML tags correctly."""
    assert html_tools.strip_tags("<p>Hello <b>World</b></p>") == "Hello World"
    assert html_tools.strip_tags("Plain text") == "Plain text"
    assert html_tools.strip_tags(123) == 123  # Non-string input returned as is

    assert html_tools.strip_tags("") == ""
    assert html_tools.strip_tags("   ") == ""
    assert html_tools.strip_tags("<p></p>") == ""
    assert html_tools.strip_tags("<p> </p>") == ""


# @pair utility:timing
def test_timed_config_disabled(monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "CONFIG", SimpleNamespace(DEBUG_TRACING=False))

    @diagnostics.timed
    def sample(value):
        return value + 1

    assert sample(2) == 3
    assert capsys.readouterr().out == ""


# @pair utility:timing
def test_timed_config_enabled(monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "CONFIG", SimpleNamespace(DEBUG_TRACING=True))

    @diagnostics.timed
    def sample(value):
        return value + 1

    assert sample(2) == 3

    output = capsys.readouterr().out
    assert "[timing]" in output
    assert "sample" in output
    assert "ms" in output


# @pair utility:timing
def test_timed_parameterized_preserves_metadata(capsys):
    @diagnostics.timed(enabled=True, label="custom-timer")
    def named_function():
        """Timer metadata should survive decoration."""
        return "done"

    assert named_function() == "done"
    assert named_function.__name__ == "named_function"
    assert named_function.__doc__ == "Timer metadata should survive decoration."

    output = capsys.readouterr().out
    assert "[timing] custom-timer:" in output


def _timed_profile_helper(value):
    return sum(i * i for i in range(value))


# @pair utility:timing
def test_timed_profiles_project_calls(capsys):
    @diagnostics.timed(enabled=True, profile=True, label="profiled", limit=20)
    def profiled():
        return _timed_profile_helper(5)

    assert profiled() == 30

    output = capsys.readouterr().out
    assert "[timing] profiled:" in output
    assert (
        "[timing] project calls by cumulative time "
        "(includes child/dependency calls) (limit=20)"
    ) in output
    assert "[timing] raw calls by cumulative time" not in output
    assert "[timing] cum_ms  self_ms  calls  function" in output
    assert "_timed_profile_helper" in output


# @pair utility:timing
def test_timed_profile_omits_raw_profile_table(capsys):
    @diagnostics.timed(
        enabled=True,
        profile=True,
        label="profiled-without-raw-table",
    )
    def profiled():
        return _timed_profile_helper(5)

    assert profiled() == 30

    output = capsys.readouterr().out
    assert "[timing] profiled-without-raw-table:" in output
    assert "[timing] project calls by cumulative time" in output
    assert "[timing] raw calls by cumulative time" not in output


# @pair utility:timing
def test_timed_project_filter_excludes_local_dependency_paths():
    project_file = diagnostics.PROJECT_ROOT / "lagniappe" / "web" / "auth.py"
    dependency_file = (
        diagnostics.PROJECT_ROOT
        / "venv"
        / "lib"
        / "python3.14"
        / "site-packages"
        / "google"
        / "api_core"
        / "retry.py"
    )

    assert (
        diagnostics._profile_location(str(project_file), 59, "wrapped", True)
        == "lagniappe/web/auth.py:59 wrapped"
    )
    assert (
        diagnostics._profile_location(str(dependency_file), 287, "retry", True) is None
    )
    assert "venv/lib" in diagnostics._profile_location(
        str(dependency_file), 287, "retry", False
    )


# @pair utility:timing
def test_timed_profile_rows_use_total_calls(monkeypatch):
    project_file = diagnostics.PROJECT_ROOT / "lagniappe" / "demo.py"
    stats = {
        (str(project_file), 7, "recursive"): (1, 2, 0.003, 0.010, {}),
    }

    monkeypatch.setattr(
        diagnostics.pstats,
        "Stats",
        lambda _profiler: SimpleNamespace(stats=stats),
    )

    rows = diagnostics._profile_rows(object(), limit=10, min_ms=0, project_only=True)

    assert rows == [
        {
            "cum_ms": 10.0,
            "self_ms": 3.0,
            "calls": "2",
            "location": "lagniappe/demo.py:7 recursive",
        }
    ]


# @pair utility:timing
def test_timed_prints_when_wrapped_function_raises(capsys):
    @diagnostics.timed(enabled=True, label="explode")
    def explode():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        explode()

    output = capsys.readouterr().out
    assert "[timing] explode:" in output


# @pair utility:timing
def test_timed_prints_request_label_without_entity_trace(monkeypatch, capsys):
    app = Flask(__name__)
    monkeypatch.setattr(diagnostics, "CONFIG", SimpleNamespace(DEBUG_TRACING=True))

    with app.test_request_context("/categories/demo?cursor=abc", method="GET"):
        g.entity_loads = [
            {
                "operation": "load",
                "primary": [],
                "secondary": ["models:Task Model"],
                "related": [],
                "first_batch_keys": 1,
                "related_batch_keys": 0,
                "first_batch_calls": 1,
                "related_batch_calls": 0,
                "db_reads": 1,
            },
        ]

        @diagnostics.timed(label="route-timer")
        def route():
            return "ok"

        assert route() == "ok"

    output = capsys.readouterr().out
    assert "[timing] GET /categories/demo?cursor=abc route-timer:" in output
    assert "[entity-loads]" not in output


# @pair utility:html-cleaning
def test_clean_html():
    """Test html_tools.clean_html removes code blocks and empty tags."""
    assert html_tools.clean_html(None) == ""
    assert html_tools.clean_html("") == ""
    assert html_tools.clean_html(123) == 123  # Non-string input returned as is

    # Removes markdown code blocks
    assert html_tools.clean_html("```html\n<p>test</p>\n```") == "<p>test</p>"
    assert html_tools.clean_html("```\n<p>test</p>\n```") == "<p>test</p>"

    # Removes empty tags
    assert (
        html_tools.clean_html("<p></p><div><span>  </span></div><p>Keep</p>")
        == "<p>Keep</p>"
    )

    # Keeps tags with content or certain elements
    assert (
        html_tools.clean_html("<p><img src='test.png'></p>")
        == '<p><img src="test.png"/></p>'
    )
    assert html_tools.clean_html("<hr>") == "<hr/>"

    # Removes whitespace between tags
    assert html_tools.clean_html("<p>A</p> \n  <p>B</p>") == "<p>A</p><p>B</p>"


# @pair utility:hashing
def test_short_hash_and_uuid():
    """Test hash and uuid utility functions."""
    h = identifiers.short_hash("test")
    assert len(h) == 12
    assert isinstance(h, str)

    u = identifiers.short_uuid()
    assert len(u) == 8
    assert isinstance(u, str)


# @pair utility:task-sorting
def test_sort_tasks():
    """Test ordering.sort_tasks sorts by due_date then modified."""
    from unittest.mock import MagicMock
    from datetime import datetime

    d1 = datetime(2025, 1, 1)
    d2 = datetime(2025, 1, 2)
    m1 = datetime(2025, 1, 10)
    m2 = datetime(2025, 1, 11)

    t1 = MagicMock(due_date=d1, modified=m1)
    t2 = MagicMock(due_date=d2, modified=m1)
    t3 = MagicMock(due_date=None, modified=m1)
    t4 = MagicMock(due_date=None, modified=m2)

    # Expected order: t1 (earliest due), t2 (later due), t4 (no due, latest modified), t3 (no due, older modified)
    tasks = [t3, t1, t4, t2]
    sorted_tasks = ordering.sort_tasks(tasks)
    assert sorted_tasks == [t1, t2, t4, t3]


# @matrix database : filter validation
def test_database_filter_requires_rejects_invalid_hashes_type():
    assert Restriction.is_denied([])
    assert not Restriction.is_denied(Restriction.UNRESTRICTED)
    assert Filter().requires(Restriction.UNRESTRICTED).build() is None

    with pytest.raises(
        TypeError,
        match="hashes must be Restriction.UNRESTRICTED or a list",
    ):
        Filter().requires("models")

    with pytest.raises(
        TypeError,
        match="hashes must be Restriction.UNRESTRICTED or a list",
    ):
        Filter().requires(False)
    with pytest.raises(
        TypeError,
        match="hashes must be Restriction.UNRESTRICTED or a list",
    ):
        Filter().requires(None)


# @matrix ai error-reporting files : expected-provider-failure pdf-page-limit privacy
def test_sentry_filter_drops_only_expected_ai_document_page_limit():
    from lagniappe.core.exceptions.request import filter_sentry_event

    expected = {
        "exception": {
            "values": [
                {
                    "type": "ClientError",
                    "value": (
                        "The document contains 1203 pages which exceeds the "
                        "supported page limit of 1000."
                    ),
                }
            ]
        }
    }
    unrelated = {
        "exception": {
            "values": [
                {
                    "type": "ClientError",
                    "value": "A different provider request was invalid.",
                }
            ]
        },
        "user": {"email": "private@example.test"},
    }

    assert filter_sentry_event(expected, {}) is None
    filtered = filter_sentry_event(unrelated, {})
    assert filtered is not None
    assert "user" not in filtered
