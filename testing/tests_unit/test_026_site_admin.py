"""Unit contracts for runtime-safe site administration services."""

from datetime import datetime, timezone
from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe.core.definitions import FetchDepth, FetchReason
from lagniappe.core.entities.group import UserGroup
from lagniappe.core.entities.page import Page
from lagniappe.core.entities.user import User
from lagniappe.core.tools.site import admin as site_admin
from lagniappe.core.tools.site import recovery


pytestmark = pytest.mark.unit


# @matrix admin : config deployment-settings metadata
def test_deployment_settings_merge_live_values_over_runtime_defaults(monkeypatch):
    config = SimpleNamespace(
        **{key: value for key, value in site_admin.DEFAULT_DEPLOYMENT_SETTINGS.items()}
    )
    config.DEPLOY_WORKER_COUNT = "5"
    monkeypatch.setattr(
        site_admin.site_database,
        "deployment",
        lambda: {"DEPLOY_WORKER_COUNT": "7", "version": 2},
    )
    monkeypatch.setattr(site_admin, "normalize_deployment_settings", dict)

    settings = site_admin.load_deployment_settings(config=config)

    assert settings["DEPLOY_WORKER_COUNT"] == "7"
    assert "version" not in settings


# @matrix admin : ai-settings config metadata
def test_ai_settings_payload_normalizes_runtime_settings_against_discovery(monkeypatch):
    config = SimpleNamespace(
        GOOGLE_CLOUD_PROJECT="demo-project",
        google_credentials="credentials",
    )
    settings = {"AI_LOCATION": "global", "AI_MODEL": "primary"}
    options = {"text": [{"id": "primary"}], "image": []}
    discovered = []
    monkeypatch.setattr(
        site_admin,
        "discover_model_options",
        lambda **kwargs: discovered.append(kwargs) or options,
    )
    monkeypatch.setattr(
        site_admin,
        "normalize_ai_settings",
        lambda values, **_kwargs: dict(values),
    )

    normalized, returned_options = site_admin.load_ai_settings_payload(
        settings,
        config=config,
    )

    assert normalized == settings
    assert returned_options is options
    assert discovered[0]["current_settings"] is settings


# @matrix admin : audit site-update
def test_site_updates_return_the_migration_report(monkeypatch):
    report = {"status": "current", "counts": {"complete": 2}}
    monkeypatch.setattr(
        site_admin.database_migrations,
        "run_data_migrations",
        lambda: report,
    )

    assert site_admin.run_site_updates() is report


# @matrix cache : migration-gate pending
def test_cache_rebuild_is_blocked_until_migrations_are_current(monkeypatch):
    report = {"status": "pending", "cache_refresh_allowed": False}
    monkeypatch.setattr(
        site_admin.database_migrations,
        "get_migration_status",
        lambda: report,
    )
    monkeypatch.setattr(
        site_admin.cache,
        "delete_cache",
        lambda: (_ for _ in ()).throw(AssertionError("blocked rebuild deleted cache")),
    )

    result = site_admin.rebuild_application_cache()

    assert result.rebuilt is False
    assert result.migration_status is report


# @matrix cache : batching current migration-gate
def test_cache_rebuild_rehydrates_entities_in_bounded_chunks(monkeypatch):
    report = {"status": "current", "cache_refresh_allowed": True}
    deleted = []
    fetches = []
    updates = []
    monkeypatch.setattr(
        site_admin.database_migrations,
        "get_migration_status",
        lambda: report,
    )
    monkeypatch.setattr(site_admin.cache, "delete_cache", lambda: deleted.append(True))
    monkeypatch.setattr(
        site_admin.database.get, "all_models", lambda: iter(["one", "two"])
    )
    monkeypatch.setattr(
        site_admin.database.get, "all_instances", lambda: iter(["three"])
    )
    monkeypatch.setattr(site_admin.database.get, "all_files", lambda: iter(()))
    monkeypatch.setattr(site_admin.database.get, "all_users", lambda: iter(()))
    monkeypatch.setattr(
        site_admin.Entities,
        "fetch",
        lambda *keys, request: (
            fetches.append((list(keys), request)) or [f"loaded:{key}" for key in keys]
        ),
    )
    monkeypatch.setattr(
        site_admin.cache,
        "update",
        lambda *entities, update: updates.append((list(entities), update)),
    )

    result = site_admin.rebuild_application_cache(chunk_size=2)

    assert result.rebuilt is True
    assert deleted == [True]
    assert [keys for keys, _request in fetches] == [["one", "two"], ["three"]]
    assert all(request.depth is FetchDepth.NESTED for _keys, request in fetches)
    assert all(
        request.reason is FetchReason.CACHE_REBUILD_MATERIALIZATION
        for _keys, request in fetches
    )
    assert updates == [(["loaded:one", "loaded:two"], False), (["loaded:three"], False)]


def _stored_entity(entity_class, key, **values):
    now = datetime.now(timezone.utc)
    entity = entity_class(testing=True)
    entity._key = key
    entity._db = {
        "active": True,
        "created": now,
        "hash": values.pop("hash"),
        "kind": entity.entity_kind,
        "modified": now,
        "name": values.pop("name"),
        "requires": values.pop("requires", [entity.entity_kind]),
        "type": entity.entity_kind,
        **values,
    }
    return entity


# @matrix cache : batching current nested-relations
def test_cache_rebuild_materializes_nested_relations_across_batch_boundaries(
    monkeypatch,
):
    project = "cache-rebuild-unit-test"
    group_key = Key("group", "grouped-viewers", project=project)
    user_key = Key("user", "grouped-user", project=project)
    page_key = Key("page", "grouped-user-page", project=project)
    group = _stored_entity(
        UserGroup,
        group_key,
        name="Grouped Viewers",
        hash="grouped-viewers",
        permissions="{}",
    )
    user = _stored_entity(
        User,
        user_key,
        name="Grouped User",
        hash="grouped-user",
        groups=[group_key],
        page=page_key,
        permissions="{}",
    )
    page = _stored_entity(
        Page,
        page_key,
        name="Grouped User Page",
        hash="grouped-user-page",
        user=user_key,
    )
    stored = {entity.key: entity for entity in (group, user, page)}
    projections = {}

    monkeypatch.setattr(
        site_admin.database_migrations,
        "get_migration_status",
        lambda: {"status": "current", "cache_refresh_allowed": True},
    )
    monkeypatch.setattr(site_admin.cache, "delete_cache", lambda: None)
    monkeypatch.setattr(site_admin.database.get, "all_models", lambda: iter([group]))
    monkeypatch.setattr(site_admin.database.get, "all_instances", lambda: iter([page]))
    monkeypatch.setattr(site_admin.database.get, "all_files", lambda: iter(()))
    monkeypatch.setattr(site_admin.database.get, "all_users", lambda: iter([user]))
    monkeypatch.setattr(
        site_admin.database.get,
        "entities",
        lambda keys: [stored[key] for key in keys if key in stored],
    )

    def materialize(*entities, update):
        assert update is False
        for entity in entities:
            projections[entity.key] = dict(entity.to_cache)

    monkeypatch.setattr(site_admin.cache, "update", materialize)

    result = site_admin.rebuild_application_cache(chunk_size=1)

    assert result.rebuilt is True
    assert page.user is user
    assert user.groups == [group]
    assert projections[page_key]["requires"] == "users,grouped-viewers"


# @matrix admin : live-settings recovery-export
def test_recovery_snapshot_merges_live_settings(monkeypatch):
    persisted = {"SECRET_KEY": "application-secret"}
    monkeypatch.setattr(
        recovery.site_database,
        "deployment",
        lambda: {"DEPLOY_MAX_INSTANCES": "4"},
    )
    monkeypatch.setattr(
        recovery.site_database,
        "ai",
        lambda: {"AI_MODEL": "live-model"},
    )
    monkeypatch.setattr(recovery, "read_recovery_redis_ca", lambda _settings: "ca")
    monkeypatch.setattr(
        recovery,
        "build_recovery_snapshot",
        lambda settings, **kwargs: {
            **settings,
            **kwargs["deployment_settings"],
            **kwargs["ai_settings"],
        },
    )

    snapshot = recovery.load_recovery_snapshot(persisted)

    assert snapshot["SECRET_KEY"] == "application-secret"
    assert snapshot["DEPLOY_MAX_INSTANCES"] == "4"
    assert snapshot["AI_MODEL"] == "live-model"


# @matrix admin : failure-isolation recovery-export
def test_recovery_snapshot_failures_use_safe_public_messages(monkeypatch):
    monkeypatch.setattr(
        recovery.site_database,
        "deployment",
        lambda: (_ for _ in ()).throw(ConnectionError("provider unavailable")),
    )

    with pytest.raises(recovery.RecoverySnapshotUnavailable) as error:
        recovery.load_recovery_snapshot({"SECRET_KEY": "application-secret"})

    assert "No settings were downloaded" in error.value.public_message
    assert "application-secret" not in error.value.public_message
