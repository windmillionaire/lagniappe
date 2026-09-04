"""Atomic browser-side mutations for externally authored Plans."""

from copy import deepcopy

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    MutationEffectType,
    MutationOperation,
    MutationPhase,
)
from lagniappe.core.mutations import (
    consume_mutation_intents,
    execute_post_commit,
    plan_mutation,
    prepare_durable_writes,
)
from lagniappe.core.tools.database import agent_api as agent_api_store


# @testable false
# @covered-by lagniappe/core/tools/ai/external_operations.py::save_plan_if_idle
# @covered-by lagniappe/core/tools/ai/external_operations.py::delete_plan_if_idle
# @reason exact raw snapshots are asserted by both public guarded mutations
def report_snapshot(report):
    """Capture the raw Report revision before an in-memory mutation begins."""
    return deepcopy(dict(report.db))


# @testable false
# @covered-by lagniappe/core/tools/ai/external_operations.py::save_plan_if_idle
# @covered-by lagniappe/core/tools/ai/external_operations.py::delete_plan_if_idle
# @reason shared mutation execution is exercised through save and delete races
def _commit_plan_if_idle(report, expected_report, plan):
    writes = prepare_durable_writes(plan)
    deletes = [
        effect.entity
        for effect in plan.effects
        if effect.phase is MutationPhase.DURABLE
        and effect.effect is MutationEffectType.DELETE
    ]
    outcome = agent_api_store.commit_plan_mutation_if_idle(
        report.key,
        expected_report=expected_report,
        writes=[(effect.entity, effect.property_mask) for effect in writes],
        deletes=deletes,
    )
    if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
        return outcome

    consume_mutation_intents(plan)
    try:
        execute_post_commit(plan)
    except Exception as error:
        # Durable state already committed. Rebuildable cache/blob effects use
        # the same failure isolation as ordinary entity mutation execution.
        exceptions.capture(
            error,
            context={
                "agent_api": {
                    "phase": "browser_plan_mutation_post_commit",
                    "report_key": getattr(report, "urlsafe_key", None),
                }
            },
        )
    return outcome


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_browser_plan_save_and_delete_use_idle_transaction
# @matrix agent-api ai-report : browser-review cas save
def save_plan_if_idle(report, expected_report, *entities):
    """Save a browser change without racing an external API Plan operation."""
    plan = plan_mutation(
        MutationOperation.SAVE,
        *(entities or (report,)),
    )
    return _commit_plan_if_idle(report, expected_report, plan)


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_external_browser_plan_save_and_delete_use_idle_transaction
# @matrix agent-api ai-report : browser-review cas delete file-cleanup
def delete_plan_if_idle(report, expected_report, *entities):
    """Delete a Plan and owned files only if its reviewed revision is current."""
    plan = plan_mutation(
        MutationOperation.DELETE,
        *(entities or (report,)),
    )
    return _commit_plan_if_idle(report, expected_report, plan)


__all__ = [
    "delete_plan_if_idle",
    "report_snapshot",
    "save_plan_if_idle",
]
