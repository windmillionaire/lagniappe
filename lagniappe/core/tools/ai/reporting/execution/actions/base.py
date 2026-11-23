"""Adapter protocol for deterministic report actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.tools.ai.reporting.contracts.actions import ReportAction
    from lagniappe.core.tools.ai.reporting.execution.batch import WorkingEntities
    from lagniappe.core.tools.ai.reporting.execution.ledger import ActionRecord
    from lagniappe.core.tools.ai.reporting.execution.runner import ExecutionContext


from .checkpoints import _prepare_action_checkpoint
from .recovery import _inspect_action_applied


type ExecutionResult = tuple[Entity | None, Sequence[Entity], Mapping[str, object]]
type HandlerResult = tuple[Entity | None, Sequence[Entity]] | ExecutionResult
type ActionHandler = Callable[[ReportAction, models.AIReport, models.User, WorkingEntities], HandlerResult]
type ContextHandler = Callable[[ReportAction, models.AIReport, models.User, WorkingEntities, ExecutionContext], HandlerResult]


ACTION_APPLIED = "applied"
ACTION_NOT_APPLIED = "not-applied"
ACTION_DRIFTED = "drifted"


class ReportActionAdapter:
    """Recovery contract for one deterministic report action type."""

    def __init__(
        self,
        action_type: str,
        apply_handler: ActionHandler | ContextHandler,
        *,
        uses_context: bool = False,
        required: bool = False,
    ) -> None:
        self.action_type = action_type
        self.apply_handler = apply_handler
        self.uses_context = uses_context
        self.required = required

    def prepare(
        self,
        action: ReportAction,
        report: models.AIReport,
        user: models.User,
        created: WorkingEntities,
        context: ExecutionContext,
        record: ActionRecord,
    ) -> ActionRecord | None:
        return _prepare_action_checkpoint(
            action,
            report,
            user,
            created,
            context,
            record,
        )

    def inspect_applied(
        self,
        action: ReportAction,
        report: models.AIReport,
        user: models.User,
        record: ActionRecord,
    ) -> str:
        return _inspect_action_applied(action, report, user, record)

    def apply(
        self,
        action: ReportAction,
        report: models.AIReport,
        user: models.User,
        created: WorkingEntities,
        context: ExecutionContext | None,
    ) -> ExecutionResult:
        arguments = (action, report, user, created)
        # The registry records the calling convention of each handler.
        if self.uses_context:
            handler = cast("ContextHandler", self.apply_handler)
            return _normalize_handler_result(handler(*arguments, context or {}))
        handler = cast("ActionHandler", self.apply_handler)
        return _normalize_handler_result(handler(*arguments))


def _normalize_handler_result(result: HandlerResult) -> ExecutionResult:
    if len(result) == 2:
        entity, to_save = result
        return entity, to_save, {}
    return result
