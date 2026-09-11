from ..mixins import RelatedEntityMixin
from ..tools.auth.restrictions import permission_relation
from .base_db import DBProperty


# @testable infrastructure
# @covered-by lagniappe/core/properties/file_related.py::AttachedPage
class AttachedEntity(RelatedEntityMixin, DBProperty):
    """Typed File links invalidate the permissions derived from their owner."""

    @property
    def value(self):
        return RelatedEntityMixin.value.fget(self)

    @value.setter
    def value(self, value):
        if value is not None:
            if getattr(value, "entity_kind", None) != self._kind:
                raise ValueError(f"File {self.id} must be a live {self._kind}")
        RelatedEntityMixin.value.fset(self, value)
        self.entity.properties.requires.unset()
        self.entity.properties.restricted_to.unset()


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_file_move_preserves_single_ownership
# @matrix files : ownership cardinality parent-key
class AttachedPage(AttachedEntity):
    """The direct Page owning this File."""

    _id = "page"
    _kind = "page"
    _label = "Page"
    _icon = "page"

    @AttachedEntity.value.setter
    def value(self, value):
        AttachedEntity.value.fset(self, value)
        if value is not None:
            self.entity.task = None
            self.entity.task_page = None


# @testable false
# @covered-by lagniappe/core/properties/file_related.py::AttachedPage
class AttachedTask(AttachedEntity):
    """The single live Task owning this File; histories are references only."""

    _id = "task"
    _kind = "task"
    _label = "Task"
    _icon = "task"

    @AttachedEntity.value.setter
    def value(self, value):
        AttachedEntity.value.fset(self, value)
        if value is not None:
            self.entity.page = None
            self.entity.task_page = permission_relation(value, "page", required=True)
        else:
            self.entity.task_page = None


# @testable false
# @covered-by lagniappe/core/properties/file_related.py::AttachedPage
class TaskPage(AttachedEntity):
    """The primary Task's Page, persisted for nested relationship loading."""

    _id = "task_page"
    _kind = "page"
    _label = "Page"
    _icon = "page"


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_email_report_file_is_viewable_only_by_submitter_or_owner
# @matrix ai-email files : temporary-view-ownership
class ReportUser(RelatedEntityMixin, DBProperty):
    """Uploading user temporarily allowed to view an unattached File."""

    _id = "report_user"
    _kind = "user"
