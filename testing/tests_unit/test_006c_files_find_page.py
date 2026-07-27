"""Page lookup helpers used by CSV import workflows."""

import importlib

import pytest

from lagniappe.core.definitions import Restriction

pytestmark = pytest.mark.unit


def _find_page_module():
    return importlib.import_module("lagniappe.core.tools.files.find_page")


# @features ingress link
# @dimensions page-match
def test_find_page_exact_name_match(monkeypatch):
    find_page = _find_page_module()
    calls = []

    def kind_search(query, kind, restrictions, belongs_to):
        calls.append((query, kind, restrictions, belongs_to))
        return [{"id": "page-1", "name": "Target Page"}]

    monkeypatch.setattr(find_page.cache, "kind_search", kind_search)

    assert find_page.find_page("Target Page") == {
        "id": "page-1",
        "warnings": [],
        "errors": [],
    }
    assert calls == [("Target Page", "page", Restriction.UNRESTRICTED, ["owner"])]


# @features ingress link
# @dimensions page-match no-match
def test_find_page_no_match_returns_error(monkeypatch):
    find_page = _find_page_module()
    monkeypatch.setattr(find_page.cache, "kind_search", lambda *args: [])

    assert find_page.find_page("Missing Page", error_label="Related") == {
        "id": None,
        "warnings": [],
        "errors": ["No page found for Related: 'Missing Page'"],
    }


# @features ingress link
# @dimensions page-match fuzzy-match weak-match
def test_find_page_fuzzy_weak_match_returns_warning(monkeypatch):
    find_page = _find_page_module()
    monkeypatch.setattr(
        find_page.cache,
        "kind_search",
        lambda *args: [{"id": "page-1", "name": "Target Page"}],
    )
    monkeypatch.setattr(
        find_page.process,
        "extractOne",
        lambda value, candidates: ("Target Page", 85),
    )

    assert find_page.find_page("Targt Page", fuzzy=True) == {
        "id": "page-1",
        "warnings": ["Weak match for Name: 'Target Page'"],
        "errors": [],
    }


# @features ingress link
# @dimensions page-match fuzzy-match no-match
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

    assert find_page.find_page("Different", fuzzy=True, error_label="Related") == {
        "id": None,
        "warnings": [],
        "errors": [
            "No page found for Related: 'Different' (Closest match: 'Target Page')"
        ],
    }
