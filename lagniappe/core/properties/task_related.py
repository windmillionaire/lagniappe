from flask_login import current_user

from ..definitions import Action, FieldType, FilterOptions, MutationIntent, Ordering
from ..entities import Entities
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


# @testable true
# @tests tests_unit/test_010_task_index.py::test_task_index_status_column_derives_messages_from_mixed_forms
# @features task-index status
# @dimensions mixed-forms computed-column
class TaskStatus(ColumnMixin, Property):
    """Task-level status column derived from the task's attached form."""

    _id = "status"
    _label = "Status"
    _icon = "status"
    _kind = "task"
    _ordering = Ordering.EXISTS

    @property
    def status_field(self):
        return next(
            (
                field
                for field in self.entity.properties.submission.fields.values()
                if isinstance(field, Status)
            ),
            None,
        )

    @property
    def value(self):
        field = self.status_field
        return field.value if field else None

    @property
    def column_value(self):
        field = self.status_field
        return field.column_value if field else None

    @property
    def sort_value(self):
        field = self.status_field
        return field.sort_value if field else None


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_filters
# @tests tests_unit/test_013_task_properties.py::test_task_categories_follow_parent_page_categories
# @features task
# @dimensions categories parent-derived filter-value
class TaskCategories(
    RelatedEntityListMixin, FilterMixin, ColumnMixin, AIMixin, Property
):
    """Categories for a task, derived from the task's parent page.

    Not stored on the task -- delegates to page.categories. Returns
    an empty list if the task has no page.
    """

    _id = "categories"
    _label = "Categories"
    _icon = "category"
    _kind = "category"

    # Filter Attributes
    _placeholder = "select a category..."
    _index = "category"
    multiple = True

    @property
    def value(self):
        if not self.entity.page:
            return []

        self._value = self.entity.page.categories
        return self._value

    @property
    def filter_label(self):
        return "In Categories"

    @property
    def sort_value(self):
        return {entity.hash: entity.name for entity in self.value}

    def filter_details(self, condition):
        details = super().filter_details(condition)
        details["kind"] = "category"
        if "entity" in details:
            details["label"] = "In Category"
            details.pop("text")
        return details


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_related_lists_replace_linked_pages_and_report_unloaded_files
# @features task
# @dimensions related-files unloaded-fallback
class TaskFiles(RelatedEntityListMixin, ColumnMixin, AIMixin, DBProperty):
    """Files related to a task.

    Get:
        value (list): Attached file entities, or [] if not loaded.
    """

    # Property Attributes
    _id = "files"
    _label = "Attachments"
    _kind = "file"
    _icon = "file"

    def _file_asset_preload_key(self, file):
        return file.filename or file.name or file.hash

    def _track_file_update(self, file):
        self.entity.add_mutation_intents(
            MutationIntent.patch(
                file,
                "tasks",
                "requires",
                property_updates=("requires", "modified"),
                reason="task-file-mirror",
            )
        )

    def _link_file(self, file):
        if not file or not getattr(self.entity, "key", None):
            return

        file.properties.tasks.add(self.entity)
        self._track_file_update(file)

    def _unlink_file(self, file):
        if not file or not getattr(self.entity, "key", None):
            return

        file.properties.tasks.remove(self.entity)
        self._track_file_update(file)

    @property
    def value(self):
        return RelatedEntityListMixin.value.fget(self)

    @value.setter
    def value(self, value):
        existing = {file.key: file for file in RelatedEntityListMixin.value.fget(self)}
        updated = {file.key: file for file in value or []}

        for key, file in existing.items():
            if key not in updated:
                self._unlink_file(file)
        for file in updated.values():
            self._link_file(file)

        RelatedEntityListMixin.value.fset(self, value)

    def add(self, value):
        added = super().add(value)
        if added:
            self._link_file(value)
        return added

    def remove(self, value):
        removed = super().remove(value)
        if removed:
            self._unlink_file(value)
        return removed

    @property
    def preload(self):
        preload = {}

        for file in self.value:
            details = dict(file.details)
            details["attached"] = True
            preload[self._file_asset_preload_key(file)] = details

        return preload

    @property
    def column_value(self):
        if getattr(self, "_column_value", None) is not None:
            return self._column_value
        elif not self.value:
            return []

        self._column_value = [
            dict(file.details)
            for file in self.value
            if file.allowed(Action.VIEW, self.user) and not file.reserved
        ]

        return self._column_value

    @property
    def ai_value(self):
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
    def sort_value(self):
        return len(self.value) if self.value else None

# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_has_signature_filter_value
# @features task, signature, filters
# @dimensions schema-field, filter-value
class HasSignature(FilterMixin, Property):
    """Whether a task's schema includes a signature and the task has one saved.

    Returns ``None`` for tasks whose schema has no signature field, ``False`` for
    tasks that ask for a signature but have no saved signature asset, and
    ``True`` when the task has a signature asset attached.
    """

    _id = "has_signature"
    _label = "Has Signature"
    _icon = "signature"
    _kind = "task"

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.SIGNATURE.value
    _field_text = "is"
    _default = "IS_TRUE"

    @property
    def signature_field(self):
        return next(
            (
                field
                for field in self.entity.properties.submission.fields.values()
                if isinstance(field, Signature)
            ),
            None,
        )

    @property
    def value(self):
        field = self.signature_field
        if not field:
            return None
        return True if field.value else False

    @property
    def filter_value(self):
        return self.value


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_has_status_filter_value
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_has_status_renders_status_column
# @pairs task:schema-field task:filter-value
# @pairs status:schema-field status:filter-value status:boolean-condition status:run-results
# @pairs filters:schema-field filters:filter-value filters:boolean-condition filters:run-results
class HasStatus(FilterMixin, Property):
    """Whether a task's schema includes status and any status is active.

    Returns ``None`` for tasks whose schema has no status field, ``False`` for
    tasks that have status definitions but no active status, and ``True`` when
    at least one status condition matches the current submission.
    """

    _id = "has_status"
    _label = "Has Status"
    _icon = "status"
    _kind = "task"

    # Filter Attributes
    _field_type = FieldType.BOOLEAN
    _field_options = FilterOptions.STATUS.value
    _field_text = "is"
    _default = "IS_TRUE"

    @property
    def status_field(self):
        return next(
            (
                field
                for field in self.entity.properties.submission.fields.values()
                if isinstance(field, Status)
            ),
            None,
        )

    @property
    def value(self):
        field = self.status_field
        if not field:
            return None
        return True if field.value else False

    @property
    def filter_value(self):
        return self.value


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_without_schedule
# @tests tests_unit/test_013_task_properties.py::test_task_assignment_records_assigned_by_user_page
# @features task
# @dimensions assignee assignment assigned-by
class AssignedTo(RelatedEntityMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty):
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
    _kind = "user"
    _label = "Assigned To"
    _icon = "user"
    _text = "Assigned to:"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if not value:
            RelatedEntityMixin.value.fset(self.entity.properties.assigned_by, None)
            RelatedEntityMixin.value.fset(self, None)
            return

        assigned_to = value.page if isinstance(value, Entities.USER) else value
        if current_user and current_user.is_authenticated:
            self.entity.assigned_by = current_user

        RelatedEntityMixin.value.fset(self, assigned_to)

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    # Filter Attributes
    _field_options = FilterOptions.LIST.value
    _field_type = FieldType.STRING
    _index = "user"
    _field_text = "Assigned to"
    _placeholder = "select users..."
    multiple = True


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_assignment_records_assigned_by_user_page
# @features task
# @dimensions assigned-by
class AssignedBy(RelatedEntityMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty):
    """User who assigned the task. Only accepts authenticated users.

    Set:
        value (Entity): User entity who made the assignment.

    Get:
        value (Entity): The assigning user's page entity.
    """

    # Property Attributes
    _id = "assigned_by"
    _kind = "user"
    _label = "Assigned By"
    _icon = "user"
    _text = "Assigned by:"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        if not isinstance(value, Entities.USER) or not value.is_authenticated:
            return

        RelatedEntityMixin.value.fset(self, value.page)

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    # Filter Attributes
    _field_options = FilterOptions.LIST.value
    _field_type = FieldType.STRING
    _index = "user"
    _field_text = "Assigned to"
    _placeholder = "select users..."
    multiple = True


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_without_schedule
# @features task-completion
# @dimensions completed-by
class CompletedBy(RelatedEntityMixin, FilterMixin, AIMixin, ColumnMixin, DBProperty):
    """User who completed the task. Only accepts authenticated users.

    Set:
        value (Entity): User entity who completed the task.

    Get:
        value (Entity): The completing user's page entity.
    """

    # Property Attributes
    _id = "completed_by"
    _kind = "user"
    _label = "Completed By"
    _icon = "completedBy"
    _text = "Completed by:"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        completed_by = value.page if isinstance(value, Entities.USER) else value

        RelatedEntityMixin.value.fset(self, completed_by)

    # Column Attributes
    _ordering = Ordering.CATEGORICAL

    # Filter Attributes
    _field_options = FilterOptions.LIST.value
    _field_type = FieldType.STRING
    _index = "user"
    _field_text = "Completed by"
    _placeholder = "select users..."
    multiple = True


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_related_lists_replace_linked_pages_and_report_unloaded_files
# @features task
# @dimensions linked-pages replacement
class LinkedPages(RelatedEntityListMixin, ColumnMixin, AIMixin, DBProperty):
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
    _kind = "page"
    _label = "Linked Pages"
    _icon = "page"

    @property
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        self._set_value(value)

    def _set_value(self, value):
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

        RelatedEntityListMixin.value.fset(self, linked)
        updated_keys = {p.key for p in linked}
        for key, page in existing.items():
            if key not in updated_keys:
                self.entity.add_mutation_intents(
                    MutationIntent.touch(page, reason="task-previous-linked-page")
                )


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_model_and_page_details_attach_from_key_map
# @features task
# @dimensions model
class TaskModel(RelatedEntityMixin, FilterMixin, AIMixin, DBProperty):
    """The model task (workflow stage) that a task belongs to within its project.

    Set:
        value (Entity): ModelTask entity.

    Get:
        value (Entity): ModelTask entity.
    """

    # Property Attributes
    _id = "model"
    _label = "Model Task"

    # @testable true
    # @tests tests_unit/test_013_task_properties.py::test_task_model_tracking_inherits_model_form
    # @features task
    # @dimensions model-form inheritance
    @property
    def value(self):
        return RelatedEntityMixin.value.fget(self)

    @value.setter
    def value(self, value):
        RelatedEntityMixin.value.fset(self, value)
        if not value or getattr(self.entity.properties.form, "key", None):
            return

        form = self._model_form(value)
        if form:
            self.entity.form = form

    # @testable false
    # @covered-by lagniappe/core/properties/task_related.py::TaskModel.value
    # @reason loaded model-form inheritance is asserted through the model setter
    def _model_form(self, model):
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
    def filter_key(self):
        return "model"


# @testable true
# @tests tests_unit/test_013_task_properties.py::test_task_model_and_page_details_attach_from_key_map
# @features task
# @dimensions page details attach
class TaskPage(RelatedEntityMixin, DetailsMixin, FilterMixin, AIMixin, DBProperty):
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
    def value(self):
        return super().value

    @value.setter
    def value(self, value):
        previous = self.value
        previous_key = previous.key if previous else None
        next_key = value.key if value else None

        RelatedEntityMixin.value.fset(self, value)

        if previous and previous_key != next_key:
            self.entity.add_mutation_intents(
                MutationIntent.touch(previous, reason="task-previous-page")
            )

    # Details Attributes
    @property
    def details_key(self):
        return "parent"

    @property
    def details_value(self):
        if not self.entity.page:
            return None

        parent = self.entity.page.reference_details
        if parent:
            parent.pop("parent", None)
        return parent
