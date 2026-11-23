"""Process-backed AI report state and transitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.ai_report import AIReport
    from lagniappe.core.tools.ai.reporting.contracts.actions import ReportProposal
    from lagniappe.core.tools.ai.reporting.execution.ledger import ReportLedger


from .base_process import ProcessProperty
from .base_property import Property

_REPORT_PROCESS_KEYS = (
    "status",
    "pending",
    "summary",
    "proposal",
    "result",
    "error",
    "deferred_job",
)

type _Report = AIReport


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_process_state_stores_report_metadata
# @matrix ai-report : canonical-storage process-state
class ReportProcess(ProcessProperty[_Report]):
    """Process section containing an AI report's workflow state."""

    process_id = "process"
    section_id = "report"
    attributes = _REPORT_PROCESS_KEYS

    def revise(self) -> None:
        self.status = "revising"
        self.pending = True
        self.summary = None
        self.error = None

    def fail(self, message: str, result: ReportLedger | dict[str, object] | None = None) -> None:
        self.status = "failed"
        self.pending = None
        self.error = message
        if result is not None:
            self.result = result

    def revision_failed(self, message: str) -> None:
        proposal = self.proposal if isinstance(self.proposal, dict) else {}
        actions = proposal.get("actions") or []
        self.status = (
            "complete"
            if not actions
            else "ready"
        )
        self.pending = None
        self.error = message
        self.summary = proposal.get("summary")
        self.result = None

    def retry(self, message: str, result: ReportLedger | dict[str, object] | None = None) -> None:
        self.status = "pending"
        self.pending = True
        self.error = message
        if result is not None:
            self.result = result

    def set_proposal(self, proposal: ReportProposal | dict[str, object]) -> None:
        self.proposal = proposal
        self.summary = proposal.get("summary") if isinstance(proposal, dict) else None
        self.status = "ready" if proposal.get("actions") else "complete"
        self.pending = None
        self.error = None
        self.result = None

    def begin_execution(self, result: ReportLedger | dict[str, object] | None = None) -> None:
        """Publish the canonical state for a running report execution."""
        self.status = "running"
        self.pending = True
        self.error = None
        if result is not None:
            self.result = result

    def complete_execution(self, result: ReportLedger | dict[str, object]) -> None:
        """Publish a successfully completed execution ledger."""
        self.status = "complete"
        self.pending = None
        self.error = None
        self.result = result

    def restore_after_execution_failure(self, message: str, previous_status: str | None = None) -> None:
        """Restore a queued execution that failed before creating a ledger."""
        self.status = "failed" if previous_status == "failed" else "ready"
        self.pending = None
        self.error = message


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason thin process-backed value adapter exercised through report process state
class ReportProcessValue[V = object](Property[V, _Report, V | None]):
    """Entity property facade for one report process attribute."""

    _blank_values = (None, [], {})

    @property
    def process_attribute(self) -> str:
        return getattr(self, "_process_attribute", self.id)

    @property
    def process(self) -> ReportProcess:
        return self.entity.properties.process

    def _clear_cached_entity_views(self) -> None:
        if hasattr(self.entity, "_details"):
            self.entity._details = None
        if hasattr(self.entity, "_to_cache"):
            self.entity._to_cache = None

    @property
    def value(self) -> V | None:
        return getattr(self.process, self.process_attribute)

    @value.setter
    def value(self, value: V | None) -> None:
        if value in self._blank_values:
            value = None
        setattr(self.process, self.process_attribute, value)
        self._clear_cached_entity_views()


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Status(ReportProcessValue[str]):
    """Current AI report processing status."""

    _id = "status"


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason active deferred-job metadata is exercised through report process state
class DeferredJob(ReportProcessValue[dict[str, object]]):
    """Reference metadata for the report's currently active background job."""

    _id = "deferred_job"


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Summary(ReportProcessValue[str]):
    """Short user-facing AI report summary."""

    _id = "summary"


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Error(ReportProcessValue[str]):
    """User-facing AI report error message."""

    _id = "error"


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason bool coercion is exercised through report process state
class Pending(ReportProcessValue[bool]):
    """Whether an AI report still represents work in progress."""

    _id = "pending"
    _truthy = {True, "true", "True", "1", "on", "yes"}

    @property
    def value(self) -> bool:
        return getattr(self.process, self.process_attribute) in self._truthy

    @value.setter
    def value(self, value: object) -> None:
        pending = value in self._truthy
        setattr(self.process, self.process_attribute, True if pending else None)
        self.entity.db.pop(self.id, None)
        self._clear_cached_entity_views()


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_create_and_file_cleanup
# @tests tests_unit/test_032_agent_api.py::test_api_report_draft_preserves_agent_manifest
# @pair ai-report:status
# @pair agent-api:status
class Note(Property[str, _Report]):
    """User-facing note derived from the report process state."""

    _id = "note"

    @property
    def value(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- The report note is computed and read-only.
        if not self.entity.available:
            from ..entities.ai_report import UNAVAILABLE_PLAN_MESSAGE
            return UNAVAILABLE_PLAN_MESSAGE
        if self.entity.error:
            return self.entity.error
        if self.entity.summary:
            return self.entity.summary
        labels = {
            "draft": "Waiting for external plan",
            "pending": "Thinking...",
            "revising": "Revising report...",
            "ready": "Ready to run",
            "running": "Running report...",
            "complete": "Report complete",
            "failed": "Report failed",
        }
        return labels.get(self.entity.status or "", "Report created")
