from typing import TYPE_CHECKING, Required, Self, TypedDict, Unpack

from flask import url_for

from ..definitions import Action
from ..mixins import AssetMixin
from ..properties import common_assets, common_entity, project
from .entity import Entity, EntityProperties
from .index import CollectionOptions, TaskIndex


if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from . import property_types
    from .model_task import ModelTask


class ProjectData(TypedDict, total=False):
    name: Required[str | None]
    description: str | None


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_update_sets_identity_and_description
# @pair project:update
class Project(Entity, AssetMixin):
    if TYPE_CHECKING:
        description: str | None

        @property
        def filters(self) -> project.ProjectFilters: ...

        model_tasks: list[ModelTask]

        @property
        def properties(self) -> property_types.ProjectProperties: ...

    entity_kind = "project"
    retired_fields = frozenset({"attributes"})

    @property
    def exclude_from_index(self) -> frozenset[str]:
        return frozenset({"description"})

    @property
    def required(self) -> list[str]:
        return ["models", self.hash]

    @property
    def url(self) -> str:
        return url_for("projects.view", key=self.urlsafe_key)

    def _get_properties(self) -> EntityProperties:
        properties = super()._get_properties()
        properties.update(
            {
                "model_tasks": project.ModelTasks,
                "description": common_entity.Description,
                "document": common_assets.Document,
                "filters": project.ProjectFilters,
                "is_public": common_entity.IsPublic,
                "public_id": common_entity.PublicID,
                "ai_generated": common_entity.AiGenerated,
            }
        )
        return properties

    @property
    def sync_ids(self) -> dict[str, dict[str, str | None]]:
        return {
            "document": {
                "id": self.properties.document.sync_id,
                "fingerprint": self.properties.document.fingerprint,
            },
        }

    def state(self, sync_id: str) -> dict[str, object]:
        if not self.allowed(Action.VIEW):
            return {}

        modified = self.modified
        if modified is None:
            raise AttributeError("The project has no modification timestamp")
        state: dict[str, object] = {
            "timestamp": modified.timestamp(),
            "ydoc": self.properties.document.ydoc,
            "fingerprint": self.properties.document.fingerprint,
        }
        if not state.get("ydoc") and self.properties.document.html:
            state["markup"] = self.properties.document.html

        return state

    def index(self, *args: object, undated: bool = False, **kwargs: Unpack[CollectionOptions]) -> TaskIndex:
        return TaskIndex(*args, entity=self, undated=undated, **kwargs)

    # @testable true
    # @tests tests_unit/test_032h_report_batches.py::test_dependent_creations_share_one_commit
    # @matrix ai-report : batching identity dependencies
    @classmethod
    def create(cls, data: ProjectData, *, key: Key | None = None) -> Self:
        new_project = cls(key)
        new_project.kind = cls.entity_kind
        new_project.properties.model_tasks._value = []
        new_project.update(data)

        return new_project

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_update_sets_identity_and_description
    # @matrix project : description identity update
    def update(self, data: ProjectData) -> None:
        self.name = data["name"]
        self.description = data.get("description")
