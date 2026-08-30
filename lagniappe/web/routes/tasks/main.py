import json

from flask import abort, request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    Fetch,
    FetchReason,
    FileConsumer,
    FileConsumerLimitError,
    Resource,
    enforce_file_consumer,
)
from lagniappe.core.entities import Entities, index
from lagniappe.core.tools import ai
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools import collaboration
from lagniappe.core.tools.auth.references import (
    SubmittedReferenceResolver,
    UNAVAILABLE_REFERENCE_ERROR,
)
from lagniappe.core.tools.auth.task_attachments import (
    sign_task_attachment_claim,
    valid_task_attachment_claim,
)
from lagniappe.core.tools.tasks import combine as task_combine
from lagniappe.core.tools.tasks import scheduling
from lagniappe.core.tools.polling.forms import is_form_field, offline_replay_conflicts
from lagniappe.web.auth import (
    abort_public_user_action,
    logged_in,
    permission,
    require_ai_access,
)
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web import deferred_autofill

from . import tasks


# @testable true
# @tests tests_e2e/008_users/test_008e_public_users.py::test_public_user_restricted_schedules_are_forbidden
# @pair public-users:ai-schedule-guard
def _ai_schedule_requested(form):
    schedule_type = form.get("schedule-type")
    return bool(
        form.get("explain") == "schedule"
        or form.get("periodic")
        or schedule_type in {"monthly", "yearly"}
        or (form.get("scheduled") and schedule_type not in {"daily", "weekly"})
    )


# @testable true
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_tasks_table_columns
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_allows_own_page_only_users
# @matrix task-index : authenticated-access columns
# @pair permissions:own-page-only
@tasks.route("/index", methods=["GET"])
@logged_in
def task_index():
    task_index = index.TaskIndex()

    return responses.index("tasks", task_index)


# @testable true
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_name_sort_ascending_reorders_rows
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_allows_own_page_only_users
# @pairs permissions:own-page-only table-controls:sort-asc task-index:authenticated-access
@tasks.route("/rows", methods=["GET"])
@logged_in
def rows():
    task_index = index.TaskIndex(**request.values)
    tasks = task_index.tasks

    return responses.rows(tasks, task_index)


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_basic_page_task
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_page_task_viewer_sees_task_without_edit_controls
# @tests tests_e2e/006_tasks/test_006g_task_autofill.py::test_task_autofill_runs_deferred_with_page_file_context
# @matrix tasks : autofill deferred
# @matrix tasks : create readonly
# @pair ai:completion-refresh
@tasks.route("/<key>/replace", methods=["GET"])
@permission(Resource.TASK, Action.VIEW)
def get(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )

    return responses.page_task(task)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::task_settings
@tasks.route("/<key>/settings/replace", methods=["GET"])
@permission(Resource.TASK, Action.VIEW)
def settings(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    return responses.task_settings(task)


# @testable true
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_task_route_is_forbidden_without_model_or_page_permission
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_page_task_viewer_sees_task_without_edit_controls
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_assigned_user_can_work_their_assigned_task
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_page_task_viewer_sees_empty_form_structure_without_edit_controls
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_title_link_opens_backing_page_task
# @matrix tasks : assignee attached-form empty-fields focus page-task permission-gates readonly row-link
# @pair permissions:resource-gates
@tasks.route("<key>", methods=["GET"])
@permission(Resource.TASK, Action.VIEW)
def view(key, **kwargs):
    task = kwargs["entity"]
    page = Entities.fetch_one(task.page, request=Fetch.direct())
    if not page.allowed(Action.VIEW) and task.is_assigned_to(current_user):
        page = Entities.fetch_one(current_user.page, request=Fetch.direct())

    return responses.page(page, focus_task=task)


# @testable true
# @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_delete_cascades_dependents_assets_and_cache
# @pair entities:delete
@tasks.route("<key>/delete", methods=["DELETE"])
@permission(Resource.TASK, Action.DELETE)
def delete(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    notify_hashes = {task.page.hash} if task and task.page else set()

    if task and task.linked_pages:
        notify_hashes.update(p.hash for p in task.linked_pages if p)

    Entities.delete(task)

    return responses.ok()


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_can_move_to_another_page
# @matrix tasks : completed move title-menu
@tasks.route("<key>/move", methods=["PUT"])
@permission(Resource.TASK, Action.EDIT)
def move(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    page_key = request.form.get("page")
    page = Entities.fetch_one(page_key, request=Fetch.direct()) if page_key else None

    if not isinstance(page, Entities.PAGE) or not page.allowed(Action.EDIT):
        return responses.error("Select a page you can edit")

    if task.page and task.page.key == page.key:
        return responses.error("Task is already on this page")

    task.page = page
    task.updated = True
    task.save()

    return responses.json_response({"reload": True})


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_task_history_routes_are_forbidden_without_permission
# @matrix task-combine : authorization compatible delta linked-page migrate-history no-model same-model same-page view-page
# @pair web-headers:no-store
@tasks.route("<key>/combine", methods=["GET", "PUT"])
@permission(Resource.TASK, Action.DELETE, no_store=True)
def combine(key, **kwargs):
    task = kwargs["entity"]
    page_key = request.args.get("page")
    page = Entities.fetch_one(page_key, request=Fetch.direct()) if page_key else None
    if not isinstance(page, Entities.PAGE) or not page.allowed(Action.VIEW):
        abort(404)

    if request.method == "GET":
        compatible = task_combine.compatible_tasks(task, page, current_user)
        return responses.task_combine_form(task, compatible)

    try:
        result = task_combine.combine_tasks(
            task,
            request.form.getlist("task"),
            page,
            current_user,
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    for removed in result.removed:
        notify_hashes = {removed.page.hash} if removed.page else set()
        notify_hashes.update(page.hash for page in removed.linked_pages if page)
    return responses.task_combine_delta(result.main, result.removed, page)


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::task_data
# @covered-by lagniappe/web/routes/tasks/main.py::upload_file
# @covered-by lagniappe/web/routes/tasks/main.py::delete_file
# @reason upload state payload parsing is exercised through task mutation routes
def _upload_assets_payload(request):
    raw_assets = request.form.get("assets")
    if raw_assets is None:
        return None

    try:
        assets = json.loads(raw_assets or "{}")
    except json.JSONDecodeError as error:
        raise exceptions.ValidationError(UNAVAILABLE_REFERENCE_ERROR) from error

    if not isinstance(assets, dict):
        raise exceptions.ValidationError(UNAVAILABLE_REFERENCE_ERROR)
    return assets


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::task_data
# @covered-by lagniappe/web/routes/tasks/main.py::upload_file
# @covered-by lagniappe/web/routes/tasks/main.py::delete_file
# @reason upload state file-key extraction is exercised through task mutation routes
def _asset_file_keys(assets):
    if assets is None:
        return []

    file_keys = []
    for definition in assets.values():
        if not isinstance(definition, dict):
            continue

        file_key = definition.get("key") or definition.get("id")
        if file_key:
            file_keys.append(file_key)

    return file_keys


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::upload_file
# @reason upload route response shaping owns task asset entry creation
def _add_file_to_assets(assets, file, *, attachment_claim=None):
    assets = dict(assets or {})
    details = dict(file.details)
    if attachment_claim:
        details["attachment_claim"] = attachment_claim
    assets[file.filename or file.name or file.hash] = details
    return assets


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::task_data
# @reason claim lookup is exercised through task mutation data assembly
def _asset_claims(assets, file_key):
    return [
        definition.get("attachment_claim")
        for definition in (assets or {}).values()
        if isinstance(definition, dict)
        and (definition.get("key") or definition.get("id")) == file_key
        and definition.get("attachment_claim")
    ]


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::delete_file
# @reason delete route response shaping owns task asset entry removal
def _remove_file_from_assets(assets, file_key):
    return {
        name: definition
        for name, definition in (assets or {}).items()
        if not isinstance(definition, dict)
        or (definition.get("key") or definition.get("id")) != file_key
    }


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::upload_file
# @reason uploaded file creation is exercised through task file routes
def _create_task_file():
    uploaded_file = request.files.get("task-file") or direct_uploads.direct_upload_file(
        "task-file"
    )
    if not uploaded_file:
        return None

    data = {
        "filename": uploaded_file.filename,
        "mimetype": request.form.get("mimetype"),
    }
    file = Entities.FILE().create(upload=uploaded_file, data=data)
    file.save()
    return file


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::task_data
# @reason shared form fields are part of task create/update data assembly
def _task_base_data(request):
    return {
        "name": request.form.get("name"),
        "description": request.form.get("description"),
    }


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_form
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_model_task
# @matrix tasks : attach-form create
def _task_form_data(loaded, request):
    return {"form": loaded.get(request.form.get("form"))}


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_project
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_model_task
# @matrix tasks : badge create model-task-link project-link
def _task_project_data(loaded, request):
    return {
        "model": loaded.get(request.form.get("model")),
        "project": loaded.get(request.form.get("project")),
    }


# @testable true
# @tests tests_e2e/008_users/test_008e_public_users.py::test_public_user_creates_task_with_reduced_schedule_options
# @pair public-users:task-project-link
def _public_task_tracking(task, project_key, model_key):
    if not getattr(current_user, "is_public", False):
        return None
    if project_key or model_key:
        abort_public_user_action()
    return (
        task.model if task else None,
        task.project if task else None,
    )


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_assigned_to
# @matrix tasks : assignee badge create
def _task_assignee_data(loaded, request):
    return {"assigned_to": loaded.get(request.form.get("assigned_to"))}


# @testable true
# @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_add_due_date
# @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_remove_due_date
# @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_due_today
# @matrix task-scheduling : add due-date remove today
def _task_scheduling_due_date_data(request):
    return request.form.get("due-date")


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_due_date
# @matrix tasks : badge create due-date
def _task_create_due_date_data(request):
    return _task_scheduling_due_date_data(request)


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::create
# @covered-by lagniappe/web/routes/tasks/main.py::update
# @covered-by lagniappe/web/routes/tasks/main.py::personal
# @reason aggregate task form-data assembly is exercised through task mutation endpoints
def task_data(request, page, task=None):
    """Resolve form data into a dict suitable for Task.create() or Task.update()."""
    assets = _upload_assets_payload(request)
    asset_file_keys = _asset_file_keys(assets)
    if "page" in request.form:
        raise exceptions.ValidationError(UNAVAILABLE_REFERENCE_ERROR)

    form_key = request.form.get("form")
    assignee_key = request.form.get("assigned_to")
    project_key = request.form.get("project")
    model_key = request.form.get("model")
    public_tracking = _public_task_tracking(task, project_key, model_key)
    resolver = SubmittedReferenceResolver(
        current_user,
        form_key,
        assignee_key,
        project_key,
        model_key,
        *asset_file_keys,
    )

    current_form = task.form if task else None
    form = resolver.one(
        form_key,
        expected=Entities.FORM,
        action=Action.VIEW,
        existing=current_form,
        predicate=lambda selected: selected.form_type == "task",
    )
    if not form_key and current_form and not current_form.allowed(
        Action.VIEW, user=current_user
    ):
        form = current_form

    current_tracking = (task.model or task.project) if task else None

    # @testable false
    # @covered-by lagniappe/web/routes/tasks/main.py::task_data
    # @reason tracking constraints are part of aggregate task reference validation
    def tracking_reference_valid(selected):
        if not isinstance(selected, Entities.MODEL_TASK) or not selected.form:
            return True
        return bool(
            selected.form.form_type == "task"
            and selected.form.allowed(Action.VIEW, user=current_user)
        )

    project_selection = resolver.one(
        project_key,
        expected=(Entities.PROJECT, Entities.MODEL_TASK),
        action=Action.VIEW,
        existing=[task.model, task.project] if task else None,
        predicate=tracking_reference_valid,
    )
    model_selection = resolver.one(
        model_key,
        expected=Entities.MODEL_TASK,
        action=Action.VIEW,
        existing=task.model if task else None,
        predicate=tracking_reference_valid,
    )
    model = (
        project_selection
        if isinstance(project_selection, Entities.MODEL_TASK)
        else model_selection
    )
    project = (
        project_selection
        if isinstance(project_selection, Entities.PROJECT)
        else model.project if model else None
    )
    if model_selection and model and model_selection.key != model.key:
        raise exceptions.ValidationError(UNAVAILABLE_REFERENCE_ERROR)
    model = model_selection or model
    if model and project and (
        not model.project or model.project.key != project.key
    ):
        raise exceptions.ValidationError(UNAVAILABLE_REFERENCE_ERROR)
    if not model_key and not project_key and current_tracking and not current_tracking.allowed(
        Action.VIEW, user=current_user
    ):
        model = task.model
        project = task.project
    if public_tracking is not None:
        model, project = public_tracking

    current_assignee = task.assigned_to if task else None

    # @testable false
    # @covered-by lagniappe/web/routes/tasks/main.py::task_data
    # @reason assignment policy is part of aggregate task reference validation
    def assignee_authorized(selected):
        return bool(
            selected.user
            and collaboration.recipient_allowed(
                current_user,
                selected.user,
                channel="assign",
            )
        )

    assigned_to = resolver.one(
        assignee_key,
        expected=Entities.PAGE,
        existing=current_assignee,
        predicate=lambda selected: bool(selected.user),
        authorize=assignee_authorized,
    )
    if (
        not assignee_key
        and current_assignee
        and (
            not current_assignee.allowed(Action.VIEW, user=current_user)
            or not assignee_authorized(current_assignee)
        )
    ):
        assigned_to = current_assignee

    task_data = {
        **_task_base_data(request),
        "page": page,
        "task": None,
        "form": form,
        "model": model,
        "project": project,
        "assigned_to": assigned_to,
        "due_date": _task_create_due_date_data(request),
    }

    if assets is not None:
        existing_files = list(task.files) if task else []
        scope = task or page

        def file_authorized(file):
            return file.allowed(Action.VIEW, user=current_user) or any(
                valid_task_attachment_claim(
                    claim,
                    actor=current_user,
                    file=file,
                    scope=scope,
                )
                for claim in _asset_claims(assets, file.urlsafe_key)
            )

        selected_files = resolver.many(
            asset_file_keys,
            expected=Entities.FILE,
            existing=existing_files,
            authorize=file_authorized,
        )
        selected_keys = {file.key for file in selected_files}
        preserved_files = [
            file
            for file in existing_files
            if file.key not in selected_keys
            and not file.allowed(Action.VIEW, user=current_user)
        ]
        task_data["asset_files"] = [*selected_files, *preserved_files]

    return task_data


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_file
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_new_task_attachment_claim_is_required_and_scope_bound
# @matrix tasks : async-upload file-upload signed-claim
@tasks.route("<key>/upload-file", methods=["POST"])
@permission(requested=Action.EDIT)
def upload_file(key, **kwargs):
    abort_public_user_action()

    try:
        existing_assets = _upload_assets_payload(request)
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    file = _create_task_file()
    if not file:
        return responses.error("No file uploaded")

    scope = kwargs["entity"]
    attachment_claim = sign_task_attachment_claim(
        actor=current_user,
        file=file,
        scope=scope,
    )
    assets = _add_file_to_assets(
        existing_assets,
        file,
        attachment_claim=attachment_claim,
    )
    details = dict(file.details)
    details["attachment_claim"] = attachment_claim

    return responses.json_response({"assets": assets, "file": details})


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::upload_file
# @reason route permission mirrors the final task upload endpoint
@tasks.route("<key>/upload-file/direct-upload", methods=["POST"])
@permission(requested=Action.EDIT)
def upload_file_direct(key, **kwargs):
    abort_public_user_action()

    return direct_uploads.direct_upload_response()


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::update
# @reason autofill prompt data assembly is part of task update request flow
def _autofill_data(task, request):
    file = request.files.get("autofill-file") or direct_uploads.direct_upload_file(
        "autofill-file", consumer=FileConsumer.AI_INLINE
    )
    if file:
        try:
            enforce_file_consumer(
                file,
                FileConsumer.AI_INLINE,
                filename=getattr(file, "filename", None),
            )
        except FileConsumerLimitError as error:
            abort(422, description=str(error))
    return ai.autofill_prompt_data(
        task,
        current_user,
        user_context=request.form.get("autofill-description"),
        file=file,
        mimetype=request.form.get("mimetype"),
    )


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_with_partial_submission_omits_empty_fields
# @matrix tasks : complete partial-submission readonly
def _should_submit_task_form(active, role, task):
    if "TaskForm" not in active:
        return False
    return not (role == "complete-toggle" and task.completed)


# @testable true
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_complete_task_from_home_page
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_complete_page_task
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_due_date
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_with_empty_form_is_readonly
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_with_partial_submission_omits_empty_fields
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_page_task_viewer_sees_task_without_edit_controls
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_assigned_user_can_work_their_assigned_task
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_forged_hidden_file_key_cannot_be_linked_to_editable_task_or_page
# @matrix tasks : assignee attached-form complete due-date empty-fields partial-submission permission-gates readonly submitted-reference
@tasks.route("<key>/update", methods=["PUT", "GET"])
@permission(Resource.TASK, Action.EDIT)
def update(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )

    if offline_replay_conflicts(task, request.form):
        return responses.page_task(task, conflict=True)

    active = request.form.getlist("active")
    role = request.form.get("role")
    explain = request.form.get("explain")

    if (
        _should_submit_task_form(active, role, task)
        or role == "autofill-submit"
        or explain == "autofill"
    ):
        locked = deferred_autofill.locked_response(task, request.form)
        if locked:
            return locked

    if role == "autofill-submit" and request.files.get("autofill-file"):
        return responses.error(
            "The autofill attachment was not uploaded. Try attaching it again."
        )

    update_data = None
    if "TaskSettings" in active:
        try:
            update_data = task_data(request, task.page, task)
        except exceptions.ValidationError as error:
            return responses.error(str(error))

    if _should_submit_task_form(active, role, task):
        try:
            task.form_submission(request, actor=current_user)
        except exceptions.ValidationError as error:
            return responses.error(str(error))

    if "TaskSettings" in active:
        try:
            task.update(update_data)
        except exceptions.ValidationError as e:
            return responses.error(str(e))

        if _ai_schedule_requested(request.form):
            require_ai_access(AI.CREATE)

        schedule = task.properties.schedule.update(request.form)
        if schedule and schedule.generate and explain == "schedule":
            return responses.explain(schedule.prompt)
        elif schedule and schedule.generate:
            schedule.create()

        if schedule and schedule.error:
            return responses.error(schedule.error)

    if role == "complete-toggle":
        try:
            task.complete() if not task.completed else task.uncomplete()
        except exceptions.TaskCompletionError as e:
            return responses.error(str(e))

    if role in ["autofill-submit"] or explain == "autofill":
        require_ai_access(AI.CREATE)
        if explain == "autofill":
            try:
                prompt = ai.form_autofill_prompt(**_autofill_data(task, request))
                return responses.explain(prompt)
            finally:
                direct_uploads.cleanup_direct_uploads(
                    request.form, input_name="autofill-file"
                )

        task.save()
        return responses.entity_response(
            deferred_autofill.start_deferred_autofill(
                task,
                current_user,
                request.form,
                multipart_file=bool(request.files.get("autofill-file")),
            ),
            task,
            task.page,
        )

    task.save()

    return responses.page_task(task)


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::update
# @reason route permission mirrors task update for autofill uploads
@tasks.route("<key>/update/direct-upload", methods=["POST"])
@permission(Resource.TASK, Action.EDIT)
def update_direct(key, **kwargs):
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    locked = deferred_autofill.locked_response(kwargs["entity"], request.form)
    if locked:
        return locked
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_basic_page_task
# @tests tests_e2e/008_users/test_008e_public_users.py::test_public_user_creates_task_with_reduced_schedule_options
# @matrix tasks : basic create
@tasks.route("<key>/create", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def create(key, **kwargs):
    """Create a task on a page. Key is the page key, not a task key."""
    page = kwargs["entity"]
    try:
        task = Entities.TASK.create(task_data(request, page))
    except exceptions.ValidationError as e:
        return responses.error(str(e))

    explain = request.form.get("explain")

    if _ai_schedule_requested(request.form):
        require_ai_access(AI.CREATE)

    schedule = task.properties.schedule.update(request.form)
    if schedule and schedule.generate and explain == "schedule":
        return responses.explain(schedule.prompt)
    elif schedule and schedule.generate:
        schedule.create()

    if schedule and schedule.error:
        return responses.error(schedule.error)

    task.save()
    task.updated = False

    return responses.page_task(task)


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::create
# @reason route permission mirrors task create for upload-backed form data
@tasks.route("<key>/create/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def create_direct(key, **kwargs):
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_create_personal_task_due_today
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_create_personal_task_due_in_four_days
# @matrix tasks : create-personal due-date
@tasks.route("<key>/personal", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def personal(key, **kwargs):
    """Create a quick task on the current user's own page (from home)."""
    page = kwargs["entity"]
    try:
        create_data = task_data(request, page)
        task = Entities.TASK.create(create_data)
    except exceptions.ValidationError as e:
        return responses.error(str(e))

    task.save()

    return _home_task_response(task)


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::personal
# @reason route permission mirrors personal task create for upload-backed form data
@tasks.route("<key>/personal/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def personal_direct(key, **kwargs):
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_appears_after_completion_cycle
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_task_history_routes_are_forbidden_without_permission
# @matrix tasks : completion-cycle history reload
@tasks.route("<key>/history", methods=["GET"])
@permission(Resource.TASK, Action.VIEW)
def history(key, **kwargs):
    task = kwargs["entity"]
    history = task.history

    history_index = index.TaskHistoryIndex(entity=task)

    return responses.table(history, history_index)


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::personal
# @covered-by lagniappe/web/routes/tasks/main.py::complete
# @covered-by lagniappe/web/routes/tasks/main.py::change_due_date
# @reason response shaping is exercised through the home task mutation routes
def _home_task_response(task):
    due = task.properties.due_date.value
    if not task.completed and scheduling.due_in_home_task_window(due):
        return responses.home_task(task)

    return responses.home_task_removed()


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_task_history_routes_are_forbidden_without_permission
# @matrix tasks : history-fill latest-submission
# @pair tasks:history
@tasks.route("<key>/history/latest-submission", methods=["GET"])
@permission(Resource.TASK, Action.VIEW)
def latest_history_submission(key, **kwargs):
    task = kwargs["entity"]
    history = Entities.fetch_one(
        database_get.latest_task_history(task), request=Fetch.direct()
    )
    submission = history.properties.submission.form_value if history else {}
    return responses.json_response({"latest_submission": submission})


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
# @matrix tasks : history-fill patch repeating-default
@tasks.route("<key>/default-submission", methods=["PATCH"])
@permission(Resource.TASK, Action.EDIT)
def save_default_field(key, **kwargs):
    task = kwargs["entity"]
    locked = deferred_autofill.locked_response(task)
    if locked:
        return locked
    field_id = (request.get_json(silent=True) or {}).get("field_id")
    if not field_id:
        return responses.error("A submission field is required")

    history = Entities.fetch_one(
        database_get.latest_task_history(task), request=Fetch.direct()
    )
    if not history:
        return responses.error("No task history is available")

    try:
        task.save_default_field(field_id, history.properties.submission)
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    return responses.entity_response(responses.ok(), task)


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::delete_file
def _delete_file_if_unreferenced(file):
    if file and not file.has_references:
        Entities.delete(file)


# @testable true
# @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_file
# @matrix tasks : attachment file-upload remove
@tasks.route("<key>/files/<file_key>", methods=["DELETE"])
@permission(Resource.TASK, Action.EDIT)
def delete_file(key, file_key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    file = Entities.fetch_one(file_key, request=Fetch.direct())
    if (
        not isinstance(file, Entities.FILE)
        or file.key not in task.properties.files.keys
        or not file.allowed(Action.VIEW, user=current_user)
    ):
        return responses.not_found("File not found")

    try:
        assets = _upload_assets_payload(request) or task.properties.files.preload
    except exceptions.ValidationError as error:
        return responses.error(str(error))
    assets = _remove_file_from_assets(assets, file.urlsafe_key)
    task.properties.files.remove(file)
    task.save()
    _delete_file_if_unreferenced(file)

    return responses.entity_response(
        responses.json_response(
            {
                "assets": assets,
                "deleted": file.details,
            }
        ),
        task,
        task.page,
    )


# @testable true
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_quick_edit_updates_editable_cell
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_saved_filter_quick_edit_persists_attached_form_checkbox
# @matrix filters : attached-form checkbox quick-edit reload-persistence
# @pair task-index:quick-edit
@tasks.route("<key>/patch", methods=["PATCH"])
@permission(Resource.TASK, Action.EDIT)
def patch(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )

    task_data = request.json
    schema_id = task_data["schema_id"]
    value = task_data["value"]
    column = task_data.get("column")
    field = None

    if is_form_field(task, schema_id) or (schema_id == "completed" and task.form):
        locked = deferred_autofill.locked_response(task)
        if locked:
            return locked

    if schema_id in task.properties:
        field = task.properties[schema_id]
        if not field.editable:
            return responses.error("Field cannot be edited")

        if schema_id == "completed":
            try:
                if value and not task.completed:
                    task.complete()
                elif not value and task.completed:
                    task.uncomplete()
            except exceptions.TaskCompletionError as e:
                return responses.error(str(e))
        else:
            field.value = value
    else:
        field = task.properties.submission.fields.get(schema_id)
        if not field:
            return responses.error("Field cannot be edited")
        if not field.editable:
            return responses.error("Field cannot be edited")
        try:
            task.validate_browser_submission_references(
                {schema_id: value},
                actor=current_user,
                normalized=True,
            )
        except exceptions.ValidationError as error:
            return responses.error(str(error))
        field = task.properties.submission.patch(schema_id, value)
        task.save_submission()

    task.save()

    return responses.entity_response(
        responses.cell(field, task, column=column),
        task,
        task.page,
    )


# @testable true
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_complete_task_from_home_page
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_complete_recurring_task_from_home_page_reappears
# @matrix tasks : complete recurring
@tasks.route("/<key>/complete", methods=["PUT"])
@permission(Resource.TASK, Action.EDIT)
def complete(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    completed = request.form.get("completed") == "true"

    if completed and task.form:
        locked = deferred_autofill.locked_response(task, request.form)
        if locked:
            return locked

    try:
        task.complete() if completed else task.uncomplete()
    except exceptions.TaskCompletionError as e:
        return responses.error(str(e))

    task.save()

    return _home_task_response(task)


# @testable true
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_tomorrow
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_this_week
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_next_week
# @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_no_due_date
# @matrix tasks : due-date postpone
@tasks.route("/<key>/change-due-date", methods=["PUT"])
@permission(Resource.TASK, Action.EDIT)
def change_due_date(key, **kwargs):
    task = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )

    value = request.form.get("newDueDate")
    if value is None:
        task.due_date = None
    else:
        task.postpone(value)

    task.save()

    return _home_task_response(task)
