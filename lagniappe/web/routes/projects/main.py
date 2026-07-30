from flask import abort, request

from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, filters
from lagniappe.core.definitions import (
    AI,
    Action,
    MutationIntent,
    ProjectAttributes,
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
# @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_project_viewer_sees_document_tab_only_when_content_exists
# @features projects
# @dimensions navigate load permission-gates readonly document-tab
@projects.route("/<key>", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def view(key, **kwargs):
    project = kwargs["entity"]
    filters.FilterCache(project).update()

    return responses.project_view(project)


# @testable true
# @tests tests_e2e/004_projects/test_004b_info.py::test_project_revision_notice_only_resets_changed_form
# @features edited-entity-notice projects
# @dimensions replacement info-form side-effect-free timestamp-only formdata staged-reset no-reload dirty-state
@projects.route("/<key>/info/replace", methods=["GET"])
@permission(Resource.PROJECT, Action.VIEW)
def info(key, **kwargs):
    return responses.project_info(kwargs["entity"])


# @testable true
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_without_tasks
# @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_without_document
# @features projects
# @dimensions attribute-model-tasks attribute-document
def create_update_data(form):
    return {
        "name": form.get("name"),
        "description": form.get("description"),
        "attributes": [a.name for a in ProjectAttributes if form.get(a.name)],
    }


# @testable true
# @tests tests_e2e/004_projects/test_004b_info.py::test_project_info_form
# @tests tests_e2e/004_projects/test_004b_info.py::test_toggle_tasks_attribute
# @tests tests_e2e/004_projects/test_004b_info.py::test_toggle_document_attribute
# @features projects
# @dimensions update info-form attribute-model-tasks attribute-document
@projects.route("<key>/update", methods=["PUT"])
@permission(Resource.PROJECT, Action.EDIT)
def update(key, **kwargs):
    project = kwargs["entity"]

    old_attributes = [a.name for a in project.attributes if project.has(a.name)]
    update_data = create_update_data(request.form)
    project.update(update_data)
    new_attributes = [a.name for a in project.attributes if project.has(a.name)]

    Entities.save(project, *project.model_tasks)

    if set(old_attributes) != set(new_attributes):
        return responses.json_response({"reload": True})
    else:
        return responses.project_info(project)


# @testable false
# @covered-by lagniappe/web/routes/projects/main.py::set_attribute
# @reason attribute-set persistence is owned by the project attribute endpoint
def _set_project_attribute(project, attribute, active):
    active_attributes = {
        item.name for item in project.attributes if project.has(item.name)
    }
    if active:
        active_attributes.add(attribute)
    else:
        active_attributes.discard(attribute)
    project.attributes = [
        item.name for item in project.attributes if item.name in active_attributes
    ]


# @testable true
# @tests tests_e2e/004_projects/test_004b_info.py::test_toggle_tasks_attribute
# @tests tests_e2e/004_projects/test_004b_info.py::test_toggle_document_attribute
# @features projects
# @dimensions attributes-live-toggle attribute-model-tasks attribute-document no-reload
@projects.route("<key>/attributes/<attribute>", methods=["PUT"])
@permission(Resource.PROJECT, Action.EDIT)
def set_attribute(key, attribute, **kwargs):
    if attribute not in ProjectAttributes.__members__:
        abort(404)

    project = kwargs["entity"]
    data = request.get_json(silent=True) or {}
    active = bool(data.get("active"))

    _set_project_attribute(project, attribute, active)
    Entities.save(project, *project.model_tasks)

    return responses.entity_response(
        responses.json_response({"attribute": attribute, "active": active}),
        project,
    )


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
# @features projects
# @dimensions create-manual ai-create explain-button
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
                form = Entities.FORM.create(model_task.get("form_data"))
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
# @features projects
# @dimensions delete
@projects.route("<key>/delete", methods=["DELETE"])
@permission(Resource.PROJECT, Action.DELETE)
def delete(key, **kwargs):
    project = kwargs["entity"]
    if not project:
        return responses.not_found("project not found")

    Entities.delete(project)

    return responses.ok()
