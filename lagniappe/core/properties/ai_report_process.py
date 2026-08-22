"""Process-backed AI report state and transitions."""

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

# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_process_state_stores_report_metadata
# @features ai-report
# @dimensions process-state canonical-storage
class ReportProcess(ProcessProperty):
    """Process section containing an AI report's workflow state."""

    process_id = "process"
    section_id = "report"
    attributes = _REPORT_PROCESS_KEYS

    def revise(self):
        self.status = "revising"
        self.pending = True
        self.summary = None
        self.error = None

    def fail(self, message, result=None):
        self.status = "failed"
        self.pending = None
        self.error = message
        if result is not None:
            self.result = result

    def revision_failed(self, message):
        proposal = self.proposal if isinstance(self.proposal, dict) else {}
        actions = proposal.get("actions") or []
        self.status = (
            "complete"
            if self.entity.tool == "ask" and not actions
            else "ready"
        )
        self.pending = None
        self.error = message
        self.summary = proposal.get("summary")
        self.result = None

    def retry(self, message, result=None):
        self.status = "pending"
        self.pending = True
        self.error = message
        if result is not None:
            self.result = result

    def set_proposal(self, proposal, status="ready"):
        self.proposal = proposal
        self.summary = proposal.get("summary") if isinstance(proposal, dict) else None
        self.status = status
        self.pending = None
        self.error = None
        self.result = None

    def begin_execution(self, result=None):
        """Publish the canonical state for a running report execution."""
        self.status = "running"
        self.pending = True
        self.error = None
        if result is not None:
            self.result = result

    def complete_execution(self, result):
        """Publish a successfully completed execution ledger."""
        self.status = "complete"
        self.pending = None
        self.error = None
        self.result = result

    def restore_after_execution_failure(self, message, previous_status=None):
        """Restore a queued execution that failed before creating a ledger."""
        self.status = "failed" if previous_status == "failed" else "ready"
        self.pending = None
        self.error = message

    def begin_undo(self, result):
        """Publish the canonical state for compensation in progress."""
        self.status = "undoing"
        self.pending = True
        self.error = None
        self.result = result

    def fail_undo(self, message, result):
        """Publish a failed compensation attempt without discarding its ledger."""
        self.status = "undo_failed"
        self.pending = None
        self.error = message
        self.result = result

    def complete_undo(self, result):
        """Return a compensated report to its ready state."""
        self.status = "ready"
        self.pending = None
        self.error = None
        self.result = result


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason thin process-backed value adapter exercised through report process state
class ReportProcessValue(Property):
    """Entity property facade for one report process attribute."""

    _blank_values = (None, [], {})

    @property
    def process_attribute(self):
        return getattr(self, "_process_attribute", self.id)

    @property
    def process(self):
        return self.entity.properties.process

    def _clear_cached_entity_views(self):
        if hasattr(self.entity, "_details"):
            self.entity._details = None
        if hasattr(self.entity, "_to_cache"):
            self.entity._to_cache = None

    @property
    def value(self):
        return getattr(self.process, self.process_attribute)

    @value.setter
    def value(self, value):
        if value in self._blank_values:
            value = None
        setattr(self.process, self.process_attribute, value)
        self._clear_cached_entity_views()


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Status(ReportProcessValue):
    """Current AI report processing status."""

    _id = "status"


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason active deferred-job metadata is exercised through report process state
class DeferredJob(ReportProcessValue):
    """Reference metadata for the report's currently active background job."""

    _id = "deferred_job"


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Summary(ReportProcessValue):
    """Short user-facing AI report summary."""

    _id = "summary"




# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason process-backed field adapter has no behavior beyond ReportProcessValue
class Error(ReportProcessValue):
    """User-facing AI report error message."""

    _id = "error"


# @testable false
# @covered-by lagniappe/core/properties/ai_report_process.py::ReportProcess
# @reason bool coercion is exercised through report process state
class Pending(ReportProcessValue):
    """Whether an AI report still represents work in progress."""

    _id = "pending"
    _truthy = {True, "true", "True", "1", 1, "on", "yes"}

    @property
    def value(self):
        return getattr(self.process, self.process_attribute) in self._truthy

    @value.setter
    def value(self, value):
        pending = value in self._truthy
        setattr(self.process, self.process_attribute, True if pending else None)
        self.entity.db.pop(self.id, None)
        self._clear_cached_entity_views()


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_create_and_file_cleanup
# @features ai-report
# @dimensions status
class Note(Property):
    """User-facing note derived from the report process state."""

    _id = "note"

    @property
    def value(self):
        if self.entity.error:
            return self.entity.error
        if self.entity.summary:
            return self.entity.summary
        pending = {
            "ask": "Thinking...",
            "create": "Planning creation...",
        }.get(self.entity.tool, "Analyzing files...")
        labels = {
            "pending": pending,
            "revising": "Revising report...",
            "ready": "Ready to run",
            "running": "Running report...",
            "complete": "Report complete",
            "failed": "Report failed",
        }
        return labels.get(self.entity.status, "Report created")
