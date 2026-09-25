"""Claimed API and atomic browser mutations for externally authored Plans."""

from contextlib import suppress
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
from .reporting.uploads import CHECKPOINT_AMBIGUOUS, CHECKPOINT_NOT_COMMITTED


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
def _commit_plan_if_idle(report, expected_report, plan, *, active_job=None):
    writes = prepare_durable_writes(plan)
    deletes = [
        effect.entity
        for effect in plan.effects
        if effect.phase is MutationPhase.DURABLE
        and effect.effect is MutationEffectType.DELETE
    ]
    guard = {"active_job": active_job} if active_job is not None else {}
    outcome = agent_api_store.commit_plan_mutation_if_idle(
        report.key,
        expected_report=expected_report,
        writes=[(effect.entity, effect.property_mask) for effect in writes],
        deletes=deletes,
        **guard,
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
def save_plan_if_idle(report, expected_report, *entities, active_job=None):
    """Save a browser change without racing an external API Plan operation."""
    plan = plan_mutation(
        MutationOperation.SAVE,
        *(entities or (report,)),
    )
    return _commit_plan_if_idle(report, expected_report, plan, active_job=active_job)


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


# @testable infrastructure
class ExternalPlanError(Exception):
    """A safe domain failure translated to HTTP only at the REST boundary."""

    def __init__(self, reason, message, *, details=None):
        super().__init__(message)
        self.reason = reason
        self.details = details


# @testable false
# @covered-by lagniappe/core/tools/ai/external/uploads.py::create_upload_sessions
# @covered-by lagniappe/core/tools/ai/external/uploads.py::finalize_upload_batch
# @reason claim outcomes are exercised through both public upload routes
def raise_plan_operation_error(outcome):
    """Map a transactional Plan-operation outcome to a bounded API conflict."""
    if outcome == agent_api_store.PLAN_OPERATION_PENDING:
        raise ExternalPlanError(
            "uploads_pending",
            "Finalize the current upload batch before starting another.",
        )
    if outcome == agent_api_store.PLAN_OPERATION_BUSY:
        raise ExternalPlanError(
            "plan_operation_in_progress",
            "Another request is already changing this Plan.",
        )
    if outcome == agent_api_store.PLAN_OPERATION_MISMATCH:
        raise ExternalPlanError(
            "upload_batch_mismatch",
            "This upload batch is no longer current for the Plan.",
        )
    if outcome == agent_api_store.PLAN_OPERATION_MISSING:
        raise ExternalPlanError("plan_not_found", "Plan not found.")
    raise ExternalPlanError(
        "invalid_upload_state",
        "The current upload batch state is invalid.",
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/external/uploads.py::create_upload_sessions
# @covered-by lagniappe/core/tools/ai/external/uploads.py::finalize_upload_batch
# @reason expiry provides recovery when best-effort cleanup itself is unavailable
def release_plan_operation_claim(
    report,
    *,
    phase,
    operation_id,
    claim_token,
):
    """Best-effort release; a crashed cleanup remains bounded by the lease."""
    with suppress(Exception):
        agent_api_store.release_plan_operation(
            report.key,
            phase=phase,
            operation_id=operation_id,
            claim_token=claim_token,
        )


# @testable true
# @tests tests_unit/test_032i_external_contracts.py::test_claimed_save_preserves_definite_and_ambiguous_checkpoint_failures
# @tests tests_unit/test_032i_external_contracts.py::test_claimed_save_advances_snapshot_and_isolates_post_commit_failure
# @matrix agent-api : checkpoint concurrency
def claimed_plan_save(report, *, phase, operation_id, claim_token, user, request_id):
    """Return a mutation writer fenced by one exact Plan-operation claim."""
    expected_report = deepcopy(dict(report.db))

    # @testable false
    # @covered-by lagniappe/core/tools/ai/external_operations.py::claimed_plan_save
    # @reason the closure delegates each checkpoint to the service-owned claim writer
    def save(*entities):
        nonlocal expected_report
        try:
            plan = plan_mutation(MutationOperation.SAVE, *entities)
            writes = prepare_durable_writes(plan)
        except BaseException as error:
            error.checkpoint_disposition = CHECKPOINT_NOT_COMMITTED
            raise
        try:
            outcome = agent_api_store.commit_plan_operation(
                report.key,
                phase=phase,
                operation_id=operation_id,
                claim_token=claim_token,
                expected_report=expected_report,
                writes=[(effect.entity, effect.property_mask) for effect in writes],
                notification_user=user if phase == "submit" else None,
            )
        except BaseException as error:
            error.checkpoint_disposition = CHECKPOINT_AMBIGUOUS
            raise
        if outcome != agent_api_store.PLAN_OPERATION_COMMITTED:
            if outcome == agent_api_store.PLAN_OPERATION_LOST:
                problem = ExternalPlanError(
                    "plan_operation_lost",
                    "This request no longer owns the Plan operation.",
                )
            elif outcome == agent_api_store.PLAN_OPERATION_STALE:
                problem = ExternalPlanError(
                    "plan_state_conflict",
                    "The Plan changed while this operation was in progress.",
                )
            else:
                try:
                    raise_plan_operation_error(outcome)
                except ExternalPlanError as error:
                    problem = error
            problem.checkpoint_disposition = CHECKPOINT_NOT_COMMITTED
            raise problem

        expected_report = deepcopy(dict(report.db))
        consume_mutation_intents(plan)
        try:
            execute_post_commit(plan)
        except Exception as error:
            exceptions.capture(
                error,
                context={
                    "agent_api": {
                        "request_id": request_id,
                        "phase": f"{phase}_post_commit",
                    }
                },
            )

    return save


__all__ = [
    "ExternalPlanError",
    "claimed_plan_save",
    "delete_plan_if_idle",
    "raise_plan_operation_error",
    "release_plan_operation_claim",
    "report_snapshot",
    "save_plan_if_idle",
]
