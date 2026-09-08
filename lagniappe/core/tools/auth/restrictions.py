"""Explicit permission dependencies and the shared restriction-list contract."""

from ...definitions import Action, Fetch
from ...exceptions import UnloadedRelationError


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_page_restrictions_take_precedence
# @matrix permissions : page-precedence owner-fallback
def combine_restrictions(page, form):
    """Normalize the first restricted source, with the site-owner fallback."""
    page, form = set(page or ()), set(form or ())
    groups = page or form
    if not page and not form:
        return []
    return ["owner", *sorted(groups - {"owner"})]


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


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_permission_preparation_only_loads_missing_sources
# @matrix permissions relations : batch explicit-fetch-depth no-group-expansion
def prepare_permissions(*entities, action=Action.VIEW):
    """Attach only missing permission sources; never expand a Group graph."""
    from ...entities import Entities

    known = {entity.key: entity for entity in entities if entity is not None}
    visited = set()
    pending = list(known.values())
    while pending:
        missing, relations, next_entities = set(), [], []
        for entity in pending:
            if entity.key in visited:
                continue
            visited.add(entity.key)
            kind = entity.entity_kind
            names = []
            if kind == "file":
                names = ["page", "task"]
            elif kind == "task_history":
                names = ["task"]
            elif kind == "task":
                names = ["page", "form"]
            elif kind == "page":
                if not entity.db.get("restricted_to"):
                    names.append("form")
                if action.value > Action.VIEW.value:
                    names.append("user")
            for name in names:
                prop = entity.properties.get(name)
                if prop is None or not prop.key:
                    continue
                if prop.is_set and prop.value is not None:
                    known[prop.key] = prop.value
                    next_entities.append(prop.value)
                else:
                    relations.append(prop)
                    if prop.key in known:
                        next_entities.append(known[prop.key])
                    else:
                        missing.add(prop.key)
        missing -= known.keys()
        if missing:
            loaded = Entities.fetch(*missing, request=Fetch.root())
            known.update((entity.key, entity) for entity in loaded)
            next_entities.extend(loaded)
        for prop in relations:
            prop.attach(known)
        pending = next_entities
    return entities
