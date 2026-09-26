"""Entity-oriented proposal display adapters."""

from ..contracts import (
    InheritedProposalDetail,
    ProposalActionDisplay,
    ProposalActionGrouping,
)


# @testable infrastructure
def category_details(details, data, action=None):
    details.reference("Form", data, "form")


# @testable infrastructure
def page_details(details, data, action=None):
    details.reference("Category", data, "category", "model")
    details.reference("Form", data, "form")
    details.submission(data, form_present=bool(details.first_value(data, "form")))
    if data.get("document_markdown") or data.get("document"):
        details.add(
            "Document", data.get("document_markdown") or data.get("document"),
            preview="document",
        )


# @testable infrastructure
def document_details(details, data, action=None):
    details.reference("Page", data, "page")
    replacing = (action or {}).get("type") == "replace_page_document"
    details.add(
        "Replacement" if replacing else "Append", data.get("document_markdown") or data.get("document"),
        preview="document",
    )
    details.add("Recovery" if replacing else "Attribution", "The previous document will be pinned; this replaces its content as a collaborative edit." if replacing else "Server-recorded time and source; existing text is preserved.")


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
    ProposalActionDisplay("suggest_page_deletion", "Suggest Page Deletion", hidden=True),
)
