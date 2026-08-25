"""Focused deferred-job behavior tests."""

from types import SimpleNamespace

import pytest

from lagniappe.core.tools.deferred_jobs.adapters import pages as page_adapters


pytestmark = pytest.mark.unit


# @matrix pages : form-defaults no-form
# @pair ai:page-generation
def test_page_generation_apply_uses_direct_fields_and_form_fallbacks(monkeypatch):
    created = []
    saved = []

    class GeneratedPage:
        @classmethod
        def create(cls, data):
            page = cls()
            page.name = data.get("name")
            page.description = data.get("description")
            page.form = data.get("form")
            page.properties = SimpleNamespace(
                document=SimpleNamespace(html=None),
            )
            page.urlsafe_key = f"page-{len(created) + 1}"
            page.submission = None
            created.append(page)
            return page

        def ai_submission(self, submission):
            self.submission = dict(submission)
            self.name = submission.get("name", self.name)
            self.description = submission.get("description", self.description)

    monkeypatch.setattr(page_adapters.Entities, "PAGE", GeneratedPage)
    monkeypatch.setattr(
        page_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        page_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        page_adapters.database.get,
        "datastore_key",
        lambda key: f"datastore:{key}",
    )

    category = SimpleNamespace()
    adapter = page_adapters.PageGenerationAdapter()

    without_form = SimpleNamespace(
        ensure_active=lambda: None,
        checkpoint={
            "pages": [
                {
                    "key": "plain-key",
                    "page": {
                        "submission": {
                            "name": "Legacy fallback name",
                            "description": "Legacy fallback description",
                        }
                    },
                }
            ]
        },
        input=lambda name: category if name == "category" else None,
    )
    assert adapter.apply(without_form) == {"page_keys": ["page-1"]}
    assert created[0].name == "Legacy fallback name"
    assert created[0].description == "Legacy fallback description"
    assert created[0].submission is None

    form = SimpleNamespace(
        schema=[
            {"id": "name"},
            {"id": "description"},
            {"id": "input-topic"},
        ]
    )
    with_form = SimpleNamespace(
        ensure_active=lambda: None,
        checkpoint={
            "pages": [
                {
                    "key": "formed-key",
                    "page": {
                        "name": "Direct name",
                        "description": "Direct description",
                        "submission": {
                            "name": "Stale form name",
                            "description": "Stale form description",
                            "input-topic": "Preserved topic",
                        },
                    },
                }
            ]
        },
        input=lambda name: {
            "category": category,
            "form": form,
        }.get(name),
    )
    assert adapter.apply(with_form) == {"page_keys": ["page-2"]}
    assert created[1].name == "Direct name"
    assert created[1].description == "Direct description"
    assert created[1].submission == {
        "name": "Direct name",
        "description": "Direct description",
        "input-topic": "Preserved topic",
    }
    assert len(saved) == 2
