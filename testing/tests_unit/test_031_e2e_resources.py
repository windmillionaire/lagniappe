"""Test-resource identity survives per-test row snapshot invalidation."""

from enum import Enum
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from testing.resources.core import SiteResource
from testing.utility import e2e_resources, e2e_worker


pytestmark = pytest.mark.unit


# @matrix testing : parallel-e2e
def test_enum_identity_is_reused_after_forgetting_and_across_process_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LAGNIAPPE_E2E_WORKER_CONTEXT", "test-context")
    monkeypatch.setattr(e2e_worker, "context", lambda: {"resource_registry": str(tmp_path)})
    row = SimpleNamespace(urlsafe_key="created-page", name="First")
    fetch = Mock(side_effect=lambda *_a, **_kw: SimpleNamespace(urlsafe_key=row.urlsafe_key, name=row.name))
    monkeypatch.setattr("testing.resources.core.Entities.fetch_one", fetch)

    class Resource(SiteResource):
        def create(self):
            self.entity = SimpleNamespace(urlsafe_key=row.urlsafe_key, name=row.name)

    class Pages(Enum):
        story = Resource()

    resource = e2e_resources.resolve_resource(Pages.story, None)
    assert resource.key == "created-page"
    resource.entity.name = "Setup edit"
    assert resource.entity.name == "Setup edit"
    fetch.assert_not_called()
    SiteResource.forget_entities()
    row.name = "Saved through browser"
    assert resource.key == "created-page"
    fetch.assert_not_called()
    assert resource.entity.name == "Saved through browser"
    assert resource.entity.name == "Saved through browser"
    assert fetch.call_count == 1
    resource.key = None  # A newly imported worker has no cached key or row.
    resource.create = Mock(side_effect=AssertionError("must reuse coordinator identity"))
    reused = e2e_resources.resolve_resource(Pages.story, None)
    assert reused.key == "created-page"
    assert reused.entity.name == "Saved through browser"
    assert fetch.call_count == 2
