"""Kind-routed executable entity mutation planning."""
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..definitions import MutationOperation
from .base import MutationPlanBuilder, RootMutation, StandardMutation
from .delete import DELETE_PLANNERS, plan_delete
from .document import plan_document_checkpoint, plan_document_parent_touch
from .executor import (
    consume_mutation_intents,
    execute_mutation,
    execute_post_commit,
    prepare_durable_writes,
)
from .registry import SAVE_PLANNERS, planner_for

if TYPE_CHECKING:
    from ..definitions import MutationPlan
    from ..entities import EntityRegistry
    from ..entities.entity import Entity


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_each_explicit_save_argument_is_a_standard_root
# @matrix mutations : multiple-explicit-roots property-mask save standard-lifecycle
def plan_mutation(
    operation: MutationOperation,
    *entities: Entity,
    registry: EntityRegistry | None = None,
) -> MutationPlan:
    """Route explicit roots through their registered kind planners."""
    if not isinstance(operation, MutationOperation):
        raise TypeError("plan_mutation requires a MutationOperation")
    if registry is None:
        from ..entities import Entities

        registry = Entities

    entities = tuple(entity for entity in entities if hasattr(entity, "db"))
    if operation is MutationOperation.DELETE:
        return plan_delete(*entities, registry=registry)

    builder = MutationPlanBuilder(
        operation, entities, registry=registry, planner_for=planner_for
    )
    for entity in entities:
        builder.plan_standard(entity, reason="explicit-root")
    return builder.build()


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_save_root_persists_full_exclusions_without_lifecycle_intents_or_cache
# @tests tests_unit/test_022_mutation_contracts.py::test_touch_uses_masked_root_save_and_only_updates_modified
# @matrix mutations : lifecycle-isolation property-mask root-save
def plan_root(
    *entities: Entity,
    property_mask: Iterable[str] | None = None,
    property_updates: Iterable[str] = (),
) -> MutationPlan:
    return RootMutation.plan(
        *entities,
        property_mask=property_mask,
        property_updates=property_updates,
    )


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_mutation_contract_registry_covers_persisted_entities_and_relations
# @matrix mutations : completeness planner-registry
def registered_kinds() -> frozenset[str]:
    """Kinds with explicit save and delete planner registrations."""
    return frozenset(SAVE_PLANNERS) & frozenset(DELETE_PLANNERS)


__all__ = [
    "RootMutation",
    "StandardMutation",
    "execute_mutation",
    "execute_post_commit",
    "plan_mutation",
    "plan_document_checkpoint",
    "plan_document_parent_touch",
    "plan_root",
    "planner_for",
    "prepare_durable_writes",
    "registered_kinds",
    "consume_mutation_intents",
]
