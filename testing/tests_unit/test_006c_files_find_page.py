"""Page lookup helpers used by CSV import workflows."""

import importlib

import pytest

from lagniappe.core.definitions import Restriction

pytestmark = pytest.mark.unit


def _find_page_module():
    return importlib.import_module("lagniappe.core.tools.files.find_page")


# @matrix ingress link : page-match
def test_find_page_exact_name_match(monkeypatch):
    find_page = _find_page_module()
    calls = []

    def kind_search(query, kind, restrictions, belongs_to):
        calls.append((query, kind, restrictions, belongs_to))
        return [{"id": "wrong-page", "name": "Other Page"},
                {"id": "page-1", "name": "Target Page"}]

    monkeypatch.setattr(find_page.cache, "kind_search", kind_search)

    assert find_page.find_page("Target Page") == {
        "id": "page-1",
        "warnings": [],
        "errors": [],
    }
    assert calls == [("Target Page", "page", Restriction.UNRESTRICTED, Restriction.BELONGS_TO_ALL)]


# @matrix ingress link : no-match page-match
def test_find_page_no_match_returns_error(monkeypatch):
    find_page = _find_page_module()
    monkeypatch.setattr(find_page.cache, "kind_search", lambda *args: [])

    result = find_page.find_page("Missing Page", error_label="Related")
    assert result["id"] is None and result["warnings"] == []
    assert len(result["errors"]) == 1
    assert all(text in result["errors"][0] for text in ("No page", "Related", "Missing Page"))


# @matrix ingress link : fuzzy-match page-match weak-match
def test_find_page_fuzzy_weak_match_returns_warning(monkeypatch):
    find_page = _find_page_module()
    monkeypatch.setattr(
        find_page.cache,
        "kind_search",
        lambda *args: [{"id": "page-1", "name": "Target Page"}],
    )
    def match(value, candidates):
        assert value == "Targt Page"
        assert list(candidates) == ["Target Page"]
        return "Target Page", 85

    monkeypatch.setattr(find_page.process, "extractOne", match)

    result = find_page.find_page("Targt Page", fuzzy=True)
    assert result["id"] == "page-1" and result["errors"] == []
    assert len(result["warnings"]) == 1
    assert all(text in result["warnings"][0] for text in ("Weak match", "Name", "Target Page"))


# @matrix ingress link : fuzzy-match no-match page-match
def test_find_page_fuzzy_low_confidence_returns_error(monkeypatch):
    find_page = _find_page_module()
    monkeypatch.setattr(
        find_page.cache,
        "kind_search",
        lambda *args: [{"id": "page-1", "name": "Target Page"}],
    )
    monkeypatch.setattr(
        find_page.process,
        "extractOne",
        lambda value, candidates: ("Target Page", 70),
    )

    result = find_page.find_page("Different", fuzzy=True, error_label="Related")
    assert result["id"] is None and result["warnings"] == []
    assert len(result["errors"]) == 1
    assert all(text in result["errors"][0] for text in ("No page", "Related", "Different", "Target Page"))
