"""Form-oriented proposal display adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.tools.ai.reporting.contracts.actions import ActionData, ReportAction
    from lagniappe.core.tools.ai.reporting.display.details import ProposalDetailCollector


from ..contracts import ProposalActionDisplay, ProposalActionGrouping


def create_form_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
    details.add("Form Type", data.get("form_type") or data.get("form-type"))


def schema_details(
    details: ProposalDetailCollector,
    data: ActionData,
    action: ReportAction | None = None,
) -> None:
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
