"""Project-related properties for model tasks and filtering."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from google.cloud.datastore import Key
    from ..entities.model_task import ModelTask
    from ..entities.project import Project

from ..definitions import Fetch
from ..entities import Entities
from ..mixins import (
    AIMixin,
    DetailsMixin,
    FilterMixin,
    RelatedEntityListMixin,
    RelatedEntityMixin,
)
from lagniappe.core.tools.database import get as database_get
from .base_db import DBProperty
from .base_property import Property
from .base_filters import Filters
from .common_related import AttachedForm, AttachedModelTask
from .common_entity import Name
from .task_dates import Completed, DueDate
from .task_related import AssignedTo, HasSignature, HasStatus, TaskCategories


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_model_tasks_load_attach_and_order_from_database
# @matrix project : db-load model-tasks ordering relation-attach
class ModelTasks(RelatedEntityListMixin["ModelTask"], Property[list["ModelTask"], "Project"]):
    """Model tasks (workflow stages) belonging to a project.

    Lazy-loaded from the database on first access. Each model task
    is attached to this project entity.

    Get:
        value (list): ModelTask entities for this project.
    """

    # Property Attributes
    _value: object
    _id = "model_tasks"
    _label = "Models"

    @property
    def value(self) -> list[ModelTask]:  # pyright: ignore[reportIncompatibleMethodOverride] -- Membership is changed through add or attach.
        if self.is_set:
            return cast("list[ModelTask]", self._value)

        model_tasks = Entities.fetch(
            *database_get.model_tasks(self.entity),
            self.entity,
            request=Fetch.direct(),
        )

        self._value = [m for m in model_tasks if isinstance(m, Entities.MODEL_TASK)]
        self._cache_attached_entities()
        return self._value

    # Entity Attributes
    def add(self, model: ModelTask) -> None:  # pyright: ignore[reportIncompatibleMethodOverride] -- This override retains its public model keyword.
        models = self.value
        if model and model.key not in [m.key for m in models]:
            model.order = max([len(models), *(m.order or 0 for m in models)]) + 1
            models.append(model)
            self._cache_attached_entities()
            self._invalidate_projections()

    def attach(self, key_map: Mapping[Key, ModelTask]) -> None:
        if self.is_set:
            models = cast("list[ModelTask]", self._value)
            self._value = [key_map.get(cast("Key", model.key), model) for model in models]
            self._cache_attached_entities()
            self._invalidate_projections()


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_filters
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_project_filter_conditions_include_task_fields
# @matrix filters project : completed conditions entity-fields filter-value
class ProjectFilters(Filters["Project"]):
    def __init__(self, *args: object, entity: Project | None = None, **kwargs: object) -> None:
        super().__init__(*args, entity=entity, **kwargs)
        self.filter_kind = "task"
        self.filter_fields = [
            Name,
            TaskCategories,
            AssignedTo,
            DueDate,
            Completed,
            HasSignature,
            HasStatus,
        ]

    @property
    def entity_fields(self) -> dict[str, FilterMixin]:
        if self._entity_fields is not None:
            return self._entity_fields

        self._entity_fields = {}
        for model in self.entity.model_tasks:
            model_field = AttachedModelTask(entity=self.entity)
            model_field.value = model
            self._entity_fields[model.hash] = model_field
            if model.form:
                form_field = AttachedForm(entity=model)
                form_field.value = model.form
                self._entity_fields[model.form.hash] = form_field

        return self._entity_fields


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_model_task_project_parent_details_and_attach
# @matrix project : attach details model-task-parent
class ModelTaskProject(
    RelatedEntityMixin["Project"], DetailsMixin, FilterMixin, AIMixin, DBProperty["Project"]
):
    """Parent project for a ModelTask entity.

    ModelTasks are children of projects and inherit their permissions.
    Resolved from the stored project relation key.

    Set:
        value (Entity): The Project entity.

    Get:
        value (Entity): The Project entity.

    Overrides:
        details_key: Returns "parent" for the details API.
    """

    # Property Attributes
    _id = "project"
    _label = "Project"

    # Details Attributes
    @property
    def details_key(self) -> str:
        return "parent"


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_get_entity_returns_model_task_form_schema_for_ai_autofill
# @matrix ai form-schema : attached-form model-task schema
class ModelTaskForm(AttachedForm, DetailsMixin):
    """The form attached to a model task.

    Set:
        value (Entity): Form entity.

    Get:
        value (Entity): Form entity.

    Overrides:
        filter_label: Returns the form's name.
    """

    # Property Attributes
    _id = "form"
    _label = "Form"
    _icon = "form"
    _kind = "form"
