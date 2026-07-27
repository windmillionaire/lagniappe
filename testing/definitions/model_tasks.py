from enum import Enum

from ..resources import ModelTask

from . import model_task_definitions as mtd


class ModelTasks(Enum):
    test_create_model_task = ModelTask(definition=mtd.create_model_task)
    test_create_model_task_with_form = ModelTask(
        definition=mtd.create_model_task_with_form
    )
    test_edit_model_task_name = ModelTask(definition=mtd.edit_model_task_name)
    test_change_model_task_form = ModelTask(definition=mtd.change_model_task_form)
    test_delete_model_task_form = ModelTask(definition=mtd.delete_model_task_form)
    test_delete_model_task = ModelTask(definition=mtd.delete_model_task)
    test_multi_model_alpha = ModelTask(definition=mtd.multi_model_task_alpha)
    test_multi_model_beta_with_form = ModelTask(
        definition=mtd.multi_model_task_beta_with_form
    )

    # Project filter tests
    test_filter_by_model_task = ModelTask(definition=mtd.filter_model_task)
    test_status_filter_model_task = ModelTask(
        definition=mtd.status_filter_model_task
    )
    test_filter_by_attached_form = ModelTask(
        definition=mtd.filter_model_task_with_form
    )
    test_filter_by_status_form = ModelTask(
        definition=mtd.filter_model_task_with_status_form
    )

    def get(self, user, create=True):
        self.value.user = user
        if not self.value.entity and create:
            return self.value.create()
        if self.value.entity:
            project = self.value.project
            if project.entity:
                self.value.entity.project = project.entity
        return self.value
