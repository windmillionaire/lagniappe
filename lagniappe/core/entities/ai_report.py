from .entity import Entity
from ..definitions import Action
from ..properties import activity, ai_report as report_properties
from ..tools.user_context import current_context_user


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_ai_report_create_and_file_cleanup
# @features ai-report
# @dimensions create files status delete
class AIReport(Entity):
    """AI-generated report containing an ordered, deterministic action proposal."""

    entity_kind = "report"

    @property
    def exclude_from_index(self):
        return frozenset(
            {
                "instructions",
                "upload_manifest",
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
                "upload_manifest": report_properties.UploadManifest,
                "process": report_properties.ReportProcess,
                "status": report_properties.Status,
                "deferred_job": report_properties.DeferredJob,
                "summary": report_properties.Summary,
                "proposal": report_properties.Proposal,
                "result": report_properties.Result,
                "error": report_properties.Error,
                "pending": report_properties.Pending,
                "note": report_properties.Note,
            }
        )
        return properties

    @property
    def required(self):
        return [self.parent.hash]

    # @testable true
    # @tests tests_unit/test_020_ai_reports.py::test_ai_report_permissions_follow_creator_ownership
    # @features ai-report permissions
    # @dimensions creator owner unrelated-user delete view
    def allowed(self, action, user=None):
        user = current_context_user(user)
        if not user or not user.is_authenticated:
            return False

        if user.is_owner:
            return True

        creator_key = self.properties.user.key
        if creator_key and creator_key == user.key:
            return Action.DELETE.implies(action)

        return False

    @classmethod
    def create(cls, data):
        parent = data.get("parent") or data.get("user")
        user = data.get("user") or parent

        report = cls(parent=parent)
        report.kind = cls.entity_kind
        report.parent = parent
        report.user = user
        report.name = data.get("name") or "Organize report"
        report.tool = data.get("tool") or "organize"
        report.instructions = data.get("instructions")
        report.input_files = data.get("input_files", [])
        report.upload_manifest = data.get("upload_manifest")
        report.status = data.get("status") or "pending"
        report.summary = data.get("summary")
        report.proposal = data.get("proposal")
        report.result = data.get("result")
        report.error = data.get("error")
        report.deferred_job = data.get("deferred_job")
        report.pending = data.get("pending", report.status in {"pending", "running"})
        return report
