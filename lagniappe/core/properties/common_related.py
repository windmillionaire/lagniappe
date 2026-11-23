from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ..entities.category import Category
    from ..entities.condition import Condition
    from ..entities.form import Form
    from ..entities.group import UserGroup
    from ..entities.history import TaskHistory
    from ..entities.model_task import ModelTask
    from ..entities.page import Page
    from ..entities.project import Project
    from ..entities.task import Task
    from .common_entity import RestrictedTo

from ..definitions import Action, MutationIntent
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
from lagniappe.core.tools.forms.definitions import immutable_submission
from .base_db import DBProperty
from .base_property import Property


type _Page = Page
type _GroupOwner = Form | Page | Task


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_category_and_form
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_model_project_form
# @matrix form : model parent related-entities
class AttachedForm(
    RelatedEntityMixin["Form"], ColumnMixin, FilterMixin, AIMixin, DBProperty["Form"]
):
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
    _kind: str | None = "form"

    # Column Attributes
    _label = "Form"

    @property
    def value(self) -> Form | None:
        return self._read_related()

    @value.setter
    def value(self, value: Form | None) -> None:
        if (
            self.entity.entity_kind in {"task", "task_history"}
            and self.key is not None
            and immutable_submission(self.entity)
            and self.key != getattr(value, "key", None)
        ):
            raise ValidationError("A completed submission must keep its original form.")
        if value is not None and not getattr(value, "key", None):
            raise ValueError("Value must have a key")
        if value is not None and getattr(value, "entity_kind", None) != "form":
            raise ValueError("Value must be a form")

        if self.entity.entity_kind in {"page", "task"} and self.key != getattr(value, "key", None):
            self.entity._permission_sources_changed = True
        self._write_related(value)
        restricted_to = cast("RestrictedTo | None", self.entity.properties.get("restricted_to"))
        if restricted_to is not None:
            restricted_to.unset()

    # Filter Attributes
    @property
    def filter_label(self) -> str | None:
        return self.value.name if self.value else None

    @property
    def ai_value(self) -> dict[str, object] | None:
        if self.entity.entity_kind in {"task", "task_history"} and immutable_submission(
            self.entity
        ):
            if not self.entity.allowed(Action.VIEW, user=self.user):
                return None
            definition = cast("Task | TaskHistory", self.entity).submission_definition
            if definition.error:
                return {"unavailable": definition.error}
            return {"schema": definition.schema, "generation": definition.generation}
        if (
            not self.value
            or not self.value.allowed(Action.VIEW, self.user)
            or self.value.reserved
        ):
            return None

        return self.value.to_ai(self.user)

    def filter_details(self, condition: Condition) -> dict[str, object]:
        details = super().filter_details(condition)
        details["label"] = "Form Attached"
        return details


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_task_history_returns_dates_submissions_and_files
# @matrix ai tasks : context files task-history
class AttachedTask(RelatedEntityMixin["Task"], FilterMixin, AIMixin, Property["Task"]):
    """A task attached to an entity (used in task history)."""

    # Property Attributes
    _id = "task"
    _label = "Task"
    _icon = "task"
    _kind: str | None = "task"
    _value: object

    @property
    def key(self) -> Key | None:
        if self.is_set and self._value:
            return cast("Task", self._value).key
        return getattr(self.entity.key, "parent", None)

    @property
    def keys(self) -> list[Key | None]:
        return [self.key] if self.key else []

    def attach(self, key_map: Mapping[Key, Task]) -> None:
        key = self.key
        self._value = key_map.get(key) if key is not None else None
        self._cache_attached_entities()
        self._invalidate_projections()



# @testable true
# @tests tests_unit/test_007_category_properties.py::test_category_filters_related_forms
# @matrix category filters form : entity-fields related-forms
class RelatedForm(RelatedEntityMixin["Form"], FilterMixin, Property["Form"]):
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
    _kind: str | None = "form"

    # Column Attributes
    _label = "Form"

    # Filter Attributes
    @property
    def filter_label(self) -> str | None:
        return self.value.name if self.value else None

    def filter_details(self, condition: Condition) -> dict[str, object]:
        details = super().filter_details(condition)
        details["label"] = "Form Attached"
        return details


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_model_project_form
# @matrix task : model related-entities
class AttachedModelTask(
    RelatedEntityMixin["ModelTask"], ColumnMixin, FilterMixin, AIMixin, DBProperty["ModelTask"]
):
    """The model task attached to an entity."""

    # Property Attributes
    _id = "model"
    _label = "Model Task"
    _icon = "model"
    _kind: str | None = "task"

    @property
    def filter_label(self) -> str | None:
        return self.value.name if self.value else None

    def filter_details(self, condition: Condition) -> dict[str, object]:
        details = super().filter_details(condition)
        details["label"] = "Model Task"
        return details


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_project
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_model_project_form
# @matrix project : model parent related-entities
class AttachedProject(
    RelatedEntityMixin["Project"], ColumnMixin, FilterMixin, AIMixin, DBProperty["Project"]
):
    """The project attached to an entity.

    Overrides:
        details_key: Returns "parent" for ModelTask entities.
    """

    # Property Attributes
    _id = "project"
    _label = "Project"
    _icon = "project"
    _kind: str | None = "project"

    # Details Attributes
    @property
    def details_key(self) -> str:
        if isinstance(self.entity, Entities.MODEL_TASK):
            return "parent"
        return "project"


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_related_entities_category_and_form
# @matrix category : parent related-entities
class AttachedCategory(
    RelatedEntityMixin["Category"], ColumnMixin, FilterMixin, AIMixin, DBProperty["Category"]
):
    """The category attached to an entity."""

    # Property Attributes
    _id = "category"
    _label = "Category"
    _icon = "category"
    _kind: str | None = "category"


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_history_attached_page_details_key_uses_parent
# @matrix tasks : attached-page history parent-details
class AttachedPage(
    RelatedEntityMixin[_Page], DetailsMixin, ColumnMixin, FilterMixin, AIMixin, DBProperty[_Page]
):
    """The page attached to an entity.

    Overrides:
        details_key: Returns "parent" for Task entities.
    """

    # Property Attributes
    _id = "page"
    _label = "Page"
    _icon = "page"
    _kind: str | None = "page"

    # Details Attributes
    @property
    def details_key(self) -> str:
        if self.entity.entity_kind in {"task", "task_history"}:
            return "parent"
        return "page"


# @testable true
# @tests tests_unit/test_004a_form_index.py::test_form_index_table
# @pair form-index:columns
class Categories(
    RelatedEntityListMixin["Category"], FilterMixin, ColumnMixin, Property[list["Category"]]
):
    """Categories that an entity is associated with (for column/filter display)."""

    # Property Attributes
    _id = "categories"
    _label = "Categories"
    _icon = "category"
    _kind: str | None = "category"

    # Filter Attributes
    _placeholder = "select a category..."
    _index = "category"
    multiple = True

    @property
    def filter_label(self) -> str | None:
        return "In Categories"

    @property
    def sort_value(self) -> dict[str, str | None]:
        return {entity.hash: entity.name for entity in self.value}


# @testable true
# @tests tests_unit/test_004a_form_index.py::test_form_index_table
# @pair form-index:columns
class Projects(
    RelatedEntityListMixin["Project"], FilterMixin, ColumnMixin, Property[list["Project"]]
):
    """Projects that an entity is associated with (for column/filter display)."""

    # Property Attributes
    _id = "projects"
    _label = "Projects"
    _icon = "project"
    _kind: str | None = "project"

    # Filter Attributes
    _placeholder = "select a project..."
    _index = "project"
    multiple = True

    @property
    def filter_label(self) -> str | None:
        return "In Projects"

    @property
    def sort_value(self) -> dict[str, str | None]:
        return {entity.hash: entity.name for entity in self.value}


class ModelTasks(RelatedEntityListMixin["ModelTask"], ColumnMixin, Property[list["ModelTask"]]):
    """Model tasks associated with an entity (for column display)."""

    # Property Attributes
    _id = "model_tasks"
    _label = "Model Tasks"
    _icon = "model"
    _kind: str | None = "model"


# @testable false
# @covered-by lagniappe/core/properties/common_related.py::RelatedForms.add
# @reason duplicate prevention and relation registration are owned by add()
class RelatedForms(RelatedEntityListMixin["Form"], DBProperty[list["Form"], "Category"]):
    """Additional forms related to an entity (beyond the primary attached form).

    Prevents duplicating the primary form. Adding a form also registers
    it as a related entity on the parent.
    """

    # Property Attributes
    _id = "forms"
    _label = "Form"
    _icon = "form"
    _kind: str | None = "form"

    @property
    def value(self) -> list[Form]:
        return self._read_related_list()

    @value.setter
    def value(self, value: list[Form] | None) -> None:
        if value is not None and not isinstance(value, list):
            raise TypeError("Value must be a list")
        for item in value or []:
            if not getattr(item, "key", None):
                raise ValueError("Value must have a key")
            if getattr(item, "entity_kind", None) != "form":
                raise ValueError("Value must be a form")

        self._write_related_list(value)

    # @testable true
    # @tests tests_unit/test_007_category_properties.py::test_related_forms_add_skips_primary_form_and_registers_relation
    # @tests tests_unit/test_007_category_properties.py::test_related_forms_add_rejects_value_without_key
    # @tests tests_unit/test_007_category_properties.py::test_related_forms_add_existing_key_does_not_load_other_forms
    # @matrix category form : add duplicate-primary related-forms relation-registration validation
    def add(self, value: Form) -> bool:
        key = getattr(value, "key", None)
        if not key:
            raise ValueError("Value must have a key")
        if getattr(value, "entity_kind", None) != "form":
            raise ValueError("Value must be a form")

        if key == self.entity.properties.form.key:
            return False

        # Ordinary Page saves re-register their attached form. Membership only
        # needs stored keys; unrelated form entities need not be loaded.
        if key in self.keys:
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
            self._cache_attached_entities()
            self._invalidate_projections()
            return True
        return False


# @testable false
# @covered-by lagniappe/core/properties/common_related.py::Groups.attach
# @reason inherited relation mechanics are exercised through local restriction attachment
class Groups(RelatedEntityListMixin["UserGroup"], DBProperty[list["UserGroup"], _GroupOwner]):
    """Groups that have access to a form."""

    _id = "groups"
    _label = "Groups"
    _icon = "group"
    _kind: str | None = "user"

    # @testable true
    # @tests tests_unit/test_002_entity_general_properties.py::test_direct_fetch_materializes_local_restrictions_from_attached_groups
    # @tests tests_unit/test_002_entity_general_properties.py::test_task_file_restrictions_use_stored_hashes_without_group_reads
    # @matrix permissions relations : attached-groups local-restrictions materialization stored-restrictions no-extra-read
    def attach(self, key_map: Mapping[Key, UserGroup]) -> None:
        super().attach(key_map)
        # With no Group references, the stored local hashes remain authoritative.
        if self.keys:
            self.entity.properties.restricted_to.materialize()
