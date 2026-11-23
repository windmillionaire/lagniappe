from typing import TYPE_CHECKING, cast

from ..mixins import RelatedEntityMixin
from ..tools.auth.restrictions import permission_relation
from .base_db import DBProperty

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.file import File
    from ..entities.page import Page
    from ..entities.task import Task
    from ..entities.user import User


type _File = File
type _Page = Page
type _Task = Task
type _User = User


class AttachedEntity[T: Entity](RelatedEntityMixin[T], DBProperty[T, _File, T | None]):
    """Typed File links invalidate the permissions derived from their owner."""

    @property
    def value(self) -> T | None:
        return self._read_related()

    @value.setter
    def value(self, value: T | None) -> None:
        self._set_attached(value)

    def _set_attached(self, value: T | None) -> None:
        if value is not None and getattr(value, "entity_kind", None) != self._kind:
            raise ValueError(f"File {self.id} must be a live {self._kind}")
        self._write_related(value)
        self.entity.properties.requires.unset()
        self.entity.properties.restricted_to.unset()


class AttachedPage(AttachedEntity[_Page]):
    """The direct Page owning this File."""

    _id = "page"
    _kind = "page"
    _label = "Page"
    _icon = "page"

    def _set_attached(self, value: Page | None) -> None:
        super()._set_attached(value)
        if value is not None:
            self.entity.task = None
            self.entity.task_page = None


class AttachedTask(AttachedEntity[_Task]):
    """The single live Task owning this File; histories are references only."""

    _id = "task"
    _kind = "task"
    _label = "Task"
    _icon = "task"

    def _set_attached(self, value: Task | None) -> None:
        super()._set_attached(value)
        if value is not None:
            self.entity.page = None
            self.entity.task_page = cast("Page", permission_relation(value, "page", required=True))
        else:
            self.entity.task_page = None


class TaskPage(AttachedEntity[_Page]):
    """The primary Task's Page, persisted for nested relationship loading."""

    _id = "task_page"
    _kind = "page"
    _label = "Page"
    _icon = "page"


class ReportUser(RelatedEntityMixin[_User], DBProperty[_User, _File]):
    """Uploading user temporarily allowed to view an unattached File."""

    _id = "report_user"
    _kind = "user"
