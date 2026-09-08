from ..mixins import RelatedEntityMixin
from .base_db import DBProperty


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_file_move_preserves_single_ownership
# @matrix files : ownership cardinality parent-key
class AttachedPage(RelatedEntityMixin, DBProperty):
    """The single Page owning this File."""

    _id = "page"
    _kind = "page"
    _label = "Page"
    _icon = "page"
    other = "task"

    @property
    def value(self):
        return RelatedEntityMixin.value.fget(self)

    @value.setter
    def value(self, value):
        if value is not None:
            if getattr(value, "entity_kind", None) != self._kind:
                raise ValueError(f"File {self.id} must be a live {self._kind}")
            if self.entity.db.get(self.other):
                raise ValueError("A File cannot belong to both a Page and a Task")
        RelatedEntityMixin.value.fset(self, value)
        self.entity.properties.requires.unset()
        self.entity.properties.restricted_to.unset()


# @testable false
# @covered-by lagniappe/core/properties/file_related.py::AttachedPage
class AttachedTask(AttachedPage):
    """The single live Task owning this File; histories are references only."""

    _id = "task"
    _kind = "task"
    _label = "Task"
    _icon = "task"
    other = "page"


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_report_file_is_viewable_only_by_submitter_or_owner
# @matrix ai-email files : temporary-view-ownership
class ReportUser(RelatedEntityMixin, DBProperty):
    """Submitting user temporarily allowed to view a report-only email file."""

    _id = "report_user"
    _kind = "user"
