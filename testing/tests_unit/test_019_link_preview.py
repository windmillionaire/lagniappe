from types import SimpleNamespace

from google.cloud.datastore import Key
import pytest

from lagniappe.core.entities import Entities
from lagniappe.core.definitions import Action
from lagniappe.core.tools.http import HTML_METADATA_POLICY, OutboundResult, OutboundStatus
from lagniappe.core.tools.links import preview as link_preview
from lagniappe.core.tools.database import get as database_get
from testing.utility.test_entities import TestUser as UtilityTestUser


class PreviewEntity(SimpleNamespace):
    def allowed(self, action, user=None):
        assert action is Action.VIEW
        assert user is not None
        return self.is_allowed


def _entity(kind="project", allowed=True):
    return PreviewEntity(
        kind=kind,
        name="Preview Target",
        description="A target description",
        is_allowed=allowed,
    )


def _project(allowed=True):
    project = _entity(kind="project", allowed=allowed)
    project.model_tasks = [SimpleNamespace(urlsafe_key="model-key", name="Inspections")]
    return project


# @matrix editor link-preview : internal metadata permissions
def test_internal_preview_returns_allowed_entity_metadata(monkeypatch):
    entity = _entity()
    monkeypatch.setattr(
        link_preview.Entities,
        "fetch_one",
        lambda key, request: entity if key == "project-key" else None,
    )

    preview = link_preview.preview_for_url(
        "/projects/project-key?from=editor#notes",
        user=object(),
        base_url="https://app.test/",
    )

    assert preview == {
        "title": "Preview Target",
        "description": "A target description",
        "url": "/projects/project-key?from=editor#notes",
        "display_url": "/projects/project-key?from=editor#notes",
        "kind": "project",
        "internal": True,
    }


# @pair link-preview:nested-relations
@pytest.mark.parametrize("kind", ["task", "file"])
def test_task_preview_loads_page_form_before_permission_check(monkeypatch, kind):
    def stored(entity_type, name):
        entity = entity_type(Key(entity_type.entity_kind, name, project="preview-unit-test"))
        entity._db = {"name": name, "hash": name, "kind": entity.entity_kind,
                     "type": entity.entity_kind, "requires": ["pages"]}
        return entity

    form = stored(Entities.FORM, "Members form")
    form.db["restricted_to"] = ["members"]
    page = stored(Entities.PAGE, "Preview page")
    page.form = form
    task = stored(Entities.TASK, "Preview Target")
    task.page = page
    entity = task
    if kind == "file":
        entity = stored(Entities.FILE, "Preview Target")
        entity.task = task
    viewer = UtilityTestUser(owner=False, permissions={"pages": "EDIT"})
    viewer.db["belongs_to"] = ["members"]
    page.properties.form.unset()
    page.properties.form._attached = {}
    original_fetch = link_preview.Entities.fetch_one
    def fetch(key, *, request):
        return original_fetch(entity, request=request)
    monkeypatch.setattr(link_preview.Entities, "fetch_one", fetch)
    monkeypatch.setattr(database_get, "entities", lambda keys: [form for key in keys if key == form.key])
    preview = link_preview.preview_for_url(f"/{kind}s/item", user=viewer, base_url="https://app.test/")
    assert preview["title"] == "Preview Target"
    assert page.form is form
    viewer.db["belongs_to"] = []
    denied = link_preview.preview_for_url(f"/{kind}s/item", user=viewer, base_url="https://app.test/")
    assert denied["title"] == "Access Restricted"


# @matrix editor link-preview : internal metadata permissions
def test_internal_status_preview_uses_project_permission(monkeypatch):
    project = _project()
    monkeypatch.setattr(
        link_preview.CONFIG,
        "CUSTOM_DOMAIN",
        "lagniappe.site",
        raising=False,
    )
    monkeypatch.setattr(
        link_preview.Entities,
        "fetch_one",
        lambda key, request: project if key == "project-key" else None,
    )

    preview = link_preview.preview_for_url(
        "https://lagniappe.site/projects/project-key/status/model-key?completed=true",
        user=object(),
        base_url="https://app.test/",
    )

    assert preview == {
        "title": "Completed Inspections",
        "description": "Preview Target task status",
        "url": "/projects/project-key/status/model-key?completed=true",
        "display_url": "/projects/project-key/status/model-key?completed=true",
        "kind": "project",
        "internal": True,
    }
    project.is_allowed = False
    denied = link_preview.preview_for_url(
        "https://lagniappe.site/projects/project-key/status/model-key?completed=true",
        user=object(),
        base_url="https://app.test/",
    )
    assert denied["title"] == "Access Restricted"
    assert "Inspections" not in str(denied)
    assert "Preview Target" not in str(denied)


# @matrix editor link-preview : internal permissions
def test_internal_preview_hides_missing_or_forbidden_entities(monkeypatch):
    monkeypatch.setattr(link_preview.Entities, "fetch_one", lambda key, request: None)

    missing = link_preview.preview_for_url(
        "/projects/missing-key",
        user=object(),
        base_url="https://app.test/",
    )
    assert missing["title"] == "Access Restricted"
    assert missing["description"] == "You do not have access to preview this link."

    forbidden = _entity(allowed=False)
    monkeypatch.setattr(
        link_preview.Entities, "fetch_one", lambda key, request: forbidden
    )

    denied = link_preview.preview_for_url(
        "/projects/forbidden-key",
        user=object(),
        base_url="https://app.test/",
    )
    assert denied["title"] == "Access Restricted"
    assert denied["description"] == "You do not have access to preview this link."


# @matrix editor link-preview : external metadata
def test_external_preview_maps_metadata_and_falls_back(monkeypatch):
    def fetch(url, policy, *, headers):
        assert url == "https://example.com/articles/one"
        assert policy is HTML_METADATA_POLICY
        return OutboundResult(
            OutboundStatus.OK,
            body=b'<title>Example Title</title><meta name="description" content="Example summary">',
            final_url=url,
        )

    monkeypatch.setattr(link_preview, "fetch_user_content", fetch)

    preview = link_preview.preview_for_url(
        "https://example.com/articles/one#section",
        user=object(),
        base_url="https://app.test/",
    )

    assert preview["title"] == "Example Title"
    assert preview["description"] == "Example summary"
    assert preview["display_url"] == "example.com/articles/one"
    assert preview["kind"] == "external"
    assert preview["internal"] is False
    assert preview["url"] == "https://example.com/articles/one"

    for response in (
        OutboundResult(OutboundStatus.OK, body=b"<html></html>"),
        OutboundResult(OutboundStatus.TIMEOUT),
    ):
        monkeypatch.setattr(link_preview, "fetch_user_content", lambda *a, **kw: response)
        fallback = link_preview.preview_for_url(
            "https://www.example.org/",
            user=object(),
            base_url="https://app.test/",
        )

        assert fallback["title"] == "example.org"
        assert fallback["description"] is None


# @matrix editor link-preview : external url-safety
def test_external_preview_rejects_unsafe_urls(monkeypatch):
    for url in [
        "javascript:alert(1)",
        "https://user:password@example.com/",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
    ]:
        with pytest.raises(link_preview.PreviewError):
            link_preview.preview_for_url(
                url,
                user=object(),
                base_url="https://app.test/",
            )

    monkeypatch.setattr(
        link_preview,
        "fetch_user_content",
        lambda *args, **kwargs: OutboundResult(
            OutboundStatus.REJECTED,
            final_url="http://127.0.0.1/",
        ),
    )

    with pytest.raises(link_preview.PreviewError):
        link_preview.preview_for_url(
            "https://example.com/",
            user=object(),
            base_url="https://app.test/",
        )

    monkeypatch.setattr(
        link_preview,
        "fetch_user_content",
        lambda *args, **kwargs: OutboundResult(
            OutboundStatus.OK,
            body=b"<html><title>Sign in</title></html>",
            media_type="text/html",
            http_status=200,
            size=36,
            redirect_count=1,
            final_url="https://example.com/users/login?next=/projects/key",
        ),
    )

    restricted = link_preview.preview_for_url(
        "https://example.com/elsewhere",
        user=object(),
        base_url="https://app.test/",
    )
    assert restricted["title"] == "Access Restricted"
