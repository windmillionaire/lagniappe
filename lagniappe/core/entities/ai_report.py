from .entity import Entity
from ..definitions import Action
from ..properties import activity
from ..properties import ai_report_input
from ..properties import ai_report_process
from ..properties import ai_report_proposal
from ..properties import ai_report_result
from ..tools.auth.context import current_context_user

REPORT_FORMAT_VERSION = 2
UNAVAILABLE_PLAN_MESSAGE = "this plan is no longer available"


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_create_and_file_cleanup
# @tests tests_unit/test_032_agent_api.py::test_api_report_draft_preserves_agent_manifest
# @matrix ai-report : create delete files status
# @pair agent-api:report-session
class AIReport(Entity):
    """AI-generated report containing an ordered, deterministic action proposal."""

    entity_kind = "report"

    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "instructions",
                "upload_manifest",
                "agent_manifest",
                "inbound_manifest",
                "file_usage",
                "process",
                "proposal",
                "result",
                "error",
                "deferred_job",
                "correction",
            }
        )

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "parent": activity.AttachedParent,
                "user": activity.AttachedUser,
                "format_version": ai_report_input.FormatVersion,
                "file_usage": ai_report_input.FileUsage,
                "instructions": activity.Instructions,
                "input_files": activity.InputFiles,
                "upload_manifest": ai_report_input.UploadManifest,
                "agent_manifest": ai_report_input.AgentManifest,
                "origin": ai_report_input.Origin,
                "inbound_manifest": ai_report_input.InboundManifest,
                "process": ai_report_process.ReportProcess,
                "status": ai_report_process.Status,
                "deferred_job": ai_report_process.DeferredJob,
                "summary": ai_report_process.Summary,
                "proposal": ai_report_proposal.Proposal,
                "result": ai_report_result.Result,
                "error": ai_report_process.Error,
                "pending": ai_report_process.Pending,
                "note": ai_report_process.Note,
            }
        )
        return properties

    # @testable true
    # @tests tests_unit/test_020b_ai_planner.py::test_report_availability_rejects_old_and_malformed_records
    # @matrix ai-report : validation status unavailable
    @property
    def available(self):
        if self.format_version != REPORT_FORMAT_VERSION:
            return False
        try:
            process = self.properties.process.section
            if not isinstance(process, dict) or not isinstance(self.status, str):
                return False
            proposal = self.proposal
            if proposal is not None and (
                not isinstance(proposal, dict)
                or not isinstance(proposal.get("actions"), list)
                or not isinstance(proposal.get("summary"), str)
                or any(
                    not isinstance(action, dict)
                    or not isinstance(action.get("type"), str)
                    or not isinstance(action.get("data"), dict)
                    for action in proposal["actions"]
                )
            ):
                return False
            result = self.result
            if result is not None and (
                not isinstance(result, dict)
                or not isinstance(result.get("actions", []), list)
                or any(
                    not isinstance(action, dict) for action in result.get("actions", [])
                )
            ):
                return False
            return isinstance(self.file_usage or [], list) and isinstance(
                self.deferred_job or {}, dict
            )
        except (ValueError, TypeError, AttributeError, KeyError):
            return False

    # @testable false
    # @covered-by lagniappe/core/entities/ai_report.py::AIReport.available
    # @reason output classification uses only supported report data
    @property
    def output_kind(self):
        if not self.available or not self.proposal:
            return None
        return "proposal" if self.proposal["actions"] else "answer"

    @property
    def required(self):
        return [self.parent.hash]

    # @testable true
    # @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_permissions_follow_creator_ownership
    # @matrix ai-report permissions : creator delete owner unrelated-user view
    def allowed(self, action, user=None):
        user = current_context_user(user)
        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_admin", False) or getattr(user, "is_owner", False):
            return True

        creator_key = self.properties.user.key
        if creator_key and creator_key == user.key:
            return Action.DELETE.implies(action)

        return False

    @classmethod
    def create(cls, data, *, key=None):
        parent = data.get("parent") or data.get("user")
        user = data.get("user") or parent

        report = cls(key) if key is not None else cls(parent=parent)
        report.kind = cls.entity_kind
        report.parent = parent
        report.user = user
        report.name = data.get("name") or "AI report"
        report.format_version = REPORT_FORMAT_VERSION
        report.file_usage = data.get("file_usage")
        report.instructions = data.get("instructions")
        report.input_files = data.get("input_files", [])
        report.upload_manifest = data.get("upload_manifest")
        report.agent_manifest = data.get("agent_manifest")
        report.origin = data.get("origin") or "web"
        report.inbound_manifest = data.get("inbound_manifest")
        report.status = data.get("status") or "pending"
        report.summary = data.get("summary")
        report.proposal = data.get("proposal")
        report.result = data.get("result")
        report.error = data.get("error")
        report.deferred_job = data.get("deferred_job")
        report.pending = data.get("pending", report.status in {"pending", "running"})
        return report
