from flask import url_for

from ..definitions import Action
from ..mixins import AssetMixin
from ..properties import common_assets, common_entity, project
from .entity import Entity
from .index import TaskIndex


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_project_update_sets_identity_description_and_attributes
# @features project
# @dimensions update
class Project(Entity, AssetMixin):
    entity_kind = "project"

    @property
    def exclude_from_index(self):
        return frozenset({"description"})

    @property
    def required(self):
        return ["models", self.hash]

    @property
    def url(self):
        return url_for("projects.view", key=self.urlsafe_key)

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "model_tasks": project.ModelTasks,
                "description": common_entity.Description,
                "document": common_assets.Document,
                "attributes": common_entity.Attributes,
                "filters": project.ProjectFilters,
                "is_public": common_entity.IsPublic,
                "public_id": common_entity.PublicID,
                "ai_generated": common_entity.AiGenerated,
            }
        )
        return properties

    @property
    def sync_ids(self):
        return {
            "document": {
                "id": self.properties.document.sync_id,
                "fingerprint": self.properties.document.fingerprint,
            },
        }

    def state(self, sync_id):
        if not self.allowed(Action.VIEW):
            return {}

        state = {
            "timestamp": self.modified.timestamp(),
            "ydoc": self.properties.document.ydoc,
            "fingerprint": self.properties.document.fingerprint,
        }
        if not state.get("ydoc") and self.properties.document.html:
            state["markup"] = self.properties.document.html

        return state

    def index(self, *args, **kwargs):
        return TaskIndex(*args, entity=self, **kwargs)

    @classmethod
    def create(cls, data):
        new_project = cls()
        new_project.kind = cls.entity_kind
        new_project.update(data)

        return new_project

    # @testable true
    # @tests tests_unit/test_005_project_properties.py::test_project_update_sets_identity_description_and_attributes
    # @features project
    # @dimensions update identity attributes description
    def update(self, data):
        self.name = data["name"]
        self.description = data.get("description")
        self.attributes = data.get("attributes")
