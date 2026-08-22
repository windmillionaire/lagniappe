"""Task-oriented proposal display adapters."""

from ..contracts import (
    InheritedProposalDetail,
    ProposalActionDisplay,
    ProposalActionGrouping,
)


# @testable infrastructure
def model_task_details(details, data, action=None):
    details.reference("Project", data, "project")
    details.reference("Form", data, "form")


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_group_completed_task_events
# @pair ai-report:completed-task
# @pair ai-report:proposal
def task_details(details, data, action=None):
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


# @testable infrastructure
def move_task_details(details, data, action=None):
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
    ProposalActionDisplay("move_task", "Move Task", move_task_details),
)
