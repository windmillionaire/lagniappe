"""Read-only display projection for stored AI report proposals."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.properties.ai_report_proposal import Proposal


def proposal_display_actions(proposal: Proposal) -> list[dict[str, object]]:
    """Project a stored proposal into the grouped display tree."""

    from .projector import ProposalDisplayProjector

    return ProposalDisplayProjector(proposal).display_actions
