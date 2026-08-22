"""Non-mutating review-state proposal display definitions."""

from ..contracts import ProposalActionDisplay, ProposalActionGrouping


REVIEW_ACTION_DISPLAYS = (
    ProposalActionDisplay(
        "needs_review", "Needs Review", grouping=ProposalActionGrouping.REVIEW
    ),
    ProposalActionDisplay("skip", "Skip", grouping=ProposalActionGrouping.REVIEW),
)
