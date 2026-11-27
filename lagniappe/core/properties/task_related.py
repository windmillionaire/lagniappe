from typing import TYPE_CHECKING, cast

from flask_login import current_user

from ..definitions import Action, FieldType, FilterOptions, MutationIntent, Ordering
from ..entities import Entities
from ..exceptions import ValidationError
from ..mixins import (
    AIMixin,
    ColumnMixin,
    DetailsMixin,
    FilterMixin,
    RelatedEntityListMixin,
    RelatedEntityMixin,
)
from .base_db import DBProperty
from .base_property import Property
from .form_special import Signature, Status


if TYPE_CHECKING:
    from ..entities import types as models
    from ..entities.condition import Condition


type _Task = models.Task
type _TaskOrHistory = models.Task | models.TaskHistory
type _Page = models.Page
type _Category = models.Category
type _File = models.File
type _Model = models.ModelTask


class TaskStatus(ColumnMixin, Property[list[str], _Task]):
    """Task-level status column derived from the task's attached form."""

    _id = "status"
    _label = "Status"
    _icon = "status"
    _kind: str | None = "task"
    _ordering = Ordering.EXISTS

    @property
    def status_field(self) -> Status | None:
        return next(
            (
                field
                for field in self.entity.properties.submission.fields.values()
                if isinstance(field, Status)
            ),
            None,
        )

    @property
    def value(self) -> list[str] | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        field = self.status_field
        return field.value if field else None

    @property
    def column_value(self) -> list[str] | None:
        field = self.status_field
        return field.column_value if field else None

    @property
    def sort_value(self) -> bool | None:
        field = self.status_field
        return field.sort_value if field else None


class TaskCategories(
    RelatedEntityListMixin[_Category], FilterMixin, ColumnMixin, AIMixin, Property[list[_Category], _Task]
):
    """Categories for a task, derived from the task's parent page.

    Not stored on the task -- delegates to page.categories. Returns
    an empty list if the task has no page.
    """

    _value: object
    _id = "categories"
    _label = "Categories"
    _icon = "category"
    _kind: str | None = "category"

    # Filter Attributes
    _placeholder = "select a category..."
    _index = "category"
    multiple = True

    @property
    def value(self) -> list[models.Category]:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        if not self.entity.page:
            return []

        categories = self.entity.page.categories
        self._value = categories
        return categories

    @property
    def filter_label(self) -> str:
        return "In Categories"

    @property
    def sort_value(self) -> dict[str, str | None] | None:
        return {entity.hash: entity.name for entity in self.value} or None

    def filter_details(self, condition: Condition) -> dict[str, object]:
        details = super().filter_details(condition)
        details["kind"] = "category"
        if "entity" in details:
            details["label"] = "In Category"
            details.pop("text")
        return details


class TaskFiles(RelatedEntityListMixin[_File], ColumnMixin, AIMixin, DBProperty[list[_File], _TaskOrHistory]):
    """Files related to a task.

    Get:
        value (list): Attached file entities, or [] if not loaded.
    """

    # Property Attributes
    _id = "files"
    _label = "Attachments"
    _kind: str | None = "file"
    _icon = "file"

    def _file_asset_preload_key(self, file: models.File) -> str:
        return file.filename or file.name or file.hash

    def _track_file_update(self, file: models.File) -> None:
        file.normalize_owner()
        self.entity.add_mutation_intents(
            MutationIntent.patch(
                file,
                "page",
                "task",
                "task_page",
                "requires",
                property_updates=("requires", "modified"),
                reason="task-file-mirror",
            )
        )

    def _link_file(self, file: models.File) -> None:
        if not file or not getattr(self.entity, "key", None):
            return

        if self.entity.entity_kind == "task_history":
            if not file.has_references:
                file.task = cast("models.TaskHistory", self.entity).task
                self._track_file_update(file)
            return
        if file.has_references and file.properties.task.key != self.entity.key:
            raise ValidationError("Move the File to this Task before attaching it")
        file.task = cast("models.Task", self.entity)
        self._track_file_update(file)

    def _unlink_file(self, file: models.File) -> None:
        if not file or not getattr(self.entity, "key", None):
            return

        # Removing a current attachment does not erase ownership: a completion
        # history may still reference the File. Moves and deletion own unlinking.
        return

    @property
    def value(self) -> list[models.File]:
        return self._read_related_list()

    @value.setter
    def value(self, value: list[models.File] | None) -> None:
        existing = {file.key: file for file in self._read_related_list()}
        updated = {file.key: file for file in value or []}

        for key, file in existing.items():
            if key not in updated:
                self._unlink_file(file)
        for file in updated.values():
            self._link_file(file)

        self._write_related_list(value)

    def add(self, value: models.File) -> bool | None:
        added = super().add(value)
        if added:
            self._link_file(value)
        return added

    def remove(self, value: models.File) -> bool:
        removed = self._remove_related(value)
        if removed:
            self._unlink_file(value)
        return removed

    @property
    def preload(self) -> dict[str, dict[str, object]]:
        preload = {}

        for file in self.value:
            if (
                not file.allowed(Action.VIEW, user=self.user)
                or file.reserved
            ):
                continue
            details = dict(file.details)
            details["attached"] = True
            preload[self._file_asset_preload_key(file)] = details

        return preload

    @property
    def column_value(self) -> list[dict[str, object]]:
        cached = getattr(self, "_column_value", None)
        if cached is not None:
            return cached
        elif not self.value:
            return []

        self._column_value = [
            dict(file.details)
            for file in self.value
            if file.allowed(Action.VIEW, self.user) and not file.reserved
        ]

        return self._column_value

    @property
    def ai_value(self) -> list[dict[str, object]] | None:
        files = []
        for file in self.value:
            if (
                not file
                or not file.allowed(Action.VIEW, self.user)
                or file.reserved
            ):
                continue
            files.append(file.to_ai(self.user))
        return files or None

    # Column Attributes
    @property
    def sort_value(self) -> int | None:
        return len(self.value) if self.value else None

class HasSignature(FilterMixin, Property[bool, _Task]):
    """Whether a task's schema includes a signature and the task has one saved.

    Returns ``None`` for tasks whose schema has no signature field, ``False`` for
    tasks that ask for a signature but have no saved signature asset, and
    ``True`` when the task has a signature asset attached.
    """

    _id = "has_signature"
    _label = "Has Signature"
    _icon = "signature"
    _kind: str | None = "task"

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.SIGNATURE.value
    _field_text = "is"
    _default = "IS_TRUE"

    @property
    def signature_field(self) -> Signature | None:
        return next(
            (
                field
                for field in self.entity.properties.submission.fields.values()
                if isinstance(field, Signature)
            ),
            None,
        )

    @property
    def value(self) -> bool | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        field = self.signature_field
        if not field:
            return None
        return bool(field.value)

    @property
    def filter_value(self) -> bool | None:
        return self.value


class HasStatus(FilterMixin, Property[bool, _Task]):
    """Whether a task's schema includes status and any status is active.

    Returns ``None`` for tasks whose schema has no status field, ``False`` for
    tasks that have status definitions but no active status, and ``True`` when
    at least one status condition matches the current submission.
    """

    _id = "has_status"
    _label = "Has Status"
    _icon = "status"
    _kind: str | None = "task"

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.STATUS.value
    _field_text = "is"
    _default = "IS_TRUE"

    @property
    def status_field(self) -> Status | None:
        return next(
            (
                field
                for field in self.entity.properties.submission.fields.values()
                if isinstance(field, Status)
            ),
            None,
        )

    @property
    def value(self) -> bool | None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This projection is computed and read-only.
        field = self.status_field
        if not field:
            return None
        return bool(field.value)

    @property
    def filter_value(self) -> bool | None:
        return self.value


class AssignedTo(RelatedEntityMixin[_Page], ColumnMixin, FilterMixin, AIMixin, DBProperty[_Page, _Task]):
    """User that a task is assigned to.

    Setting this also records who made the assignment (assigned_by)
    using the current user. User entities are stored via their page key.

    Set:
        value (Entity): User or Page entity to assign to.

    Get:
        value (Entity): The assigned user's page entity.
    """

    # Property Attributes
    _id = "assigned_to"
    _kind: str | None = "user"
    _label = "Assigned To"
    _icon = "user"
    _text = "Assigned to:"

    @property
    def value(self) -> models.Page | None:
        return super().value

    @value.setter
    def value(self, value: models.User | models.Page | None) -> None:
        if not value:
            self.entity.properties.assigned_by._write_related(None)
            self._write_related(None)
            return

        assigned_to = value.page if isinstance(value, Entities.USER) else cast("models.Page", value)
        if current_user and current_user.is_authenticated:
            self.entity.properties.assigned_by.value = cast("models.User", current_user)

        self._write_related(assigned_to)

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    # Filter Attributes
    _field_options = FilterOptions.LIST.value
    _field_type = FieldType.STRING
    _index = "user"
    _field_text = "Assigned to"
    _placeholder = "select users..."
    multiple = True


class AssignedBy(RelatedEntityMixin[_Page], ColumnMixin, FilterMixin, AIMixin, DBProperty[_Page, _Task]):
    """User who assigned the task. Only accepts authenticated users.

    Set:
        value (Entity): User entity who made the assignment.

    Get:
        value (Entity): The assigning user's page entity.
    """

    # Property Attributes
    _id = "assigned_by"
    _kind: str | None = "user"
    _label = "Assigned By"
    _icon = "user"
    _text = "Assigned by:"

    @property
    def value(self) -> models.Page | None:
        return super().value

    @value.setter
    def value(self, value: models.User | models.Page | None) -> None:
        if not isinstance(value, Entities.USER) or not value.is_authenticated:
            return

        self._write_related(value.page)

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    # Filter Attributes
    _field_options = FilterOptions.LIST.value
    _field_type = FieldType.STRING
    _index = "user"
    _field_text = "Assigned to"
    _placeholder = "select users..."
    multiple = True


class CompletedBy(RelatedEntityMixin[_Page], FilterMixin, AIMixin, ColumnMixin, DBProperty[_Page, _TaskOrHistory]):
    """User who completed the task. Only accepts authenticated users.

    Set:
        value (Entity): User entity who completed the task.

    Get:
        value (Entity): The completing user's page entity.
    """

    # Property Attributes
    _id = "completed_by"
    _kind: str | None = "user"
    _label = "Completed By"
    _icon = "completedBy"
    _text = "Completed by:"

    @property
    def value(self) -> models.Page | None:
        return super().value

    @value.setter
    def value(self, value: models.User | models.Page | None) -> None:
        completed_by = value.page if isinstance(value, Entities.USER) else cast("models.Page | None", value)

        self._write_related(completed_by)

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    # Filter Attributes
    _field_options = FilterOptions.LIST.value
    _field_type = FieldType.STRING
    _index = "user"
    _field_text = "Completed by"
    _placeholder = "select users..."
    multiple = True


class LinkedPages(RelatedEntityListMixin[_Page], ColumnMixin, AIMixin, DBProperty[list[_Page], _TaskOrHistory]):
    """Pages linked to a task (beyond the parent page).

    The setter stores the current submission-derived page links and excludes
    the task's own page from the stored list.

    Set:
        value (list): Page entities.

    Get:
        value (list): Linked page entities (permission-checked via mixin).
    """

    # Property Attributes
    _id = "linked_pages"
    _kind: str | None = "page"
    _label = "Linked Pages"
    _icon = "page"

    @property
    def value(self) -> list[models.Page]:
        return super().value

    @value.setter
    def value(self, value: list[models.Page] | None) -> None:
        self._set_value(value)

    def _set_value(self, value: list[models.Page] | None) -> None:
        self._column_value = None
        existing = {p.key: p for p in super().value if p}
        page_key = self.entity.page.key if self.entity.page else None
        linked = list(
            {
                p.key: p
                for p in value or []
                if p and getattr(p, "key", None) and p.key != page_key
            }.values()
        )

        self._write_related_list(linked)
        updated_keys = {p.key for p in linked}
        for key, page in existing.items():
            if key not in updated_keys:
                self.entity.add_mutation_intents(
                    MutationIntent.touch(page, reason="task-previous-linked-page")
                )


class TaskModel(RelatedEntityMixin[_Model], FilterMixin, AIMixin, DBProperty[_Model, _Task]):
    """The model task (workflow stage) that a task belongs to within its project.

    Set:
        value (Entity): ModelTask entity.

    Get:
        value (Entity): ModelTask entity.
    """

    # Property Attributes
    _id = "model"
    _label = "Model Task"

    @property
    def value(self) -> models.ModelTask | None:
        return self._read_related()

    @value.setter
    def value(self, value: models.ModelTask | None) -> None:
        self._write_related(value)
        if not value or getattr(self.entity.properties.form, "key", None):
            return

        form = self._model_form(value)
        if form:
            self.entity.form = form

    def _model_form(self, model: models.ModelTask) -> models.Form | None:
        form_property = getattr(getattr(model, "properties", None), "form", None)
        if not form_property:
            return None
        if getattr(form_property, "is_set", False):
            form = form_property.value
            if isinstance(form, Entities.FORM):
                return form

        return None

    # Filter attributes
    @property
    def filter_key(self) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] -- Model ownership exposes a fixed filter key.
        return "model"


class TaskPage(RelatedEntityMixin[_Page], DetailsMixin, FilterMixin, AIMixin, DBProperty[_Page, _Task]):
    """Page for a task. Tasks inherit permissions from their page.

    Set:
        value (Entity): Page entity.

    Get:
        value (Entity): Page entity.

    Overrides:
        details_key: Returns "parent".
    """

    # Property Attributes
    _id = "page"
    _label = "Page"

    @property
    def value(self) -> models.Page | None:
        return super().value

    @value.setter
    def value(self, value: models.Page | None) -> None:
        previous = self.value
        previous_key = previous.key if previous else None
        next_key = value.key if value else None

        self._write_related(value)

        if previous_key != next_key:
            self.entity.properties.restricted_to.unset()
            self.entity._page_changed = bool(previous_key)
        if previous and previous_key != next_key:
            self.entity.add_mutation_intents(
                MutationIntent.touch(previous, reason="task-previous-page")
            )

    # Details Attributes
    @property
    def details_key(self) -> str:
        return "parent"

    @property
    def details_value(self) -> dict[str, object] | None:
        if not self.entity.page:
            return None

        parent = self.entity.page.reference_details
        if parent:
            parent.pop("parent", None)
        return parent
