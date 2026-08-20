"""Explicit kind-to-planner routing for entity mutations."""

from .base import StandardMutation
from .save import (
    FileMutation,
    FilterMutation,
    FormMutation,
    JobMutation,
    ModelMutation,
    NoteMutation,
    NotificationMutation,
    PageMutation,
    ReportMutation,
    TaskHistoryMutation,
    TaskMutation,
    UserMutation,
)


STANDARD = StandardMutation()

SAVE_PLANNERS = {
    "user": UserMutation(),
    "project": STANDARD,
    "model": ModelMutation(),
    "file": FileMutation(),
    "ingress": STANDARD,
    "form": FormMutation(),
    "category": STANDARD,
    "users": STANDARD,
    "page": PageMutation(),
    "task": TaskMutation(),
    "group": STANDARD,
    "public_group": STANDARD,
    "filter": FilterMutation(),
    "task_history": TaskHistoryMutation(),
    "notification": NotificationMutation(),
    "note": NoteMutation(),
    "form_history": STANDARD,
    "document_history": STANDARD,
    "job": JobMutation(),
    "job_lock": STANDARD,
    "report": ReportMutation(),
    "message_conversation": STANDARD,
    "message": STANDARD,
    "mention_marker": STANDARD,
}


# @testable true
# @tests tests_unit/test_022_mutation_contracts.py::test_mutation_contract_registry_covers_persisted_entities_and_relations
# @features mutations
# @dimensions contract completeness planner-registry
def planner_for(entity):
    kind = getattr(entity, "entity_kind", None) or getattr(entity, "kind", None)
    try:
        return SAVE_PLANNERS[kind]
    except KeyError as error:
        raise ValueError(f"No mutation planner registered for kind: {kind}") from error


# @testable false
# @covered-by lagniappe/core/mutations/registry.py::planner_for
# @reason registry keys are exposed through the package completeness check
def registered_kinds():
    return frozenset(SAVE_PLANNERS)
