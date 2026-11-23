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


class ModelTask(Entity):
    if TYPE_CHECKING:
        project: Project | None
        form: Form | None

        @property
        def properties(self) -> property_types.ModelTaskProperties: ...

    entity_kind = "model"

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
