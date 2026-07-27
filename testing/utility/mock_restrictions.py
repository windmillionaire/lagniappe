"""
Stand-in for ``cache.get_details_by_hash`` when testing ``Restrictions`` facets.

Production code uses Redis-backed entity details; unit and e2e tests can patch
``get_details_by_hash`` with :meth:`MockRestrictions.get_details_by_hash` so
facet logic (task / form / users / can_assign) runs without cache.

Heuristics match common test fixture hashes (``cat*``, ``page*``, ``grp*``,
``puser*``, …). Override any hash with ``kind_overrides`` when needed.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping
from unittest.mock import patch

__all__ = ["MockRestrictions"]


class MockRestrictions:
    """Builds ``{hash: {"hash", "kind"}}`` maps like the real cache layer."""

    _GLOBAL_KEYS = frozenset({"users", "models", "forms"})

    def __init__(self, *, kind_overrides: Mapping[str, Mapping[str, Any]] | None = None):
        self._overrides = dict(kind_overrides or {})

    def entity_detail(self, h: str) -> dict[str, Any]:
        if h in self._overrides:
            return dict(self._overrides[h])
        return self._infer_detail(h)

    @classmethod
    def _infer_detail(cls, h: str) -> dict[str, Any]:
        if h in cls._GLOBAL_KEYS:
            return {"hash": h, "kind": h.rstrip("s")}
        if h.startswith("grp"):
            return {"hash": h, "kind": "group"}
        if h.startswith("cat"):
            return {"hash": h, "kind": "category"}
        if h.startswith("page"):
            return {"hash": h, "kind": "page"}
        if h.startswith("puser") or h.startswith("powner") or h.startswith("pg"):
            return {"hash": h, "kind": "page"}
        return {"hash": h, "kind": "page"}

    def get_details_by_hash(self, hashes: Iterable[str] | None) -> dict[str, Any]:
        """Same contract as ``lagniappe.core.tools.cache.get_details_by_hash``."""
        if not hashes:
            return {}
        if isinstance(hashes, str):
            hashes = [hashes]
        return {h: self.entity_detail(h) for h in hashes}

    def patch_cache(
        self,
        target: str = "lagniappe.core.properties.user_restrictions.cache.get_details_by_hash",
    ):
        """Patch the restrictions module's cache lookup to use this instance."""
        return patch(target, side_effect=self.get_details_by_hash)
