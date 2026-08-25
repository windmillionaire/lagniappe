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


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_groups_added_categories_under_page
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_existing_page_category_for_attachments
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_resolve_normalized_entity_refs
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_show_rename_entity_details
# @matrix ai-report : add-category attachment-grouping details display-labels existing-page-category normalized-references proposal rename
# @matrix categories : add-category attachment-grouping details existing-page-category proposal
def entity_reference_details(details, data, action=None):
    action_type = action.get("type")
    if action_type == "add_category":
        details.reference("Page", data, "page")
        details.reference("Category", data, "category", "model")
    elif action_type == "rename_entity":
        details.reference("Entity", data, "entity")
        details.add("New Name", data.get("name"))
    elif action_type == "move_page":
        details.reference("Page", data, "page")
        details.reference("Category", data, "category", "model")


ENTITY_ACTION_DISPLAYS = (
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
    ProposalActionDisplay(
        "add_category",
        "Add Category",
        entity_reference_details,
        grouping=ProposalActionGrouping.PAGE_CATEGORY,
        label_detail="Category",
    ),
    ProposalActionDisplay("move_page", "Move Page", entity_reference_details),
    ProposalActionDisplay("rename_entity", "Rename", entity_reference_details),
    ProposalActionDisplay("delete_page", "Delete Page", hidden=True),
)
