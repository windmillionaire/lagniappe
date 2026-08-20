"""Kind-routed executable entity mutation planning."""

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


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_each_explicit_save_argument_is_a_standard_root
# @features mutations
# @dimensions save multiple-explicit-roots standard-lifecycle property-mask
def plan_mutation(operation, *entities, registry=None):
    """Route explicit roots through their registered kind planners."""
    if not isinstance(operation, MutationOperation):
        raise TypeError("plan_mutation requires a MutationOperation")
    if registry is None:
        from ..entities import Entities

        registry = Entities

    entities = tuple(entity for entity in entities if hasattr(entity, "db"))
    if operation is MutationOperation.DELETE:
        return plan_delete(*entities, registry=registry)

    builder = MutationPlanBuilder(operation, entities, registry=registry)
    for entity in entities:
        builder.plan_standard(entity, reason="explicit-root")
    return builder.build()


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_save_root_persists_full_exclusions_without_lifecycle_intents_or_cache
# @tests tests_unit/test_022_mutation_contracts.py::test_touch_uses_masked_root_save_and_only_updates_modified
# @features mutations
# @dimensions root-save property-mask lifecycle-isolation
def plan_root(*entities, property_mask=None, property_updates=()):
    return RootMutation.plan(
        *entities,
        property_mask=property_mask,
        property_updates=property_updates,
    )


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_mutation_contract_registry_covers_persisted_entities_and_relations
# @features mutations
# @dimensions planner-registry completeness
def registered_kinds():
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
