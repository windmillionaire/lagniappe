"""Masked mutation plans for collaborative-document persistence."""
from typing import TYPE_CHECKING

from ..definitions import MutationOperation
from .base import MutationPlanBuilder
from .registry import planner_for

if TYPE_CHECKING:
    from ..definitions import MutationPlan
    from ..entities import EntityRegistry
    from ..entities.entity import Entity


def _advance_parent(builder: MutationPlanBuilder, entity: Entity) -> None:
    builder.touch(entity, reason="document-parent")
    for owner in getattr(entity, "page_list_owners", ()):
        builder.touch(owner, reason="document-page-list-owner")


def plan_document_checkpoint(
    entity: Entity,
    *,
    advance_parent: bool = False,
    registry: EntityRegistry | None = None,
) -> MutationPlan:
    """Persist document assets/history without writing unrelated parent fields."""
    builder = MutationPlanBuilder(
        MutationOperation.SAVE,
        (entity,),
        registry=registry,
        planner_for=planner_for,
    )
    builder.patch(
        entity,
        "assets",
        "document_history",
        property_updates=(),
        reason="document-checkpoint",
    )
    builder.consume_intents(entity)
    if advance_parent:
        _advance_parent(builder, entity)
    return builder.build()


def plan_document_parent_touch(
    entity: Entity, *, registry: EntityRegistry | None = None
) -> MutationPlan:
    """Advance document ownership metadata without rewriting document/form state."""
    builder = MutationPlanBuilder(
        MutationOperation.SAVE,
        (entity,),
        registry=registry,
    )
    _advance_parent(builder, entity)
    return builder.build()
