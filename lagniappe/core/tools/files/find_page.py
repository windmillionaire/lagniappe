"""Page lookup helpers for CSV import workflows."""

import re

from thefuzz import process

from ...definitions import Restriction
from .. import cache


FUZZY_MATCH_THRESHOLD = 80
WEAK_MATCH_THRESHOLD = 90


# @testable true
# @tests tests_unit/test_006c_files_find_page.py::test_find_page_exact_name_match
# @tests tests_unit/test_006c_files_find_page.py::test_find_page_no_match_returns_error
# @tests tests_unit/test_006c_files_find_page.py::test_find_page_fuzzy_weak_match_returns_warning
# @tests tests_unit/test_006c_files_find_page.py::test_find_page_fuzzy_low_confidence_returns_error
# @features ingress link
# @dimensions page-match fuzzy-match no-match weak-match
def find_page(value, match_field_label="Name", fuzzy=False, error_label=None):
    """Find a page by name or cached form-field snippet for CSV imports."""
    result = {"id": None, "warnings": [], "errors": []}
    lookup_value = _lookup_value(value)
    label = error_label or match_field_label

    if not lookup_value:
        result["errors"].append(f"No page found for {label}: '{lookup_value}'")
        return result

    search_results = cache.kind_search(
        lookup_value, "page", Restriction.UNRESTRICTED, ["owner"]
    )
    candidates = _page_candidates(search_results, match_field_label)

    if not candidates:
        result["errors"].append(f"No page found for {label}: '{lookup_value}'")
        return result

    if fuzzy:
        match = process.extractOne(lookup_value, candidates.keys())
        if not match or match[1] < FUZZY_MATCH_THRESHOLD:
            closest = match[0] if match else lookup_value
            result["errors"].append(
                f"No page found for {label}: '{lookup_value}' "
                f"(Closest match: '{closest}')"
            )
            return result
        if match[1] < WEAK_MATCH_THRESHOLD:
            result["warnings"].append(f"Weak match for {label}: '{match[0]}'")
        result["id"] = candidates.get(match[0])
        return result

    page_id = candidates.get(lookup_value)
    if not page_id:
        result["errors"].append(f"No page found for {label}: '{lookup_value}'")
        return result

    result["id"] = page_id
    return result


# @testable false
# @covered-by lagniappe/core/tools/files/find_page.py::find_page
# @reason helper-owned-by page lookup normalization contract
def _lookup_value(value):
    if isinstance(value, list):
        value = " ".join(
            str(item).strip()
            for item in value
            if item is not None and str(item).strip()
        )
    elif value is not None:
        value = str(value).strip()
    return value or None


# @testable false
# @covered-by lagniappe/core/tools/files/find_page.py::find_page
# @reason helper-owned-by page lookup candidate extraction contract
def _page_candidates(search_results, match_field_label):
    if match_field_label.lower() == "name":
        return {r["name"]: r["id"] for r in search_results if r.get("name")}

    return {
        re.sub(r"</?b>", "", str(r["form_value"])): r["id"]
        for r in search_results
        if r.get("form_value") and r.get("form_field") == match_field_label
    }
