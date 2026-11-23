from typing import TYPE_CHECKING, Self, TypedDict, cast

from ..properties import project
from ..exceptions import PropertyError
from ..tools.database.get import urlsafe_key
from .entity import Entity, EntityProperties


if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from . import property_types
    from .form import Form
    from .project import Project


class ModelTaskData(TypedDict, total=False):
    name: str | None
    form: Form | None


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_model_task_entity_create_update_order_and_save_relations
# @tests tests_unit/test_005_project_properties.py::test_model_task_access_is_independent_of_attached_form_restrictions
# @matrix model-task permissions project : attached-form create ordering relation-save restricted-access update
class ModelTask(Entity):
    if TYPE_CHECKING:
        project: Project | None
        form: Form | None

        @property
        def properties(self) -> property_types.ModelTaskProperties: ...

    entity_kind = "model"

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_model_task_reference_retains_project_without_loading_relations
    # @pair model-task:reference-links
    @property
    def reference_details(self) -> dict[str, object]:
        details = super().reference_details
        project = self.properties.project
        if project.key:
            details["parent"] = (
                project.value.reference_details
                if project.is_set and project.value
                else {"id": urlsafe_key(project.key), "kind": "project"}
            )
        return details

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_model_task_required_reports_unloaded_project_relation
    # @matrix requires : unloaded-relation validation
    @property
    def required(self) -> list[str]:
        project = self.project
        if not project:
            raise PropertyError(
                "ModelTask.required requires a loaded project relation",
                entity=self,
            )
        return ["models", self.hash, project.hash]

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "form": project.ModelTaskForm,
                "project": project.ModelTaskProject,
            }
        )
        return properties

    @property
    def order(self) -> int | None:
        return cast("int | None", self.db.get("order"))

    @order.setter
    def order(self, value: int | str) -> None:
        self.db["order"] = int(value)

    # @testable true
    # @tests tests_unit/test_032h_report_batches.py::test_create_key_batches_are_bounded_and_keep_parent_groups_separate
    # @matrix ai-report : id-allocation parent
    @classmethod
    def create(cls, project: Project, data: ModelTaskData, *, key: Key | None = None) -> Self:
        new_task = cls(key, parent=project)
        new_task.project = project
        new_task.kind = cls.entity_kind

        project.properties.model_tasks.add(new_task)

        new_task.update(data)
        return new_task

    def update(self, data: ModelTaskData) -> None:
        self.name = data.get("name")
        self.form = data.get("form")
