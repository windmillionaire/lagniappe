"""Deterministic entity revisions shared by durable and cached projections."""

import hashlib
import json

from ..tools.auth.restrictions import normalize_restrictions


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_restricted_fingerprints_share_the_entity_and_cache_formula
# @matrix permissions cache : fingerprint modified stable-order
def base_fingerprint(modified):
    """Hash the durable modification timestamp without changing its meaning."""
    return hashlib.md5(modified.isoformat().encode("utf-8")).hexdigest()


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_restricted_fingerprints_share_the_entity_and_cache_formula
# @tests tests_unit/test_002_entity_general_properties.py::test_restriction_fingerprint_preserves_source_boundaries
# @matrix permissions cache : fingerprint form-version stable-order
# @matrix permissions cache : source-clauses
def restricted_fingerprint(base, restricted_to, *, form_version=None):
    """Include independent source clauses and the entity's own Form version.

    ``None`` omits the Form component for Files; ``""`` represents a Page or
    Task without a Form. Source boundaries matter; group order and duplicates do not.
    """
    parts = [base]
    if form_version is not None:
        parts.append(form_version)
    parts.append(json.dumps(normalize_restrictions(restricted_to), sort_keys=True, separators=(",", ":")))
    return hashlib.md5(":".join(parts).encode("utf-8")).hexdigest()
