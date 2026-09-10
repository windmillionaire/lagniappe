"""Explicit permission dependencies and canonical source restrictions."""

from ...exceptions import UnloadedRelationError


RESTRICTION_SOURCES = ("page", "page_form", "task_form")


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_restrictions_normalize_source_clauses
# @matrix permissions : source-clauses stable-order admin-only
def normalize_restrictions(mapping):
    """Copy nonempty source clauses, preserving their independent requirements."""
    normalized = {}
    for source in RESTRICTION_SOURCES:
        groups = set((mapping or {}).get(source) or ())
        if groups:
            normalized[source] = ["admin"] if "admin" in groups else sorted(groups)
    return normalized


# @testable true
# @tests tests_unit/test_002_entity_general_properties.py::test_restriction_fields_keep_source_boundaries
# @matrix permissions cache : source-clauses stable-order
def restriction_fields(mapping):
    """Encode each source independently as a Redis TAG field."""
    return {
        f"restricted_to_{source}": ",".join(groups)
        for source, groups in normalize_restrictions(mapping).items()
    }


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_required_permission_relation_does_not_hide_unloaded_page
# @matrix permissions relations : required-parent unloaded-relation
def permission_relation(entity, name, *, required=False):
    prop = entity.properties.get(name)
    if prop is None or not prop.key:
        if required:
            raise UnloadedRelationError(f"{entity.entity_kind}.{name} is required")
        return None
    if not prop.is_set or prop.value is None:
        raise UnloadedRelationError(f"{entity.entity_kind}.{name} must be loaded")
    return prop.value
