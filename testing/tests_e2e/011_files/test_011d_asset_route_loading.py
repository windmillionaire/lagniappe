"""Focused route-loading contracts for asset responses."""

from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import FetchDepth
from lagniappe.web.routes.assets import editor, main


pytestmark = pytest.mark.e2e


# @features html-field
# @dimensions decorator-entity direct-expand
def test_html_field_expands_permission_entity_directly(monkeypatch):
    provided_entity = SimpleNamespace(
        form=SimpleNamespace(
            get_html_field=lambda field_id: f"markup for {field_id}",
        )
    )
    fetches = []

    def fetch_one(entity, *, request):
        fetches.append((entity, request))
        return entity

    monkeypatch.setattr(
        editor.responses,
        "document_html",
        lambda markup: {"markup": markup},
    )
    monkeypatch.setattr(editor.Entities, "fetch_one", fetch_one)

    response = editor.html_field.__wrapped__(
        "stored-key",
        "html-field",
        entity=provided_entity,
    )

    assert response == {"markup": "markup for html-field"}
    assert fetches[0][0] is provided_entity
    assert fetches[0][1].depth is FetchDepth.DIRECT
    assert fetches[0][1].reason is None
    with pytest.raises(KeyError, match="entity"):
        editor.html_field.__wrapped__("stored-key", "html-field")


# @features file
# @dimensions decorator-entity direct-expand
def test_get_image_expands_permission_entity_directly(monkeypatch):
    provided_entity = SimpleNamespace(get_asset=lambda _name: None)
    fetches = []

    def fetch_one(entity, *, request):
        fetches.append((entity, request))
        return entity

    monkeypatch.setattr(
        main.responses,
        "not_found",
        lambda message: (message, 404),
    )
    monkeypatch.setattr(main.Entities, "fetch_one", fetch_one)

    response = main.get_image.__wrapped__(
        "stored-key",
        "missing-asset",
        entity=provided_entity,
    )

    assert response == ("Content not found", 404)
    assert fetches[0][0] is provided_entity
    assert fetches[0][1].depth is FetchDepth.DIRECT
    assert fetches[0][1].reason is None
    with pytest.raises(KeyError, match="entity"):
        main.get_image.__wrapped__("stored-key", "missing-asset")
