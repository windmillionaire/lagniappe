"""Entity-oriented proposal display adapters."""

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


def category_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Form", data, "form")


def page_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Category", data, "category", "model")
    details.reference("Form", data, "form")
    details.submission(data, form_present=bool(details.first_value(data, "form")))
    if data.get("document_markdown") or data.get("document"):
        details.add(
            "Document", data.get("document_markdown") or data.get("document"),
            preview="document",
        )


def document_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Page", data, "page")
    replacing = (action or {}).get("type") == "replace_page_document"
    details.add(
        "Replacement" if replacing else "Append", data.get("document_markdown") or data.get("document"),
        preview="document",
    )
    details.add("Recovery" if replacing else "Attribution", "The previous document will be pinned; this replaces its content as a collaborative edit." if replacing else "Server-recorded time and source; existing text is preserved.")


def delete_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.reference("Entity", data, "entity")
    details.add("Effect", "Permanently deletes this record and its dependent data.")


ENTITY_ACTION_DISPLAYS = (
    ProposalActionDisplay("append_page_document", "Append Page Document", document_details),
    ProposalActionDisplay("replace_page_document", "Replace Page Document", document_details),
    ProposalActionDisplay("create_category", "Category", category_details),
    ProposalActionDisplay("create_project", "Project"),
    ProposalActionDisplay(
        "create_page",
        "Page",
        page_details,
        grouping=ProposalActionGrouping.PAGE,
        inherited_details=(
            InheritedProposalDetail(("category", "model"), "Form", ("form",)),
        ),
    ),
    ProposalActionDisplay("delete_page", "Delete Page", delete_details),
    ProposalActionDisplay("delete_task", "Delete Task", delete_details),
    ProposalActionDisplay("delete_category", "Delete Category", delete_details),
    ProposalActionDisplay("delete_project", "Delete Project", delete_details),
    ProposalActionDisplay("delete_model_task", "Delete Model Task", delete_details),
    ProposalActionDisplay("delete_file", "Delete File", delete_details),
    ProposalActionDisplay("suggest_page_deletion", "Suggest Page Deletion", hidden=True),
)
