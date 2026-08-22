"""File-oriented proposal display adapters."""

from ..contracts import ProposalActionDisplay, ProposalActionGrouping


# @testable infrastructure
def move_file_details(details, data, action=None):
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


# @testable infrastructure
def page_attachment_details(details, data, action=None):
    details.reference("Page", data, "page")
    details.reference("File", data, "file")


# @testable infrastructure
def task_attachment_details(details, data, action=None):
    details.reference("Task", data, "task")
    details.reference("File", data, "file")


# @testable infrastructure
def summary_details(details, data, action=None):
    details.reference("File", data, "file")
    details.add("Summary", data.get("summary"))


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_group_move_files_under_target_page
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_existing_page_category_for_attachments
# @pair ai-report:details
# @pair ai-report:move-file
# @pair ai-report:proposal
# @pair files:details
# @pair files:existing-page-category
# @pair files:move-file
# @pair files:proposal
# @pair files:attachment-grouping
def file_action_displays():
    return (
        ProposalActionDisplay(
            "move_file",
            "Move File",
            move_file_details,
            grouping=ProposalActionGrouping.FILE_MOVE,
            prefer_file_label=True,
        ),
        ProposalActionDisplay(
            "attach_file_to_page",
            "Attached File",
            page_attachment_details,
            grouping=ProposalActionGrouping.PAGE_ATTACHMENT,
        ),
        ProposalActionDisplay(
            "attach_file_to_task",
            "Attached File",
            task_attachment_details,
            grouping=ProposalActionGrouping.TASK_ATTACHMENT,
        ),
        ProposalActionDisplay(
            "summarize_file",
            "Summary",
            summary_details,
            grouping=ProposalActionGrouping.FILE_SUMMARY,
        ),
    )


FILE_ACTION_DISPLAYS = file_action_displays()
