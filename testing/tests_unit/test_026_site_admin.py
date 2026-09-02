"""Unit contracts for runtime-safe site administration services."""

from datetime import datetime, timezone
from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe.core.definitions import FetchDepth, FetchReason
from lagniappe.core.definitions.manual import MANUAL_SECTIONS
from lagniappe.core.entities.group import UserGroup
from lagniappe.core.entities.page import Page
from lagniappe.core.entities.user import User
from lagniappe.core.tools.site import admin as site_admin
from lagniappe.core.tools.site import cache_rebuild
from lagniappe.core.tools.site import recovery
from lagniappe.core.tools.site import public_pages


pytestmark = pytest.mark.unit


def _public_page(document, *, assets=None, settings=None, **values):
    assets = assets or {}
    page = SimpleNamespace(
        properties=SimpleNamespace(document=SimpleNamespace(html=document)),
        assets={name: {"type": "image"} for name in assets},
        public_settings=settings or {},
        name=values.pop("name", "Public Page"),
        active=values.pop("active", True),
        is_public=values.pop("is_public", True),
        entity_kind=values.pop("entity_kind", "page"),
        db=values.pop("db", {"public_id": "public-id"}),
        categories=values.pop("categories", []),
        **values,
    )
    page.get_asset = lambda name: assets.get(name)
    return page


# @matrix public-pages : config-fallback live-settings
def test_public_page_runtime_settings_prefer_live_datastore_and_fail_closed(
    monkeypatch,
):
    config = SimpleNamespace(PUBLIC_PAGE_INDEXING=False)
    monkeypatch.setattr(
        public_pages.site_database,
        "public_pages",
        lambda: {"PUBLIC_PAGE_INDEXING": True, "version": 3},
    )
    assert public_pages.runtime_settings(config=config)["PUBLIC_PAGE_INDEXING"] is True

    monkeypatch.setattr(
        public_pages.site_database,
        "public_pages",
        lambda: (_ for _ in ()).throw(RuntimeError("Datastore unavailable")),
    )
    monkeypatch.setattr(public_pages, "capture", lambda *_args, **_kwargs: None)
    assert public_pages.runtime_settings(config=config)["PUBLIC_PAGE_INDEXING"] is False


# @matrix public-pages : document-image privacy preview
def test_public_document_images_only_include_embedded_page_assets():
    first = SimpleNamespace(
        url="/assets/page/image_first.png",
        content_type="image/png",
        fingerprint="first",
        extension="png",
    )
    unused = SimpleNamespace(
        url="/assets/page/image_unused.jpg",
        content_type="image/jpeg",
        fingerprint="unused",
        extension="jpg",
    )
    page = _public_page(
        '<p><img src="/assets/page/image_first.png" alt="First"></p>'
        '<img src="https://example.com/external.jpg">',
        assets={"image_first": first, "image_unused": unused},
    )

    candidates = public_pages.document_images(page)

    assert [(image.name, image.alt) for image in candidates] == [
        ("image_first", "First")
    ]


# @matrix public-pages : document-image public-rendering
def test_public_document_rewrites_only_embedded_page_images():
    asset = SimpleNamespace(
        url="/assets/page/image_first.png",
        content_type="image/png",
        fingerprint="first",
        extension="png",
    )
    page = _public_page(
        '<p><img src="/assets/page/image_first.png" alt="First"></p>'
        '<img src="https://example.com/external.jpg">',
        assets={"image_first": asset},
    )

    html, candidates = public_pages.public_document_html(
        page,
        lambda image: f"/pages/public/public-id/images/{image.name}.png",
    )

    assert "/pages/public/public-id/images/image_first.png" in html
    assert "https://example.com/external.jpg" not in html
    assert [image.name for image in candidates] == ["image_first"]

    forged, _ = public_pages.public_document_html(
        page,
        lambda image: (
            f"https://attacker.test/pages/public/public-id/images/{image.name}.png"
        ),
        public_origin="https://site.test/pages/public/public-id",
    )

    assert "<img" not in forged


# @matrix public-pages : metadata privacy social-preview
def test_public_metadata_uses_safe_fallbacks_and_selected_document_image(monkeypatch):
    asset = SimpleNamespace(
        url="/assets/page/image_first.png",
        content_type="image/png",
        fingerprint="first",
        extension="png",
    )
    page = _public_page(
        '<p>A document-only description.</p><img src="/assets/page/image_first.png" alt="Diagram">',
        assets={"image_first": asset},
        settings={"preview_image_asset": "image_first"},
        name="Internal Name",
        description="Must not leak",
    )

    result = public_pages.metadata(
        page,
        canonical_url="https://site.test/pages/public/id",
        site_image_url="https://site.test/images/logo.png",
        public_image_url=lambda image: (
            f"https://site.test/pages/public/public-id/images/{image.name}.png"
        ),
        indexing=True,
    )

    assert result["title"] == "Internal Name"
    assert result["description"] == "A document-only description."
    assert "Must not leak" not in result.values()
    assert result["image"] == (
        "https://site.test/pages/public/public-id/images/image_first.png"
    )
    assert result["image_alt"] == "Diagram"
    assert result["robots"] == "index, follow"


# @matrix manual : canonical-url metadata search-discovery
# @matrix manual sitemap : canonical-url public-url
def test_public_manual_metadata_and_urls_are_canonical(monkeypatch):
    monkeypatch.setattr(
        public_pages,
        "absolute_url",
        lambda path: f"https://site.test{path}",
    )

    overview = public_pages.manual_metadata(
        MANUAL_SECTIONS[0],
        indexing=True,
        app_name="Demo",
    )
    forms = public_pages.manual_metadata(
        MANUAL_SECTIONS[2],
        indexing=False,
        app_name="Demo",
    )

    assert overview == {
        "path": "/manual/",
        "canonical_url": "https://site.test/manual/",
        "title": "Overview — Demo Manual",
        "description": "Read the Overview section of the Demo manual.",
        "robots": "index, follow",
    }
    assert forms == {
        "path": "/manual/forms",
        "canonical_url": "https://site.test/manual/forms",
        "title": "Forms — Demo Manual",
        "description": "Read the Forms section of the Demo manual.",
        "robots": "noindex, follow",
    }

    urls = public_pages.discoverable_manual_urls()
    assert len(urls) == len(MANUAL_SECTIONS)
    assert urls[0] == "https://site.test/manual/"
    assert "https://site.test/manual/overview" not in urls
    assert "https://site.test/manual/security" in urls
    assert not any("/manual/section/" in url for url in urls)


# @matrix public-pages robots : disabled enabled public-assets
# @matrix manual robots : disabled enabled fragment
def test_robots_text_allows_public_surface_and_advertises_enabled_sitemap():
    disabled = public_pages.robots_text(
        False,
        sitemap_url="https://site.test/sitemap.xml",
        public_manual=True,
    )
    enabled = public_pages.robots_text(
        True,
        sitemap_url="https://site.test/sitemap.xml",
        public_manual=True,
    )
    private_manual = public_pages.robots_text(
        True,
        sitemap_url="https://site.test/sitemap.xml",
        public_manual=False,
    )

    assert "Disallow: /" in disabled
    assert "Allow: /public/" in disabled
    assert "Allow: /pages/public/" in disabled
    assert "Allow: /manual/" in disabled
    assert "Disallow: /manual/section/" in disabled
    assert "Sitemap:" not in disabled
    assert "Sitemap: https://site.test/sitemap.xml" in enabled
    assert "Allow: /manual/" not in private_manual


# @matrix public-pages sitemap : dedupe limit sorted xml
def test_sitemap_xml_is_sorted_deduped_and_fails_closed_at_limit(monkeypatch):
    xml = public_pages.sitemap_xml(
        ["https://site.test/z", "https://site.test/a", "https://site.test/z"]
    )
    assert xml.index("https://site.test/a") < xml.index("https://site.test/z")
    assert xml.count("https://site.test/z") == 1

    monkeypatch.setattr(public_pages, "SITEMAP_URL_LIMIT", 1)
    with pytest.raises(public_pages.SitemapLimitError):
        public_pages.sitemap_xml(["https://site.test/a", "https://site.test/b"])


# @matrix public-pages public-directory : active category description opt-out public-url sorting
def test_public_directory_snapshot_groups_safe_metadata_and_avoids_documents(
    monkeypatch,
):
    alpha = SimpleNamespace(urlsafe_key="alpha-key", name="Alpha")
    fetch_requests = []
    pages = [
        _public_page(
            "document must not be read",
            name="Zulu",
            settings={
                "title": "A public title",
                "description": "An explicit public description.",
                "directory_category": "alpha-key",
            },
            categories=[alpha],
            db={"public_id": "included"},
        ),
        _public_page(
            "private document text",
            name="Fallback Page",
            settings={"directory_category": "detached-key"},
            categories=[alpha],
            db={"public_id": "fallback"},
        ),
        _public_page("", active=False, db={"public_id": "inactive"}),
        _public_page(
            "",
            settings={"allow_indexing": False},
            db={"public_id": "opted-out"},
        ),
        _public_page("", entity_kind="project", db={"public_id": "wrong-kind"}),
    ]
    monkeypatch.setattr(
        public_pages.database_get,
        "discoverable_page_rows",
        lambda: ["candidate"],
    )
    monkeypatch.setattr(
        public_pages.Entities,
        "fetch",
        lambda *_rows, request: fetch_requests.append(request) or pages,
    )
    monkeypatch.setattr(
        public_pages,
        "runtime_settings",
        lambda: {"PUBLIC_PAGE_INDEXING": True},
    )

    snapshot = public_pages.public_directory_snapshot()

    assert snapshot == {
        "schema": 1,
        "site_indexing": True,
        "groups": [
            {
                "id": "category:alpha-key",
                "name": "Alpha",
                "pages": [
                    {
                        "path": "/pages/public/included",
                        "title": "A public title",
                        "description": "An explicit public description.",
                    }
                ],
            },
            {
                "id": "public-pages",
                "name": "Public Pages",
                "pages": [
                    {
                        "path": "/pages/public/fallback",
                        "title": "Fallback Page",
                        "description": None,
                    }
                ],
            },
        ],
    }
    assert "document" not in str(snapshot).lower()
    assert [request.depth for request in fetch_requests] == [FetchDepth.DIRECT]


# @matrix public-pages public-directory : disabled query-avoidance
def test_public_directory_snapshot_skips_page_query_when_discovery_is_off(
    monkeypatch,
):
    monkeypatch.setattr(
        public_pages,
        "runtime_settings",
        lambda: {"PUBLIC_PAGE_INDEXING": False},
    )
    monkeypatch.setattr(
        public_pages.database_get,
        "discoverable_page_rows",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected page query")),
    )

    assert public_pages.public_directory_snapshot() == {
        "schema": 1,
        "site_indexing": False,
        "groups": [],
    }


# @matrix public-pages sitemap public-directory : shared-catalog public-url
def test_discoverable_page_urls_use_cached_directory_snapshot(monkeypatch):
    monkeypatch.setattr(
        public_pages,
        "absolute_url",
        lambda path: f"https://site.test{path}",
    )
    snapshot = {
        "groups": [
            {
                "pages": [
                    {
                        "path": "/pages/public/included",
                        "title": "Included",
                        "description": None,
                    }
                ]
            }
        ]
    }
    assert public_pages.discoverable_page_urls(snapshot) == [
        "https://site.test/pages/public/included"
    ]


# @matrix manual public-directory : authored-order public-url
def test_manual_directory_group_preserves_authored_section_order():
    group = public_pages.manual_directory_group()

    assert group["name"] == "Manual"
    assert [page["title"] for page in group["pages"]] == [
        section["name"] for section in MANUAL_SECTIONS
    ]
    assert group["pages"][0]["path"] == "/manual/"
    assert all(page["description"] is None for page in group["pages"])


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
    normalization = []
    monkeypatch.setattr(
        site_admin,
        "normalize_deployment_settings",
        lambda values, **kwargs: normalization.append(kwargs) or dict(values),
    )

    settings = site_admin.load_deployment_settings(config=config)

    assert settings["DEPLOY_WORKER_COUNT"] == "7"
    assert "version" not in settings
    assert normalization == [{"enforce_worker_limit": False}]


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
        cache_rebuild.database_migrations,
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
        cache_rebuild.cache,
        "delete_cache",
        lambda: (_ for _ in ()).throw(AssertionError("blocked rebuild deleted cache")),
    )

    result = cache_rebuild.rebuild_application_cache()

    assert result.rebuilt is False
    assert result.migration_status is report


# @matrix cache : batching current migration-gate
def test_cache_rebuild_rehydrates_entities_in_bounded_chunks(monkeypatch):
    report = {"status": "current", "cache_refresh_allowed": True}
    deleted = []
    fetches = []
    updates = []
    monkeypatch.setattr(
        cache_rebuild.database_migrations,
        "get_migration_status",
        lambda: report,
    )
    monkeypatch.setattr(
        cache_rebuild.cache, "delete_cache", lambda: deleted.append(True)
    )
    monkeypatch.setattr(
        cache_rebuild.database_get, "all_models", lambda: iter(["one", "two"])
    )
    monkeypatch.setattr(
        cache_rebuild.database_get, "all_instances", lambda: iter(["three"])
    )
    monkeypatch.setattr(cache_rebuild.database_get, "all_files", lambda: iter(()))
    monkeypatch.setattr(cache_rebuild.database_get, "all_users", lambda: iter(()))
    monkeypatch.setattr(
        cache_rebuild.Entities,
        "fetch",
        lambda *keys, request: (
            fetches.append((list(keys), request)) or [f"loaded:{key}" for key in keys]
        ),
    )
    monkeypatch.setattr(
        cache_rebuild.cache,
        "update",
        lambda *entities, update: updates.append((list(entities), update)),
    )

    result = cache_rebuild.rebuild_application_cache(chunk_size=2)

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
        cache_rebuild.database_migrations,
        "get_migration_status",
        lambda: {"status": "current", "cache_refresh_allowed": True},
    )
    monkeypatch.setattr(cache_rebuild.cache, "delete_cache", lambda: None)
    monkeypatch.setattr(cache_rebuild.database_get, "all_models", lambda: iter([group]))
    monkeypatch.setattr(
        cache_rebuild.database_get, "all_instances", lambda: iter([page])
    )
    monkeypatch.setattr(cache_rebuild.database_get, "all_files", lambda: iter(()))
    monkeypatch.setattr(cache_rebuild.database_get, "all_users", lambda: iter([user]))
    monkeypatch.setattr(
        cache_rebuild.database_get,
        "entities",
        lambda keys: [stored[key] for key in keys if key in stored],
    )

    def materialize(*entities, update):
        assert update is False
        for entity in entities:
            projections[entity.key] = dict(entity.to_cache)

    monkeypatch.setattr(cache_rebuild.cache, "update", materialize)

    result = cache_rebuild.rebuild_application_cache(chunk_size=1)

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
    monkeypatch.setattr(
        recovery.site_database,
        "public_pages",
        lambda: {"PUBLIC_PAGE_INDEXING": True},
    )
    monkeypatch.setattr(recovery, "read_recovery_redis_ca", lambda _settings: "ca")
    monkeypatch.setattr(
        recovery,
        "build_recovery_snapshot",
        lambda settings, **kwargs: {
            **settings,
            **kwargs["deployment_settings"],
            **kwargs["ai_settings"],
            **kwargs["public_page_settings"],
        },
    )

    snapshot = recovery.load_recovery_snapshot(persisted)

    assert snapshot["SECRET_KEY"] == "application-secret"
    assert snapshot["DEPLOY_MAX_INSTANCES"] == "4"
    assert snapshot["AI_MODEL"] == "live-model"
    assert snapshot["PUBLIC_PAGE_INDEXING"] is True


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
