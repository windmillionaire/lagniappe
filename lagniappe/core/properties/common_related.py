from ..definitions import Action, MutationIntent
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


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_category_and_form
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_model_project_form
# @matrix form : model parent related-entities
class AttachedForm(RelatedEntityMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty):
    """The form attached to an entity.

    Set:
        value (Entity): Form entity.

    Get:
        value (Entity): Form entity.

    Overrides:
        filter_label: Returns the form's name.
    """

    # Property Attributes
    _id = "form"
    _icon = "form"
    _kind = "form"

    # Column Attributes
    _label = "Form"

    @property
    def value(self):
        return RelatedEntityMixin.value.fget(self)

    @value.setter
    def value(self, value):
        if value is not None and not getattr(value, "key", None):
            raise ValueError("Value must have a key")
        if value is not None and getattr(value, "entity_kind", None) != "form":
            raise ValueError("Value must be a form")

        RelatedEntityMixin.value.fset(self, value)

    # Filter Attributes
    @property
    def filter_label(self):
        return self.value.name if self.value else None

    @property
    def ai_value(self):
        if (
            not self.value
            or not self.value.allowed(Action.VIEW, self.user)
            or self.value.reserved
        ):
            return None

        return self.value.to_ai(self.user)

    def filter_details(self, condition):
        details = super().filter_details(condition)
        details["label"] = "Form Attached"
        return details


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_task_history_returns_dates_submissions_and_files
# @matrix ai tasks : context files task-history
class AttachedTask(RelatedEntityMixin, FilterMixin, AIMixin, Property):
    """A task attached to an entity (used in task history)."""

    # Property Attributes
    _id = "task"
    _label = "Task"
    _icon = "task"
    _kind = "task"


# @testable true
# @tests tests_unit/test_007_category_properties.py::test_category_filters_related_forms
# @matrix category filters form : entity-fields related-forms
class RelatedForm(RelatedEntityMixin, FilterMixin, Property):
    """A form related to an entity (used in filter conditions).

    Unlike AttachedForm, this is not persisted in entity.db -- it
    exists only as a filter-time reference to a form entity.

    Set:
        value (Entity): Form entity.

    Get:
        value (Entity): Form entity.
    """

    # Property Attributes
    _id = "form"
    _icon = "form"
    _kind = "form"

    # Column Attributes
    _label = "Form"

    # Filter Attributes
    @property
    def filter_label(self):
        return self.value.name if self.value else None

    def filter_details(self, condition):
        details = super().filter_details(condition)
        details["label"] = "Form Attached"
        return details


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_model_project_form
# @matrix task : model related-entities
class AttachedModelTask(
    RelatedEntityMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty
):
    """The model task attached to an entity."""

    # Property Attributes
    _id = "model"
    _label = "Model Task"
    _icon = "model"
    _kind = "task"

    @property
    def filter_label(self):
        return self.value.name if self.value else None

    def filter_details(self, condition):
        details = super().filter_details(condition)
        details["label"] = "Model Task"
        return details


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_project
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_model_project_form
# @matrix project : model parent related-entities
class AttachedProject(
    RelatedEntityMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty
):
    """The project attached to an entity.

    Overrides:
        details_key: Returns "parent" for ModelTask entities.
    """

    # Property Attributes
    _id = "project"
    _label = "Project"
    _icon = "project"
    _kind = "project"

    # Details Attributes
    @property
    def details_key(self):
        if isinstance(self.entity, Entities.MODEL_TASK):
            return "parent"
        return "project"


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_category_and_form
# @matrix category : parent related-entities
class AttachedCategory(
    RelatedEntityMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty
):
    """The category attached to an entity."""

    # Property Attributes
    _id = "category"
    _label = "Category"
    _icon = "category"
    _kind = "category"


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_attached_page_details_key_uses_parent
# @matrix tasks : attached-page history parent-details
class AttachedPage(
    RelatedEntityMixin, DetailsMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty
):
    """The page attached to an entity.

    Overrides:
        details_key: Returns "parent" for Task entities.
    """

    # Property Attributes
    _id = "page"
    _label = "Page"
    _icon = "page"
    _kind = "page"

    # Details Attributes
    @property
    def details_key(self):
        if self.entity.entity_kind in {"task", "task_history"}:
            return "parent"
        return "page"


# @testable true
# @tests tests_unit/test_004a_form_index.py::test_form_index_table
# @pair form-index:columns
class Categories(RelatedEntityListMixin, FilterMixin, ColumnMixin, Property):
    """Categories that an entity is associated with (for column/filter display)."""

    # Property Attributes
    _id = "categories"
    _label = "Categories"
    _icon = "category"
    _kind = "category"

    # Filter Attributes
    _placeholder = "select a category..."
    _index = "category"
    multiple = True

    @property
    def filter_label(self):
        return "In Categories"

    @property
    def sort_value(self):
        return {entity.hash: entity.name for entity in self.value}


# @testable true
# @tests tests_unit/test_004a_form_index.py::test_form_index_table
# @pair form-index:columns
class Projects(RelatedEntityListMixin, FilterMixin, ColumnMixin, Property):
    """Projects that an entity is associated with (for column/filter display)."""

    # Property Attributes
    _id = "projects"
    _label = "Projects"
    _icon = "project"
    _kind = "project"

    # Filter Attributes
    _placeholder = "select a project..."
    _index = "project"
    multiple = True

    @property
    def filter_label(self):
        return "In Projects"

    @property
    def sort_value(self):
        return {entity.hash: entity.name for entity in self.value}


class ModelTasks(RelatedEntityListMixin, ColumnMixin, Property):
    """Model tasks associated with an entity (for column display)."""

    # Property Attributes
    _id = "model_tasks"
    _label = "Model Tasks"
    _icon = "model"
    _kind = "model"


# @testable false
# @covered-by lagniappe/core/properties/common_related.py::RelatedForms.add
# @reason duplicate prevention and relation registration are owned by add()
class RelatedForms(RelatedEntityListMixin, DBProperty):
    """Additional forms related to an entity (beyond the primary attached form).

    Prevents duplicating the primary form. Adding a form also registers
    it as a related entity on the parent.
    """

    # Property Attributes
    _id = "forms"
    _label = "Form"
    _icon = "form"
    _kind = "form"

    @property
    def value(self):
        return RelatedEntityListMixin.value.fget(self)

    @value.setter
    def value(self, value):
        if value is not None and not isinstance(value, list):
            raise TypeError("Value must be a list")
        for item in value or []:
            if not getattr(item, "key", None):
                raise ValueError("Value must have a key")
            if getattr(item, "entity_kind", None) != "form":
                raise ValueError("Value must be a form")

        RelatedEntityListMixin.value.fset(self, value)

    # @testable true
    # @tests tests_unit/test_007_category_properties.py::test_related_forms_add_skips_primary_form_and_registers_relation
    # @tests tests_unit/test_007_category_properties.py::test_related_forms_add_rejects_value_without_key
    # @matrix category form : add duplicate-primary related-forms relation-registration
    def add(self, value):
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")
        if getattr(value, "entity_kind", None) != "form":
            raise ValueError("Value must be a form")

        if self.entity.form and key == self.entity.form.key:
            return False

        if key not in [v.key for v in self.value]:
            self.value.append(value)
            keys = [v.key for v in self.value]
            if keys in self._blank_values:
                self.entity.db.pop(self.id, None)
            else:
                self.entity.db[self.id] = keys
            self.entity.add_mutation_intents(
                MutationIntent.touch(value, reason="related-form-list-member")
            )
            return True
        return False


class Groups(RelatedEntityListMixin, DBProperty):
    """Groups that have access to a form."""

    _id = "groups"
    _label = "Groups"
    _icon = "group"
    _kind = "user"
