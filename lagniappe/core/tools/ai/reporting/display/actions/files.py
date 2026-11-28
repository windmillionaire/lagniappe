"""File-oriented proposal display adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.tools.ai.reporting.contracts.actions import ActionData, ReportAction
    from lagniappe.core.tools.ai.reporting.display.details import ProposalDetailCollector


from ..contracts import ProposalActionDisplay, ProposalActionGrouping


def move_file_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("File", data, "file")
    details.reference("From Page", data, "from_page", "source_page", "page_from")
    details.reference("From Task", data, "from_task", "source_task", "task_from")
    details.reference(
        "To Page",
        data,
        "to_page",
        "target_page",
        "destination_page",
        "page",
    )
    details.reference(
        "To Task",
        data,
        "to_task",
        "target_task",
        "destination_task",
        "task",
    )


def attachment_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Target", data, "entity")
    details.reference("File", data, "file")


def summary_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("File", data, "file")
    details.add("Summary", data.get("summary"))


def artifact_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Page", data, "page")


def file_action_displays() -> tuple[ProposalActionDisplay, ...]:
    return (
        ProposalActionDisplay(
            "move_file",
            "Move File",
            move_file_details,
            grouping=ProposalActionGrouping.FILE_MOVE,
            prefer_file_label=True,
        ),
        ProposalActionDisplay(
            "attach_file",
            "Attached File",
            attachment_details,
            grouping=ProposalActionGrouping.ATTACHMENT,
        ),
        ProposalActionDisplay("create_artifact", "Create Interactive Artifact", artifact_details),
        ProposalActionDisplay(
            "summarize_file",
            "Summary",
            summary_details,
            grouping=ProposalActionGrouping.FILE_SUMMARY,
        ),
    )


FILE_ACTION_DISPLAYS = file_action_displays()
