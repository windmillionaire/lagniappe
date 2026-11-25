"""Task-oriented proposal display adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.tools.ai.reporting.contracts.actions import ActionData, ReportAction
    from lagniappe.core.tools.ai.reporting.display.details import ProposalDetailCollector


from ..contracts import (
    InheritedProposalDetail,
    ProposalActionDisplay,
    ProposalActionGrouping,
)


def model_task_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Project", data, "project")
    details.reference("Form", data, "form")


def task_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Task", data, "task")
    details.reference("Page", data, "page")
    details.reference("Project", data, "project")
    details.reference("Model Task", data, "model")
    details.reference("Form", data, "form")
    details.add("Due Date", data.get("due_date") or data.get("due-date"))
    completed_on = data.get("completed_on") or data.get("completed-on")
    details.add("Completed On", completed_on)
    if data.get("completed") is True and not completed_on:
        details.add("Status", "Completed")
    details.submission(data, form_present=bool(details.first_value(data, "form")))
    for file_ref in details.file_values(data):
        details.add_reference("File", file_ref)


def move_task_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Task", data, "task")
    details.reference("Page", data, "to_page", "page")


TASK_ACTION_DISPLAYS = (
    ProposalActionDisplay("create_model_task", "Model Task", model_task_details),
    ProposalActionDisplay(
        "create_task",
        "Task",
        task_details,
        grouping=ProposalActionGrouping.TASK,
        inherited_details=(
            InheritedProposalDetail(("model",), "Project", ("project",)),
            InheritedProposalDetail(("model",), "Form", ("form",)),
        ),
    ),
    ProposalActionDisplay("complete_task", "Complete Task", task_details),
    ProposalActionDisplay("move_task", "Move Task", move_task_details),
)
