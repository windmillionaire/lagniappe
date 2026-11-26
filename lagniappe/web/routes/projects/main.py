from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack
    from werkzeug.datastructures import MultiDict

from lagniappe.core.entities.project import ProjectData
from lagniappe.core.entities.model_task import ModelTaskData

from flask import abort, jsonify, request

from lagniappe.core.entities import Entities
from lagniappe.core.tools import filters
from lagniappe.core.tools.ai import project as ai_project
from lagniappe.core.definitions import (
    AI,
    Action,
    MutationIntent,
    Resource,
)
from lagniappe.core import exceptions
from lagniappe.web.auth import permission, require_ai_access
from lagniappe.web import responses

from . import projects


@projects.route("/<key>", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def view(
    key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    if not isinstance(project, Entities.PROJECT):
        abort(404)
    filters.FilterCache(project).update()

    return responses.project_view(project)


@projects.route("/<key>/info/replace", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def info(
    key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    return responses.project_info(kwargs["entity"])


def create_update_data(form: MultiDict[str, str]) -> ProjectData:
    return {
        "name": form.get("name"),
        "description": form.get("description"),
    }


@projects.route("<key>/update", methods=["PUT"])
@permission(Resource.PROJECT, Action.EDIT)
def update(
    key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]

    update_data = create_update_data(request.form)
    project.update(update_data)

    Entities.save(project, *project.model_tasks)

    return responses.project_info(project)


@projects.route("/<key>/patch", methods=["PATCH"])
@permission(Resource.PROJECT, Action.EDIT)
def patch(
    key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return responses.bad_request("Invalid project patch payload")

    schema_id = payload.get("schema_id")
    value = payload.get("value")

    if schema_id == "name":
        data: ProjectData = {
            "name": str(value) if value is not None else "",
            "description": project.description,
        }
    elif schema_id == "description":
        data = {
            "name": project.name,
            "description": str(value) if value is not None else "",
        }
    else:
        return responses.bad_request(f"Unsupported project field '{schema_id}'")

    try:
        project.update(data)
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    Entities.save(project, *project.model_tasks)

    return responses.entity_response(
        (
            jsonify(
                {
                    "name": project.name,
                    "description": project.description or "",
                    "fingerprint": project.fingerprint,
                }
            ),
            200,
        ),
        project,
        *project.model_tasks,
    )


class _GeneratedForm(TypedDict):
    name: str | None
    schema: object
    form_type: str


class _GeneratedModelTask(ModelTaskData, total=False):
    form_data: _GeneratedForm


class _GeneratedProject(ProjectData):
    model_tasks: list[_GeneratedModelTask]


def _create_project(generated_data: ai_project.GeneratedProject) -> _GeneratedProject:
    project_data: _GeneratedProject = {
        "name": generated_data.get("project_name"),
        "description": generated_data.get("project_description"),
        "model_tasks": [],
    }

    for model_task in generated_data.get("model_tasks"):
        new_model_task_data: _GeneratedModelTask = {
            "name": model_task.get("name"),
        }
        project_data["model_tasks"].append(new_model_task_data)

        if model_task.get("form_schema"):
            new_model_task_data["form_data"] = {
                "name": model_task.get("name"),
                "schema": model_task.get("form_schema"),
                "form_type": "task",
            }

    return project_data


@projects.route("/create", methods=["POST"])
@permission(Resource.PROJECTS, Action.CREATE)
def create() -> ResponseReturnValue:
    generate = request.form.get("generate")
    if request.form.get("role") == "explain" or request.form.get("explain"):
        return responses.error("Initial Prompt is no longer available.")

    if generate:
        require_ai_access(AI.CREATE)
        prompt = ai_project.project_creation_prompt(request.form.get("user_description") or "")
        try:
            generated_data = ai_project.generate_project(prompt)
        except (exceptions.AIException, Exception) as e:
            return responses.error(str(e), exception=e)

        project_data = _create_project(generated_data)
        new_project = Entities.PROJECT.create(project_data)
        new_project.ai_generated = True

        for model_task in project_data.get("model_tasks") or []:
            new_model_task = Entities.MODEL_TASK.create(new_project, model_task)
            new_project.add_mutation_intents(
                MutationIntent.standard(
                    new_model_task,
                    reason="generated-project-model-task",
                )
            )
            if form_data := model_task.get("form_data"):
                form = Entities.FORM.create(
                    {
                        "name": form_data.get("name"),
                        "form-type": form_data["form_type"],
                    }
                )
                form.properties.schema.validate_ai(form_data.get("schema"))
                new_model_task.form = form
                new_project.add_mutation_intents(
                    MutationIntent.standard(
                        form,
                        reason="generated-project-model-task-form",
                    )
                )

    else:
        new_project = Entities.PROJECT.create(create_update_data(request.form))

    new_project.save()

    return responses.new_project(new_project)


@projects.route("<key>/delete", methods=["DELETE"])
@permission(Resource.PROJECT, Action.DELETE)
def delete(
    key: str, **kwargs: Unpack[EntityContext[models.Project]]
) -> ResponseReturnValue:
    project = kwargs["entity"]
    if not project:
        return responses.not_found("project not found")

    Entities.delete(project)

    return responses.ok()
