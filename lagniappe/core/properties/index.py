from .base_columns import Columns
from .common_entity import Description, Modified, Name
from .common_related import Categories, Projects
from .form import FormType
from .task_related import AssignedTo, CompletedBy, TaskFiles, TaskStatus
from .task_dates import Completed, CompletedOn, DueDate
from .user_related import Groups
from .user_entity import Email, LastLogin
from ..mixins import ColumnMixin


# @testable true
# @tests tests_unit/test_010_task_index.py::test_task_index
# @features task-index
# @dimensions table, columns
class TaskTable(Columns):
    _id = "table"
    _kind = "task"

    def __init__(self, *args, **kwargs):
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
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            if isinstance(field, self.default_selected):
                field.selected = True


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_appears_after_completion_cycle
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload
# @tests tests_unit/test_010_task_index.py::test_task_history_index_includes_attachments_column
# @tests tests_unit/test_010_task_index.py::test_task_history_index_includes_snapshot_columns
# @features tasks
# @dimensions history completion-cycle reload table columns name description attachments
class TaskHistoryTable(Columns):
    _id = "table"
    _kind = "task"
    _embedded = True
    default_selected = (CompletedOn, Name, Description)

    def __init__(self, *args, **kwargs):
        self.column_fields = [
            CompletedOn,
            Name,
            Description,
            CompletedBy,
            TaskFiles,
        ]
        super().__init__(*args, **kwargs)

    @property
    def fields(self):
        if getattr(self, "_fields", None):
            return self._fields

        fields = {}
        for f in self.column_fields:
            field = f(entity=self.entity)
            fields[field.id] = field

        if self.entity.form:
            fields.update(
                {
                    f.id: f
                    for f in self.entity.form.fields.values()
                    if isinstance(f, ColumnMixin)
                }
            )

        for f in fields.values():
            f.selected = isinstance(f, self.default_selected)
            if isinstance(f, Name):
                f.link = False
                f.parent = False

        self._fields = fields
        return self._fields


# @testable true
# @tests tests_unit/test_004a_form_index.py::test_form_index_table
# @features form-index
# @dimensions table, columns
class FormTable(Columns):
    _id = "table"
    _kind = "form"

    def __init__(self, *args, **kwargs):
        self.column_fields = [Name, FormType, Categories, Projects, Modified]
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.selected = True


# @testable true
# @tests tests_unit/test_009_user_index.py::test_user_index
# @features user-index
# @dimensions table, columns
class UserTable(Columns):
    _id = "table"
    _kind = "user"

    def __init__(self, *args, **kwargs):
        self.column_fields = [Name, Email, Groups, LastLogin, Modified]
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.selected = True
