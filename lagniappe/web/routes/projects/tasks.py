from flask import request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.core.tools.filters import compile_filter_contract
from lagniappe.core.tools.tasks.ordering import sort_tasks
from lagniappe.core.definitions import Action, Fetch, Resource
from lagniappe.web.auth import permission
from lagniappe.web import responses

from . import projects


# @testable false
# @covered-by lagniappe/web/routes/projects/tasks.py::create_model
# @covered-by lagniappe/web/routes/projects/tasks.py::update_model
# @reason form parsing helper owned by model-task create/update routes
def create_update_data(form, model_task=None):
    form_id = form.get("form")
    current_form = model_task.form if model_task else None
    selected_form = SubmittedReferenceResolver(current_user, form_id).one(
        form_id,
        expected=Entities.FORM,
        action=Action.VIEW,
        existing=current_form,
        predicate=lambda candidate: candidate.form_type == "task",
    )
    if not form_id and current_form and not current_form.allowed(
        Action.VIEW, user=current_user
    ):
        selected_form = current_form
    data = {
        "name": form.get("name"),
        "form": selected_form,
    }
    return data


# @testable false
# @covered-by lagniappe/web/routes/projects/tasks.py::update_model
# @covered-by lagniappe/web/routes/projects/tasks.py::delete_model
# @covered-by lagniappe/web/routes/projects/tasks.py::status
# @reason route-scoped model resolution is exercised through model-task routes
def _project_model(project, task_key):
    try:
        return SubmittedReferenceResolver(current_user, task_key).one(
            task_key,
            expected=Entities.MODEL_TASK,
            action=Action.VIEW,
            predicate=lambda candidate: bool(
                candidate.project and candidate.project.key == project.key
            ),
            required=True,
        )
    except exceptions.ValidationError:
        return None


# @testable true
# @tests tests_e2e/004_projects/test_004a_project.py::test_create_model_task
# @tests tests_e2e/004_projects/test_004a_project.py::test_create_model_task_with_form
# @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_create_model_form_opens_from_model_tasks_section
# @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_project_editor_can_open_model_task_creation
# @features model-tasks
# @dimensions create attach-form permission-gates
@projects.route("<key>/create-model", methods=["POST"])
@permission(Resource.PROJECT, Action.EDIT)
def create_model(key, **kwargs):
    project = kwargs["entity"]
    try:
        update_data = create_update_data(request.form)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    model_task = Entities.MODEL_TASK.create(project, update_data)

    model_task.save()

    return responses.new_model_task(model_task)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::new_model_task
@projects.route("<key>/models/<task_key>/replace", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def model_info(key, task_key, **kwargs):
    project = kwargs["entity"]
    model_task = _project_model(project, task_key)
    if not model_task:
        return responses.not_found("Model task not found")

    return responses.new_model_task(model_task)


# @testable true
# @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_edit_model_task_name
# @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_change_model_task_form
# @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_delete_model_task_form
# @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_model_task_mutations_require_route_project_membership
# @features model-tasks
# @dimensions update name form-change form-clear parent-membership
@projects.route("<key>/update-model/<task_key>", methods=["PUT"])
@permission(Resource.PROJECT, Action.EDIT)
def update_model(key, task_key, **kwargs):
    project = kwargs["entity"]
    model_task = _project_model(project, task_key)
    if not model_task:
        return responses.not_found("Model task not found")

    try:
        data = create_update_data(request.form, model_task=model_task)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    model_task.update(data)

    model_task.save()

    return responses.new_model_task(model_task)


# @testable true
# @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_delete_model_task
# @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_model_task_mutations_require_route_project_membership
# @features model-tasks
# @dimensions delete parent-membership
@projects.route("<key>/delete-model/<task_key>", methods=["DELETE"])
@permission(Resource.PROJECT, Action.EDIT)
def delete_model(key, task_key, **kwargs):
    project = kwargs["entity"]
    model_task = _project_model(project, task_key)
    if not model_task:
        return responses.not_found("Model task not found")

    updated_tasks = [t for t in project.model_tasks if t.order > model_task.order]
    for t in updated_tasks:
        t.order -= 1

    Entities.delete(model_task)
    Entities.save(project, *updated_tasks)

    return responses.ok()


# @testable false
# @covered-by lagniappe/web/routes/projects/tasks.py::status
# @reason temporary filter construction is exercised through the model-task status route
def _status_filter(project, model, completed):
    compiled = compile_filter_contract(
        project,
        {
            "version": 1,
            "conditions": [
                {
                    "source_id": project.hash,
                    "field": "model",
                    "comparator": "eq",
                    "values": [model.hash],
                },
                {
                    "source_id": project.hash,
                    "field": "completed",
                    "comparator": "is_true" if completed else "is_false",
                    "values": [],
                },
            ],
        },
        current_user,
    )
    filter = Entities.FILTER.create(project, compiled, temporary=True)
    # identifier = f"{project.hash}-{model.hash}-{status_value}"
    # filter.hash = utility.short_hash(identifier)

    if model.form:
        filter.properties.table.update_fields(model.form.fields)

    return filter


# @testable true
# @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_completed_button
# @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_in_progress_button
# @features model-tasks
# @dimensions status-filter completed in-progress
@projects.route("<key>/status/<task_key>", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def status(key, task_key, **kwargs):
    project = kwargs["entity"]
    model = _project_model(project, task_key)
    if not model:
        return responses.not_found("Model task not found")
    completed = True if request.args.get("completed") == "true" else False
    filter = _status_filter(project, model, completed)

    db = database.get.tasks(
        model=model,
        completed=completed,
        hashes=current_user.properties.restrictions.task,
        limit=None,
    )
    cached = Entities.fetch(*db.results, request=Fetch.direct())
    filter.route = request.path

    return responses.filtered_task_index(sort_tasks(cached), filter)
