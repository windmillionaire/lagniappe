"""Explicit registry of AI-report proposal display behavior."""

from .actions.entities import ENTITY_ACTION_DISPLAYS
from .actions.files import FILE_ACTION_DISPLAYS
from .actions.forms import FORM_ACTION_DISPLAYS
from .actions.review import REVIEW_ACTION_DISPLAYS
from .actions.tasks import TASK_ACTION_DISPLAYS
from .contracts import ProposalActionDisplay


REGISTERED_ACTION_DISPLAYS = (
    *ENTITY_ACTION_DISPLAYS,
    *FILE_ACTION_DISPLAYS,
    *FORM_ACTION_DISPLAYS,
    *TASK_ACTION_DISPLAYS,
    *REVIEW_ACTION_DISPLAYS,
)

ACTION_DISPLAY_REGISTRY = {
    definition.action_type: definition for definition in REGISTERED_ACTION_DISPLAYS
}

if len(ACTION_DISPLAY_REGISTRY) != len(REGISTERED_ACTION_DISPLAYS):
    raise RuntimeError("Duplicate AI-report proposal display action registration")


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_display_registry_covers_action_contracts
# @pair ai-report:display-registry
# @pair ai-report:action-contracts
def proposal_action_display(action_type):
    """Return registered behavior or a conservative unknown-action fallback."""

    return ACTION_DISPLAY_REGISTRY.get(
        action_type,
        ProposalActionDisplay(action_type or "", ""),
    )
