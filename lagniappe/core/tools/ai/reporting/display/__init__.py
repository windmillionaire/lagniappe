"""Read-only display projection for stored AI report proposals."""


# @testable infrastructure
# @covered-by lagniappe/core/tools/ai/reporting/display/projector.py::ProposalDisplayProjector.display_actions
def proposal_display_actions(proposal):
    """Project a stored proposal into the grouped display tree."""

    from .projector import ProposalDisplayProjector

    return ProposalDisplayProjector(proposal).display_actions
