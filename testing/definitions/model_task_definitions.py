from dataclasses import dataclass
from typing import Optional

from .forms import Forms
from .projects import Projects


@dataclass
class ModelTaskDefinition:
    name: str
    project: Projects
    description: str = ""
    form: Optional[Forms] = None


create_model_task = ModelTaskDefinition(
    name="Test Model Task",
    project=Projects.test_create_project_manual_mode,
)

create_model_task_with_form = ModelTaskDefinition(
    name="Test Model Task with Form",
    project=Projects.test_create_project_manual_mode,
    form=Forms.test_create_task_form,
)

edit_model_task_name = ModelTaskDefinition(
    name="Model Task Name Edit",
    project=Projects.test_create_project_manual_mode,
)

change_model_task_form = ModelTaskDefinition(
    name="Model Task Form Change",
    project=Projects.test_create_project_manual_mode,
    form=Forms.test_create_task_form,
)

delete_model_task_form = ModelTaskDefinition(
    name="Model Task Form Delete",
    project=Projects.test_create_project_manual_mode,
    form=Forms.test_create_task_form,
)

delete_model_task = ModelTaskDefinition(
    name="Model Task to Delete",
    project=Projects.test_create_project_manual_mode,
)

multi_model_task_alpha = ModelTaskDefinition(
    name="Alpha Stage",
    project=Projects.test_page_tasks_multi_model,
)

multi_model_task_beta_with_form = ModelTaskDefinition(
    name="Beta Stage",
    project=Projects.test_page_tasks_multi_model,
    form=Forms.test_create_task_form,
)

filter_model_task = ModelTaskDefinition(
    name="Filter Stage",
    project=Projects.test_filter_project,
)

status_filter_model_task = ModelTaskDefinition(
    name="Status Filter Stage",
    project=Projects.test_filter_project,
)

filter_model_task_with_form = ModelTaskDefinition(
    name="Filter Form Stage",
    project=Projects.test_filter_project,
    form=Forms.test_project_filter_task_form,
)

filter_model_task_with_status_form = ModelTaskDefinition(
    name="Filter Status Form Stage",
    project=Projects.test_filter_project,
    form=Forms.test_task_status_form,
)
