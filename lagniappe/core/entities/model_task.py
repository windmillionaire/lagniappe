from ..properties import common_entity, project
from ..exceptions import PropertyError
from .entity import Entity


# @testable true
# @tests tests_unit/test_005_project_properties.py::test_model_task_entity_create_update_order_and_save_relations
# @tests tests_unit/test_005_project_properties.py::test_model_task_allowed_inherits_attached_form_restrictions
# @matrix model-task project : attached-form create ordering relation-save restricted-access update
class ModelTask(Entity):
    entity_kind = "model"

    # @testable true
    # @tests tests_unit/test_006b_ingress_entity.py::test_model_task_required_reports_unloaded_project_relation
    # @matrix requires : unloaded-relation validation
    @property
    def required(self):
        project = self.project
        if not project:
            raise PropertyError(
                "ModelTask.required requires a loaded project relation",
                entity=self,
            )
        return ["models", self.hash, project.hash]

    def _get_properties(self):
        properties = super()._get_properties()
        properties.update(
            {
                "form": project.ModelTaskForm,
                "project": project.ModelTaskProject,
                "restricted_to": common_entity.RestrictedTo,
            }
        )
        return properties

    @property
    def order(self):
        return self.db.get("order", None)

    @order.setter
    def order(self, value):
        self.db["order"] = int(value)

    @classmethod
    def create(cls, project, data):
        new_task = cls(parent=project)
        new_task.project = project
        new_task.kind = cls.entity_kind

        project.properties.model_tasks.add(new_task)

        new_task.update(data)
        return new_task

    def update(self, data):
        self.name = data.get("name")
        self.form = data.get("form")
