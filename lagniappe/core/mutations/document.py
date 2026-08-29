"""Masked mutation plans for collaborative-document persistence."""

from ..definitions import MutationOperation
from .base import MutationPlanBuilder


# @testable false
# @covered-by lagniappe/core/mutations/document.py::plan_document_checkpoint
# @covered-by lagniappe/core/mutations/document.py::plan_document_parent_touch
# @reason parent/list-owner masking is asserted through both public document plans
def _advance_parent(builder, entity):
    builder.touch(entity, reason="document-parent")
    for owner in getattr(entity, "page_list_owners", ()):
        builder.touch(owner, reason="document-page-list-owner")


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_document_checkpoint_masks_parent_state_and_optionally_advances_lists
# @matrix mutations sync : checkpoint document history list-owner parent-fingerprint property-mask
def plan_document_checkpoint(entity, *, advance_parent=False, registry=None):
    """Persist document assets/history without writing unrelated parent fields."""
    builder = MutationPlanBuilder(
        MutationOperation.SAVE,
        (entity,),
        registry=registry,
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


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_document_parent_touch_only_advances_parent_and_list_fingerprints
# @matrix mutations sync : document list-owner parent-fingerprint property-mask
def plan_document_parent_touch(entity, *, registry=None):
    """Advance document ownership metadata without rewriting document/form state."""
    builder = MutationPlanBuilder(
        MutationOperation.SAVE,
        (entity,),
        registry=registry,
    )
    _advance_parent(builder, entity)
    return builder.build()
