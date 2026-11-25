"""Explicit permission dependencies and canonical source restrictions."""

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity

from ...exceptions import UnloadedRelationError


class PermissionRelation(Protocol):
    @property
    def key(self) -> object: ...
    @property
    def is_set(self) -> bool: ...
    @property
    def value(self) -> Entity | None: ...


RESTRICTION_SOURCES = ("page", "page_form", "task_form")


def normalize_restrictions(mapping: Mapping[str, Iterable[str]] | None) -> dict[str, list[str]]:
    """Copy nonempty source clauses, preserving their independent requirements."""
    normalized = {}
    for source in RESTRICTION_SOURCES:
        groups = set((mapping or {}).get(source) or ())
        if groups:
            normalized[source] = ["admin"] if "admin" in groups else sorted(groups)
    return normalized


def restriction_fields(mapping: Mapping[str, Iterable[str]] | None) -> dict[str, str]:
    """Encode each source independently as a Redis TAG field."""
    return {
        f"restricted_to_{source}": ",".join(groups)
        for source, groups in normalize_restrictions(mapping).items()
    }


def permission_relation(entity: Entity, name: str, *, required: bool = False) -> Entity | None:
    prop = cast("PermissionRelation | None", entity.properties.get(name))
    if prop is None or not prop.key:
        if required:
            raise UnloadedRelationError(f"{entity.entity_kind}.{name} is required")
        return None
    if not prop.is_set or (required and prop.value is None):
        raise UnloadedRelationError(f"{entity.entity_kind}.{name} must be loaded")
    return prop.value
