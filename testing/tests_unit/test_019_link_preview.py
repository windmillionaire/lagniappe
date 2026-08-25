from types import SimpleNamespace

import pytest

from lagniappe.core.tools.http import OutboundResult, OutboundStatus
from lagniappe.core.tools.links import preview as link_preview


class PreviewEntity(SimpleNamespace):
    def allowed(self, action, user=None):
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


# @features editor link-preview
# @dimensions internal metadata permissions
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


# @features editor link-preview
# @dimensions internal metadata permissions
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


# @features editor link-preview
# @dimensions internal permissions
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


# @features editor link-preview
# @dimensions external metadata
def test_external_preview_maps_metadata_and_falls_back(monkeypatch):
    monkeypatch.setattr(
        link_preview,
        "_external_metadata",
        lambda url: {"name": "Example Title", "description": "Example summary"},
    )

    preview = link_preview.preview_for_url(
        "https://example.com/articles/one",
        user=object(),
        base_url="https://app.test/",
    )

    assert preview["title"] == "Example Title"
    assert preview["description"] == "Example summary"
    assert preview["display_url"] == "example.com/articles/one"
    assert preview["kind"] == "external"
    assert preview["internal"] is False

    monkeypatch.setattr(link_preview, "_external_metadata", lambda url: {})
    fallback = link_preview.preview_for_url(
        "https://www.example.org/",
        user=object(),
        base_url="https://app.test/",
    )

    assert fallback["title"] == "example.org"
    assert fallback["description"] is None


# @features editor link-preview
# @dimensions external url-safety
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
