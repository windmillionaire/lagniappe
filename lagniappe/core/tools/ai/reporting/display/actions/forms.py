"""Form-oriented proposal display adapters."""

from ..contracts import ProposalActionDisplay, ProposalActionGrouping


# @testable infrastructure
def create_form_details(details, data, action=None):
    details.add("Form Type", data.get("form_type") or data.get("form-type"))


# @testable infrastructure
def page_form_details(details, data, action=None):
    details.reference("Page", data, "page")
    details.reference("Form", data, "form")


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_proposal_display_actions_group_schema_updates_separately
# @matrix ai-report form-schema : details proposal schema-section skip-grouping
def schema_details(details, data, action=None):
    details.reference("Form", data, "form")
    operations = data.get("operations")
    if isinstance(operations, list):
        count = len(operations)
        details.add("Updates", f"{count} schema change{'s' if count != 1 else ''}")


# @testable infrastructure
def submission_update_details(details, data, action=None):
    updates = data.get("updates")
    if isinstance(updates, list):
        count = len(updates)
        details.add("Updates", f"{count} field update{'s' if count != 1 else ''}")


FORM_ACTION_DISPLAYS = (
    ProposalActionDisplay("create_form", "Form", create_form_details),
    ProposalActionDisplay(
        "add_form_to_page",
        "Add Form",
        page_form_details,
        grouping=ProposalActionGrouping.PAGE_FORM,
        label_detail="Form",
    ),
    ProposalActionDisplay(
        "update_form_schema",
        "Schema Update",
        schema_details,
        grouping=ProposalActionGrouping.SCHEMA,
    ),
    ProposalActionDisplay(
        "update_submission_fields",
        "Submission Update",
        submission_update_details,
    ),
)
