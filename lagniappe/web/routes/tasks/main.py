from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Request
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.task import TaskData
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

import json

from flask import abort, request, get_template_attribute
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    Action,
    Fetch,
    FetchReason,
    FileConsumerLimitError,
    Resource,
)
from lagniappe.core.properties.task_scheduling import ScheduleType
from lagniappe.core.properties.base_property import Property
from lagniappe.core.entities import Entities, index
from lagniappe.core.tools import dates
from lagniappe.core.properties.schema import SchemaFields
from lagniappe.core.tools.forms.definitions import history_groups, history_values_for
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import assets as storage_assets
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
    authenticated_user,
    load_route_entity,
    abort_public_user_action,
    logged_in,
    permission,
    require_ai_access,
)
from lagniappe.web.pagination import pagination_options
from lagniappe.web import responses
from lagniappe.web import direct_uploads
from lagniappe.web import deferred_autofill
from lagniappe.core.tools.forms import review as form_review

from ..pages.main import _load_page_settings_relations
from . import tasks


def _ai_schedule_requested(form):
    schedule_type = form.get("schedule-type")
    return bool(
        form.get("periodic")
        or schedule_type in {"monthly", "yearly"}
        or (form.get("scheduled") and schedule_type not in {"daily", "weekly"})
    )


@tasks.route("/index", methods=["GET"])
@logged_in
def task_index() -> ResponseReturnValue:
    task_index = index.TaskIndex()

    return responses.index("tasks", task_index)


@tasks.route("/rows", methods=["GET"])
@logged_in
def rows() -> ResponseReturnValue:
    task_index = index.TaskIndex(undated=bool(request.values.get("undated")), **pagination_options())
    tasks = task_index.tasks

    return responses.rows(tasks, task_index)


@tasks.route("/<key>/replace", methods=["GET"])
@permission(Resource.TASK, Action.VIEW, fingerprint=deferred_autofill.form_fingerprint)
def get(key: str, **kwargs: Unpack[EntityContext[models.Task]]) -> ResponseReturnValue:
    task = load_route_entity(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )

    return responses.page_task(task)


@tasks.route("/<key>/settings/replace", methods=["GET"])
@permission(Resource.TASK, Action.VIEW)
def settings(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    return responses.task_settings(task)


@tasks.route("<key>", methods=["GET"])
@permission(Resource.TASK, Action.VIEW, fingerprint=deferred_autofill.form_fingerprint)
def view(key: str, **kwargs: Unpack[EntityContext[models.Task]]) -> ResponseReturnValue:
    task = kwargs["entity"]
    page = Entities.fetch_one(task.page, request=Fetch.direct())
    if not isinstance(page, Entities.PAGE):
        return responses.not_found("Page not found")
    if not page.allowed(Action.VIEW) and task.is_assigned_to(authenticated_user()):
        page = Entities.fetch_one(current_user.page, request=Fetch.direct())
        if not isinstance(page, Entities.PAGE):
            return responses.not_found("Page not found")

    _load_page_settings_relations(
        page, restrictions=Resource.USER.allowed(Action.PERMISSIONS)
    )
    return responses.page(page, focus_task=task)


@tasks.route("<key>/delete", methods=["DELETE"])
@permission(Resource.TASK, Action.DELETE)
def delete(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    notify_hashes = {task.page.hash} if task and task.page else set()

    if task and task.linked_pages:
        notify_hashes.update(p.hash for p in task.linked_pages if p)

    Entities.delete(task)

    return responses.ok()


@tasks.route("<key>/move", methods=["PUT"])
@permission(Resource.TASK, Action.EDIT)
def move(key: str, **kwargs: Unpack[EntityContext[models.Task]]) -> ResponseReturnValue:
    task = load_route_entity(
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


@tasks.route("<key>/combine", methods=["GET", "PUT"])
@permission(Resource.TASK, Action.DELETE, no_store=True)
def combine(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = kwargs["entity"]
    page_key = request.args.get("page")
    page = Entities.fetch_one(page_key, request=Fetch.direct()) if page_key else None
    if not isinstance(page, Entities.PAGE) or not page.allowed(Action.VIEW):
        abort(404)

    if request.method == "GET":
        compatible = task_combine.compatible_tasks(task, page, authenticated_user())
        return responses.task_combine_form(task, compatible)

    try:
        result = task_combine.combine_tasks(
            task,
            request.form.getlist("task"),
            page,
            authenticated_user(),
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    for removed in result.removed:
        notify_hashes = {removed.page.hash} if removed.page else set()
        notify_hashes.update(page.hash for page in removed.linked_pages if page)
    return responses.task_combine_delta(result.main, result.removed, page)


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


def _add_file_to_assets(assets, file, *, attachment_claim=None):
    assets = dict(assets or {})
    details = dict(file.details)
    if attachment_claim:
        details["attachment_claim"] = attachment_claim
    assets[file.filename or file.name or file.hash] = details
    return assets


def _asset_claims(assets, file_key):
    return [
        definition.get("attachment_claim")
        for definition in (assets or {}).values()
        if isinstance(definition, dict)
        and (definition.get("key") or definition.get("id")) == file_key
        and definition.get("attachment_claim")
    ]


def _remove_file_from_assets(assets, file_key):
    return {
        name: definition
        for name, definition in (assets or {}).items()
        if not isinstance(definition, dict)
        or (definition.get("key") or definition.get("id")) != file_key
    }


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
    file = Entities.FILE().create(
        upload=uploaded_file,
        data=data,
        report_user=authenticated_user(),
    )
    file.save()
    return file


def _task_base_data(request: Request) -> TaskData:
    return {
        "name": request.form.get("name"),
        "description": request.form.get("description"),
    }


def _task_form_data(loaded, request):
    return {"form": loaded.get(request.form.get("form"))}


def _task_project_data(loaded, request):
    return {
        "model": loaded.get(request.form.get("model")),
        "project": loaded.get(request.form.get("project")),
    }


def _public_task_tracking(task, project_key, model_key):
    if not getattr(current_user, "is_public", False):
        return None
    if project_key or model_key:
        abort_public_user_action()
    return (
        task.model if task else None,
        task.project if task else None,
    )


def _task_assignee_data(loaded, request):
    return {"assigned_to": loaded.get(request.form.get("assigned_to"))}


def _task_scheduling_due_date_data(request):
    return request.form.get("due-date")


def _task_create_due_date_data(request):
    return _task_scheduling_due_date_data(request)


def task_data(
    request: Request, page: models.Page, task: models.Task | None = None
) -> TaskData:
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
        authenticated_user(),
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
    if not model_key and not project_key and task is not None and current_tracking and not current_tracking.allowed(
        Action.VIEW, user=current_user
    ):
        model = task.model
        project = task.project
    if public_tracking is not None:
        model, project = public_tracking

    current_assignee = task.assigned_to if task else None

    def assignee_authorized(selected):
        return bool(
            selected.user
            and collaboration.recipient_allowed(
                authenticated_user(),
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

    task_data: TaskData = {
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
            return (file.has_references and file.allowed(Action.VIEW, user=current_user)) or any(
                valid_task_attachment_claim(
                    claim,
                    actor=authenticated_user(),
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


@tasks.route("<key>/upload-file", methods=["POST"])
@permission(requested=Action.EDIT)
def upload_file(
    key: str, **kwargs: Unpack[EntityContext[Entity]]
) -> ResponseReturnValue:
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
        actor=authenticated_user(),
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


@tasks.route("<key>/upload-file/direct-upload", methods=["POST"])
@permission(requested=Action.EDIT)
def upload_file_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    abort_public_user_action()

    return direct_uploads.direct_upload_response()


def _should_submit_task_form(active, role, task):
    if "TaskForm" not in active:
        return False
    return not (role == "complete-toggle" and task.completed)


@tasks.route("<key>/update", methods=["PUT", "GET"])
@permission(Resource.TASK, Action.EDIT)
def update(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )

    if offline_replay_conflicts(task, request.form):
        return responses.page_task(task, conflict=True)

    active = request.form.getlist("active")
    role = request.form.get("role")
    if role == "explain" or request.form.get("explain"):
        return responses.error("Initial Prompt is no longer available.")

    submitting_answers = (
        _should_submit_task_form(active, role, task)
        or role == "autofill-submit"
    )
    # Settings/completion also save the task row. Fence their loaded state so a
    # simultaneous AI commit cannot be replaced by that older row.
    baseline = request.form if submitting_answers else {"form-revision": task.autofill_revision}
    if not form_review.stage_submission_guard(task, baseline):
        return deferred_autofill.conflict_response(task)
    if submitting_answers:
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
            page = task.page
            if page is None:
                return responses.error("The task page is no longer available.")
            update_data = task_data(request, page, task)
        except exceptions.ValidationError as error:
            return responses.error(str(error))

    autofill_requested = role == "autofill-submit"
    draft = None
    if autofill_requested:
        try:
            draft = task.preview_form_submission(request, actor=current_user)
        except exceptions.ValidationError as error:
            return responses.error(str(error))
    elif _should_submit_task_form(active, role, task):
        try:
            task.form_submission(request, actor=current_user)
        except exceptions.ValidationError as error:
            return responses.error(str(error))

    if update_data is not None:
        try:
            task.update(update_data)
        except exceptions.ValidationError as e:
            return responses.error(str(e))

        if _ai_schedule_requested(request.form):
            require_ai_access(AI.CREATE)

        schedule = task.properties.schedule.update(request.form)
        if isinstance(schedule, ScheduleType) and schedule.generate:
            schedule.create()

        if isinstance(schedule, ScheduleType) and schedule.error:
            return responses.error(schedule.error)

    if role == "complete-toggle":
        try:
            if task.completed:
                task.uncomplete(
                    submission_source=request.form.get("completion_submission", "modified"),
                )
            else:
                task.complete()
        except (exceptions.TaskCompletionError, exceptions.ValidationError) as e:
            return responses.error(str(e))

    if autofill_requested and draft is not None:
        require_ai_access(AI.CREATE)
        return responses.entity_response(
            deferred_autofill.start_deferred_autofill(
                task,
                authenticated_user(),
                request.form,
                multipart_file=bool(request.files.get("autofill-file")),
                submission=draft["values"],
                prompt_submission=draft["ai_values"],
            ),
            task,
            task.page,
        )

    staged_file = None
    try:
        staged_file, staged_cleanup = deferred_autofill.staged_upload_for_update(
            task, authenticated_user(), request.form,
        )
        form_review.acknowledge_reviews(task, authenticated_user(), request.form.getlist("reviewed-operation"))
        if staged_file:
            Entities.save(staged_file, task)
        else:
            task.save()
    except exceptions.MutationConflict:
        if staged_file:
            storage_assets.cleanup_rejected_attempt(staged_file)
        return deferred_autofill.conflict_response(task)
    except (exceptions.ValidationError, storage_assets.DirectUploadError, FileConsumerLimitError) as error:
        if staged_file:
            storage_assets.cleanup_rejected_attempt(staged_file)
        return responses.error(str(error))

    deferred_autofill.cleanup_staged_uploads(staged_cleanup)

    return responses.page_task(task)


@tasks.route("<key>/update/direct-upload", methods=["POST"])
@permission(Resource.TASK, Action.EDIT)
def update_direct(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    locked = deferred_autofill.locked_response(kwargs["entity"], upload_data)
    if locked:
        return locked
    return direct_uploads.direct_upload_response()


@tasks.route("<key>/create", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def create(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    """Create a task on a page. Key is the page key, not a task key."""
    page = kwargs["entity"]
    try:
        task = Entities.TASK.create(task_data(request, page))
    except exceptions.ValidationError as e:
        return responses.error(str(e))

    if request.form.get("explain") or request.form.get("role") == "explain":
        return responses.error("Initial Prompt is no longer available.")

    if _ai_schedule_requested(request.form):
        require_ai_access(AI.CREATE)

    schedule = task.properties.schedule.update(request.form)
    if isinstance(schedule, ScheduleType) and schedule.generate:
        schedule.create()

    if isinstance(schedule, ScheduleType) and schedule.error:
        return responses.error(schedule.error)

    task.save()
    task.updated = False

    return responses.page_task(task)


@tasks.route("<key>/create/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def create_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    upload_data = request.get_json(silent=True) or request.form
    if upload_data.get("input_name") == "autofill-file":
        require_ai_access(AI.CREATE)
    return direct_uploads.direct_upload_response()


@tasks.route("<key>/personal", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def personal(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
    """Create a quick task on the current user's own page (from home)."""
    page = kwargs["entity"]
    try:
        create_data = task_data(request, page)
        task = Entities.TASK.create(create_data)
    except exceptions.ValidationError as e:
        return responses.error(str(e))

    task.save()

    return _home_task_response(task)


@tasks.route("<key>/archived-submission", methods=["GET"])
@permission(Resource.TASK, Action.VIEW, no_store=True)
def archived_submission(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = kwargs["entity"]
    if not task.completed or task.form is not None or task.properties.form.key is None:
        abort(404)
    return responses.form_submission(task, archived=True)


@tasks.route("<key>/personal/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def personal_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    return direct_uploads.direct_upload_response()


@tasks.route("<key>/history", methods=["GET"])
@permission(Resource.TASK, Action.VIEW, no_store=True)
def history(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = kwargs["entity"]
    groups = [
        {**group, "index": index.TaskHistoryIndex(entity=group["records"][0])}
        for group in history_groups(task.history)
    ]
    template = get_template_attribute("tasks/history.html", "completion_history")
    return template(groups), 200


@tasks.route("<key>/completion-details", methods=["GET"])
@permission(requested=Action.VIEW, no_store=True)
def completion_details(
    key: str, **kwargs: Unpack[EntityContext[models.Task | models.TaskHistory]]
) -> ResponseReturnValue:
    entity = Entities.fetch_one(kwargs["entity"], request=Fetch.direct())
    if not isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)) or (
        isinstance(entity, Entities.TASK) and not entity.completed
    ):
        abort(404)
    if isinstance(entity, Entities.TASK) and not entity.allowed(Action.EDIT):
        abort(403)
    return responses.form_submission(entity, original=isinstance(entity, Entities.TASK))


def _home_task_response(task):
    due = task.properties.due_date.value
    if not task.completed and scheduling.due_in_home_task_window(due):
        return responses.home_task(task)

    return responses.home_task_removed()


@tasks.route("<key>/history/latest-submission", methods=["GET"])
@permission(Resource.TASK, Action.VIEW, no_store=True)
def latest_history_submission(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = kwargs["entity"]
    histories = task.load_history(database_get.latest_task_history(task))
    history = histories[0] if histories else None
    field_id = request.args.get("field")
    schema = {field["id"]: field for field in task.submission_schema}
    if field_id is None:
        values = history.properties.submission.value if history else {}
        fields = [key for key, value in values.items()
                  if key in schema and value is not None and value != ""
                  and value != [] and value != {}
                  and schema[key]["type"] not in {"html", "signature", "status"}]
        return responses.json_response({"history_fields": fields})
    try:
        if not history:
            raise exceptions.ValidationError("This task has no saved answers to reuse.")
        values = history_values_for(task, history, field_id, zone=str(dates.user_timezone()))
        field = SchemaFields.create_field(schema[field_id], history)
        if field is None:
            raise exceptions.ValidationError("This field cannot be filled from history.")
        field.db_value = values[field_id]
        return responses.json_response({"latest_submission": {field_id: field.form_value}})
    except exceptions.ValidationError as error:
        return responses.json_response({"error": str(error)}, status=422)


def _delete_file_if_unreferenced(file):
    if file and not file.has_references:
        Entities.delete(file)


@tasks.route("<key>/files/<file_key>", methods=["DELETE"])
@permission(Resource.TASK, Action.EDIT)
def delete_file(
    key: str, file_key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    file = Entities.fetch_one(file_key, request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
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


@tasks.route("<key>/patch", methods=["PATCH"])
@permission(Resource.TASK, Action.EDIT)
def patch(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
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
        if str(task_data.get("form_generation", "0")) != str(task.generation):
            return responses.error("The form fields changed. Reload this table before editing the value.")

    if schema_id in task.properties:
        field = task.properties[schema_id]
        if not isinstance(field, Property) or not field.editable:
            return responses.error("Field cannot be edited")

        if schema_id == "completed":
            try:
                if value and not task.completed:
                    task.complete()
                elif not value and task.completed:
                    task.uncomplete(
                        submission_source=task_data.get("completion_submission", "modified"),
                    )
            except (exceptions.TaskCompletionError, exceptions.ValidationError) as e:
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


@tasks.route("/<key>/complete", methods=["PUT"])
@permission(Resource.TASK, Action.EDIT)
def complete(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
        kwargs["entity"],
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    completed = request.form.get("completed") == "true"

    if completed and task.form:
        locked = deferred_autofill.locked_response(task, request.form)
        if locked:
            return locked

    try:
        if completed:
            task.complete()
        else:
            task.uncomplete(
                submission_source=request.form.get("completion_submission", "modified"),
            )
    except (exceptions.TaskCompletionError, exceptions.ValidationError) as e:
        return responses.error(str(e))

    task.save()

    return _home_task_response(task)


@tasks.route("/<key>/change-due-date", methods=["PUT"])
@permission(Resource.TASK, Action.EDIT)
def change_due_date(
    key: str, **kwargs: Unpack[EntityContext[models.Task]]
) -> ResponseReturnValue:
    task = load_route_entity(
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
