from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities.model_task import ModelTaskData
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack
    from werkzeug.datastructures import MultiDict

from flask import request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.core.tools.filters import compile_filter_contract
from lagniappe.core.tools.entity_patches import prepare_patch
from lagniappe.core.tools.tasks.ordering import sort_tasks
from lagniappe.core.definitions import Action, Fetch, FetchReason, Resource
from lagniappe.web.auth import authenticated_user, permission
from lagniappe.web import responses

from . import projects


def create_update_data(
    form: MultiDict[str, str], model_task: models.ModelTask | None = None
) -> ModelTaskData:
    form_id = form.get("form")
    current_form = model_task.form if model_task else None
    selected_form = SubmittedReferenceResolver(authenticated_user(), form_id).one(
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
    data: ModelTaskData = {
        "name": form.get("name"),
        "form": selected_form,
    }
    return data


def _project_model(
    project: models.Project, task_key: str, *, from_stage_list: bool = False
) -> models.ModelTask | None:
    reference: str | models.ModelTask = task_key
    if from_stage_list:
        key = database_get.datastore_key(task_key)
        if key is None:
            return None
        stage = next((model for model in project.model_tasks if model.key == key), None)
        if stage is None:
            return None
        reference = stage
    try:
        return SubmittedReferenceResolver(authenticated_user(), reference).one(
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


@projects.route("<key>/create-model", methods=["POST"])
@permission(Resource.PROJECT, Action.EDIT)
def create_model(
    key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    try:
        update_data = create_update_data(request.form)
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    model_task = Entities.MODEL_TASK.create(project, update_data)

    model_task.save()

    return responses.new_model_task(model_task)


@projects.route("<key>/models/<task_key>/replace", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def model_info(
    key: str, task_key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    model_task = _project_model(project, task_key)
    if not model_task:
        return responses.not_found("Model task not found")

    return responses.new_model_task(model_task)


@projects.route("<key>/update-model/<task_key>", methods=["PUT"])
@permission(Resource.PROJECT, Action.EDIT)
def update_model(
    key: str, task_key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
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


@projects.route("<key>/reorder-models", methods=["PUT"])
@permission(Resource.PROJECT, Action.EDIT)
def reorder_models(
    key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    data = request.get_json(silent=True)
    references = data.get("model_tasks") if isinstance(data, dict) else None
    if not isinstance(references, list) or not all(isinstance(ref, str) for ref in references):
        return responses.error("Model ordering must be a list of model task references.")
    models_by_key = {model.urlsafe_key: model for model in project.model_tasks}
    if any(ref not in models_by_key for ref in references):
        return responses.error("Model task not found in this Project.")
    try:
        prepared = prepare_patch(project, {"model_tasks": [models_by_key[ref] for ref in references]}, authenticated_user())
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    changed = [model for model in prepared.writes[1:] if model.order != models_by_key[model.urlsafe_key].order]
    if changed:
        Entities.save(*changed)
    return responses.entity_response(
        responses.json_response({"model_tasks": references}), project, *changed,
    )


@projects.route("<key>/delete-model/<task_key>", methods=["DELETE"])
@permission(Resource.PROJECT, Action.EDIT)
def delete_model(
    key: str, task_key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    model_task = _project_model(project, task_key)
    if not model_task:
        return responses.not_found("Model task not found")

    updated_tasks = []
    removed_order = model_task.order
    for sibling in project.model_tasks:
        order = sibling.order
        if isinstance(order, int) and isinstance(removed_order, int) and order > removed_order:
            sibling.order = order - 1
            updated_tasks.append(sibling)

    Entities.delete(model_task)
    Entities.save(project, *updated_tasks)

    return responses.ok()


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


@projects.route("<key>/status/<task_key>", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def status(
    key: str, task_key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    model = _project_model(project, task_key, from_stage_list=True)
    if not model:
        return responses.not_found("Model task not found")
    completed = request.args.get("completed") == "true"
    filter = _status_filter(project, model, completed)

    db = database_get.tasks(
        model=model,
        completed=completed,
        hashes=current_user.properties.restrictions.task,
        limit=None,
    )
    cached = Entities.fetch(
        *db.results,
        request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
    )
    filter.route = request.full_path.removesuffix("?")

    tasks = sort_tasks([task for task in cached if isinstance(task, Entities.TASK)])
    return responses.filtered_task_index(tasks, filter)
