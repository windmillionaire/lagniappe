"""Explicit kind-to-planner routing for entity mutations."""
from typing import TYPE_CHECKING, cast

from .base import StandardMutation
from .save import (
    CategoryMutation,
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

if TYPE_CHECKING:
    from ..entities.entity import Entity


STANDARD = StandardMutation()

SAVE_PLANNERS = {
    "user": UserMutation(),
    "project": STANDARD,
    "model": ModelMutation(),
    "file": FileMutation(),
    "ingress": STANDARD,
    "form": FormMutation(),
    "category": CategoryMutation(),
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


def planner_for(entity: Entity) -> StandardMutation[Entity]:
    kind = getattr(entity, "entity_kind", None) or getattr(entity, "kind", None)
    try:
        return cast("StandardMutation[Entity]", SAVE_PLANNERS[cast(str, kind)])
    except KeyError as error:
        raise ValueError(f"No mutation planner registered for kind: {kind}") from error


def registered_kinds() -> frozenset[str]:
    return frozenset(SAVE_PLANNERS)
