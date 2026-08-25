from .entity import Entity
from ..definitions import Action
from ..properties import activity
from ..properties import ai_report_input
from ..properties import ai_report_process
from ..properties import ai_report_proposal
from ..properties import ai_report_result
from ..tools.auth.context import current_context_user


# @testable true
# @tests tests_unit/test_020a_ai_report_properties.py::test_ai_report_create_and_file_cleanup
# @matrix ai-report : create delete files status
class AIReport(Entity):
    """AI-generated report containing an ordered, deterministic action proposal."""

    entity_kind = "report"

    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "instructions",
                "upload_manifest",
                "inbound_manifest",
                "process",
                "proposal",
                "result",
                "error",
                "deferred_job",
            }
        )

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "parent": activity.AttachedParent,
                "user": activity.AttachedUser,
                "tool": activity.Tool,
                "instructions": activity.Instructions,
                "input_files": activity.InputFiles,
                "upload_manifest": ai_report_input.UploadManifest,
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
        report.name = data.get("name") or "Organize report"
        report.tool = data.get("tool") or "organize"
        report.instructions = data.get("instructions")
        report.input_files = data.get("input_files", [])
        report.upload_manifest = data.get("upload_manifest")
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
