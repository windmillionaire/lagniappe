"""User selection and dependency-aware skip projection for proposals."""

from lagniappe.core import exceptions

from .references import _referenced_action_ids
from .validation import validate_proposal


# @testable true
# @tests tests_unit/test_020e_ai_report_proposals.py::test_skip_proposal_actions_marks_dependencies
# @matrix ai-report : dependencies proposal skip
def skip_proposal_actions(proposal, index):
    """Mark one proposal action and all dependent actions as skipped."""
    proposal = validate_proposal(proposal)
    actions = proposal.get("actions") or []
    if index < 0 or index >= len(actions):
        raise exceptions.ValidationError("Action not found.")

    skipped_indexes = _dependent_action_indexes(actions, index)
    for action_index in skipped_indexes:
        actions[action_index]["skip"] = True

    return sorted(action_index + 1 for action_index in skipped_indexes)


# @testable true
# @tests tests_unit/test_020e_ai_report_proposals.py::test_toggle_proposal_action_skip_restores_dependencies
# @matrix ai-report : dependencies proposal restore skip
def toggle_proposal_action_skip(proposal, index):
    """Toggle skipped state for an action and its dependent actions."""
    proposal = validate_proposal(proposal)
    actions = proposal.get("actions") or []
    if index < 0 or index >= len(actions):
        raise exceptions.ValidationError("Action not found.")

    changed_indexes = _dependent_action_indexes(actions, index)
    return _set_proposal_action_skip(actions, index, changed_indexes)


# @testable true
# @tests tests_unit/test_020e_ai_report_proposals.py::test_toggle_proposal_action_skip_restores_dependencies
# @tests tests_unit/test_020g_ai_report_actions_entities.py::test_toggle_proposal_action_indexes_can_skip_exact_indexes_without_dependencies
# @matrix ai-report : dependencies exact-indexes grouped-display proposal restore schema-section skip
def toggle_proposal_action_indexes(proposal, index, indexes, include_dependencies=True):
    """Toggle skipped state for a display group of proposal actions."""
    proposal = validate_proposal(proposal)
    actions = proposal.get("actions") or []
    if index < 0 or index >= len(actions):
        raise exceptions.ValidationError("Action not found.")

    changed_indexes = set()
    for action_index in indexes or []:
        if action_index < 0 or action_index >= len(actions):
            raise exceptions.ValidationError("Action not found.")
        if include_dependencies:
            changed_indexes.update(_dependent_action_indexes(actions, action_index))
        else:
            changed_indexes.add(action_index)

    if include_dependencies:
        changed_indexes.update(_dependent_action_indexes(actions, index))
    else:
        changed_indexes.add(index)
    return _set_proposal_action_skip(actions, index, changed_indexes)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/selection.py::toggle_proposal_action_skip
# @covered-by lagniappe/core/tools/ai/reporting/proposals/selection.py::toggle_proposal_action_indexes
# @reason shared skip state mutation is verified through public toggle helpers
def _set_proposal_action_skip(actions, index, changed_indexes):
    skip = actions[index].get("skip") is not True
    for action_index in changed_indexes:
        if skip:
            actions[action_index]["skip"] = True
        else:
            actions[action_index].pop("skip", None)

    return {
        "changed": sorted(action_index + 1 for action_index in changed_indexes),
        "skipped": [
            action_index + 1
            for action_index, action in enumerate(actions)
            if action.get("skip") is True
        ],
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/proposals/selection.py::skip_proposal_actions
# @covered-by lagniappe/core/tools/ai/reporting/proposals/selection.py::toggle_proposal_action_skip
# @reason dependency walk is verified through public proposal mutation helpers
def _dependent_action_indexes(actions, index):
    skipped_ids = set()
    skipped_indexes = {index}
    action = actions[index]
    if action.get("id"):
        skipped_ids.add(action["id"])

    changed = True
    while changed:
        changed = False
        for action_index, action in enumerate(actions):
            if action_index in skipped_indexes:
                continue
            dependencies = set(_referenced_action_ids(action))
            if dependencies.intersection(skipped_ids):
                skipped_indexes.add(action_index)
                if action.get("id"):
                    skipped_ids.add(action["id"])
                changed = True

    return skipped_indexes
