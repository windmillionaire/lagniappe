from flask import request

from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, filters
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


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_manual_mode
# @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_project_is_forbidden_without_model_permission
# @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_project_viewer_reads_project_without_editing_controls
# @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_project_viewer_can_read_document_content
# @matrix projects : document-tab load navigate permission-gates readonly
@projects.route("/<key>", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def view(key, **kwargs):
    project = kwargs["entity"]
    filters.FilterCache(project).update()

    return responses.project_view(project)


# @testable true
# @tests tests_e2e/004_projects/test_004b_info.py::test_project_info_replacement_is_side_effect_free_for_timestamp_only_revision
# @tests tests_e2e/004_projects/test_004b_info.py::test_project_revision_notice_only_resets_changed_form
# @matrix edited-entity-notice projects : dirty-state info-form no-reload replacement side-effect-free staged-reset timestamp-only
@projects.route("/<key>/info/replace", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def info(key, **kwargs):
    return responses.project_info(kwargs["entity"])


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_manual_mode
# @matrix projects : create-manual
def create_update_data(form):
    return {
        "name": form.get("name"),
        "description": form.get("description"),
    }


# @testable true
# @tests tests_e2e/004_projects/test_004b_info.py::test_project_info_form
# @matrix projects : info-form update
@projects.route("<key>/update", methods=["PUT"])
@permission(Resource.PROJECT, Action.EDIT)
def update(key, **kwargs):
    project = kwargs["entity"]

    update_data = create_update_data(request.form)
    project.update(update_data)

    Entities.save(project, *project.model_tasks)

    return responses.project_info(project)


# @testable false
# @covered-by lagniappe/web/routes/projects/main.py::create
# @reason AI response shaping is exercised through the project create route
def _create_project(generated_data):
    project_data = {
        "name": generated_data.get("project_name"),
        "description": generated_data.get("project_description"),
        "model_tasks": [],
    }

    for model_task in generated_data.get("model_tasks"):
        new_model_task_data = {
            "name": model_task.get("name"),
        }
        project_data["model_tasks"].append(new_model_task_data)

        if model_task.get("form_schema"):
            new_model_task_data["form_data"] = {
                "name": model_task.get("name"),
                "schema": model_task.get("form_schema"),
                "form-type": "task",
            }

    return project_data


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_manual_mode
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_ai_mode
# @matrix projects : ai-create create-manual explain-button
@projects.route("/create", methods=["POST"])
@permission(Resource.PROJECTS, Action.CREATE)
def create():
    generate = request.form.get("generate")
    explain = request.form.get("role") == "explain"

    if generate:
        require_ai_access(AI.CREATE)
        prompt = ai.project_creation_prompt(request.form.get("user_description"))
        if explain:
            return responses.explain(prompt)

        try:
            generated_data = ai.generate_project(prompt)
        except (exceptions.AIException, Exception) as e:
            return responses.error(str(e), exception=e)

        project_data = _create_project(generated_data)
        new_project = Entities.PROJECT.create(project_data)
        new_project.ai_generated = True

        for model_task in project_data.get("model_tasks"):
            new_model_task = Entities.MODEL_TASK.create(new_project, model_task)
            new_project.add_mutation_intents(
                MutationIntent.standard(
                    new_model_task,
                    reason="generated-project-model-task",
                )
            )
            if model_task.get("form_data"):
                form_data = model_task.get("form_data")
                form = Entities.FORM.create(
                    {
                        "name": form_data.get("name"),
                        "form-type": form_data.get("form-type"),
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


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_delete_project
# @pair projects:delete
@projects.route("<key>/delete", methods=["DELETE"])
@permission(Resource.PROJECT, Action.DELETE)
def delete(key, **kwargs):
    project = kwargs["entity"]
    if not project:
        return responses.not_found("project not found")

    Entities.delete(project)

    return responses.ok()
