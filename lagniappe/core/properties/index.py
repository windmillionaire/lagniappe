from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.site import Site
    from ..entities.history import TaskHistory
    from ..entities.task import Task

from .base_property import build_field
from .base_columns import Columns
from .common_entity import Description, Modified, Name
from .common_related import Categories, Projects
from .form import FormType
from .task_related import AssignedTo, CompletedBy, TaskFiles, TaskStatus
from .task_dates import Completed, CompletedOn, DueDate
from .user_related import Groups
from .user_entity import Email, LastLogin
from ..mixins import ColumnMixin


class TaskTable(Columns["Entity | Site"]):
    _id = "table"
    _kind = "task"

    def __init__(self, *args: object, entity: Entity | Site | None = None, **kwargs: object) -> None:
        self.column_fields = [
            Completed,
            Name,
            TaskStatus,
            Description,
            DueDate,
            AssignedTo,
            Modified,
        ]
        self.default_selected = (Name, DueDate, Modified)
        super().__init__(*args, entity=entity, **kwargs)

        for field in self.fields.values():
            if isinstance(field, self.default_selected):
                field.selected = True


class TaskHistoryTable(Columns["Task | TaskHistory"]):
    _id = "table"
    _kind = "task"
    _embedded = True
    default_selected = (CompletedOn, Name, Description)

    def __init__(self, *args: object, entity: Task | TaskHistory | None = None, **kwargs: object) -> None:
        self.column_fields = [
            CompletedOn,
            Name,
            Description,
            CompletedBy,
            TaskFiles,
        ]
        super().__init__(*args, entity=entity, **kwargs)

    @property
    def fields(self) -> dict[str, ColumnMixin]:
        if cached := getattr(self, "_fields", None):
            return cached

        fields: dict[str, ColumnMixin] = {}
        for f in self.column_fields:
            field = build_field(f, self.entity)
            fields[field.id] = field

        definition = getattr(self.entity, "submission_definition", None)
        form = definition.source if definition is not None else self.entity.form
        if form and not form.db.get("pending_form_change"):
            fields.update(
                {
                    f.id: f
                    for f in form.fields.values()
                    if isinstance(f, ColumnMixin)
                }
            )

        for field in fields.values():
            field.selected = isinstance(field, self.default_selected)
            if isinstance(field, Name):
                field.link = False
                field.parent = False

        self._fields = fields
        return self._fields


class FormTable(Columns["Entity | Site"]):
    _id = "table"
    _kind = "form"

    def __init__(self, *args: object, entity: Entity | Site | None = None, **kwargs: object) -> None:
        self.column_fields = [Name, FormType, Categories, Projects, Modified]
        super().__init__(*args, entity=entity, **kwargs)

        for field in self.fields.values():
            field.selected = True


class UserTable(Columns["Entity | Site"]):
    _id = "table"
    _kind = "user"

    def __init__(self, *args: object, entity: Entity | Site | None = None, **kwargs: object) -> None:
        self.column_fields = [Name, Email, Groups, LastLogin, Modified]
        super().__init__(*args, entity=entity, **kwargs)

        for field in self.fields.values():
            field.selected = True
