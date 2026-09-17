"""Form-oriented proposal display adapters."""

from ..contracts import ProposalActionDisplay, ProposalActionGrouping


# @testable infrastructure
def create_form_details(details, data, action=None):
    details.add("Form Type", data.get("form_type") or data.get("form-type"))


# @testable true
# @matrix ai-report form-schema : details proposal
def schema_details(details, data, action=None):
    details.reference("Form", data, "form")
    operations = data.get("operations")
    if isinstance(operations, list):
        count = len(operations)
        details.add("Updates", f"{count} schema change{'s' if count != 1 else ''}")


FORM_ACTION_DISPLAYS = (
    ProposalActionDisplay("create_form", "Form", create_form_details),
    ProposalActionDisplay(
        "update_form_schema",
        "Update Form Schema",
        schema_details,
        grouping=ProposalActionGrouping.SCHEMA,
    ),
)
