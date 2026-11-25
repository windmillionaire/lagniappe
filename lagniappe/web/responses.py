from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.core.entities.index import Index
    from lagniappe.core.properties.form_table import Table
    from lagniappe.core.properties.home import HomeProperty, TaskList
    from lagniappe.core.tools.cache.notification_state import NotificationState
    from lagniappe.core.tools.files.ranges import ByteRange

from types import SimpleNamespace
from typing import cast
from flask import (
    abort,
    Response,
    g,
    get_template_attribute,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from lagniappe.web import auth
from lagniappe.core.definitions.asset import FileAsset
from smartypants import smartypants
import yaml

from lagniappe.core.entities.entity import Entity
from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Action,
    Fetch,
    FetchReason,
    IngressStage,
    Resource,
    SearchFacets,
)
from lagniappe.core.definitions.manual import VALID_MANUAL_SECTIONS
from lagniappe.core.entities import Entities
from lagniappe.core.properties.schema import SchemaFields
from lagniappe.core.tools.forms.definitions import (
    definition_for,
    original_completion,
    rendered_html_fields,
)
from lagniappe.core.tools.database import assets as database_assets
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools import cache
from lagniappe.core.tools.polling.projections import (
    channel_revision,
    channel_revisions,
    filter_revision,
    filter_result_revision,
    render_operation_statuses,
)
from lagniappe.core.tools.tasks.ordering import page_task_roots


# --- General Responses ---


def offline() -> tuple[str, int]:
    return render_template("home/offline.html"), 200


def error(error: object, exception: BaseException | None = None) -> Response:
    if exception:
        exceptions.capture(exception)
    return Response(str(error), status=422, mimetype="text/plain")


def bad_request(error: object) -> Response:
    return Response(str(error), status=400, mimetype="text/plain")


def not_found(error: str) -> tuple[str, int]:
    return error, 404


def cell(
    field: object,
    entity: Entity,
    column: Mapping[str, object] | None = None,
    embedded: bool = False,
) -> tuple[str, int]:
    template = get_template_attribute("cell.html", "format_table_cell")
    column_data: dict[str, object] = {"link": True, "parent": True}
    column_data.update(column or {})
    template_column = SimpleNamespace(**column_data)
    parent = SimpleNamespace(table=SimpleNamespace(embedded=embedded))
    return template(field, entity, template_column, parent), 200


# @template cell.html::cell
def table(entities: Sequence[Entity], parent: object) -> tuple[str, int]:
    template = get_template_attribute("table.html", "table")
    return template(entities, parent), 200


def ok() -> tuple[str, int]:
    return "", 200


def image_response(image_data: bytes, mimetype: str) -> tuple[Response, int]:
    return Response(image_data, mimetype=mimetype), 200


def file_response(
    file_data: bytes | Iterable[bytes],
    mimetype: str,
    *,
    status: int = 200,
    byte_range: ByteRange | None = None,
    accept_ranges: bool = False,
) -> tuple[Response, int]:
    g.NO_CACHE = True
    response = Response(file_data, mimetype=mimetype, status=status)
    if accept_ranges:
        response.headers["Accept-Ranges"] = "bytes"
    if byte_range:
        response.headers["Content-Range"] = byte_range.content_range
        response.headers["Content-Length"] = str(byte_range.length)
    return response, status


def file_range_not_satisfiable(size: int, mimetype: str) -> tuple[Response, int]:
    g.NO_CACHE = True
    response = Response("", mimetype=mimetype, status=416)
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Range"] = f"bytes */{size}"
    return response, 416


def json_response(data: object, status: int = 200) -> tuple[Response, int]:
    return jsonify(data), status


def publish_notification_state(state: NotificationState | None) -> None:
    """Attach compact notification state to the current response lifecycle."""
    g.NOTIFICATION_STATE = cache.public_notification_state(state)


def entity_response[T](response: T, *entities: Entity | None) -> T:
    """Annotate a successful response with committed entity revisions."""
    revisions = getattr(g, "ENTITY_RESPONSE_REVISIONS", {})
    for entity in entities:
        if not entity:
            continue
        revisions[entity.urlsafe_key] = {
            "key": entity.urlsafe_key,
            "fingerprint": entity.fingerprint,
            "modified": entity.modified.isoformat() if entity.modified else None,
        }
    g.ENTITY_RESPONSE_REVISIONS = revisions
    return response


def notification_item(notification: models.Notification) -> str:
    template = get_template_attribute("notifications.html", "item")
    return template(notification).strip()


# --- Index Responses ---


def index(name: str, index: Index | Entity, **context: object) -> tuple[str, int]:
    fingerprint = (
        database_utility.site_fingerprint(f"/{name}/index")
        if name in {"forms", "tasks", "users"}
        else None
    )
    poll_channel = "categories" if name == "categories" else name
    poll_revision = (
        channel_revision(
            poll_channel,
            auth.authenticated_user(),
            site_fingerprints={f"/{name}/index": fingerprint},
        )
        if fingerprint
        else channel_revisions((poll_channel,), auth.authenticated_user())[poll_channel]
    )
    return (
        render_template(
            f"{name}/index.html",
            index=index,
            fingerprint=poll_revision if name == "tasks" else fingerprint,
            poll_channel=poll_channel,
            poll_revision=poll_revision,
            **context,
        ),
        200,
    )


def rows[T: Entity](entities: T | list[T], parent: object) -> tuple[str, int]:
    entities = entities if isinstance(entities, list) else [entities]
    template = get_template_attribute("table.html", "rows")
    return f"<table>{template(entities, parent)}</table>", 200


# --- Document Responses ---


def public_document(entity: models.Page) -> Response:
    from lagniappe.core.tools.email.notifications.links import absolute_url
    from lagniappe.core.tools.site import public_pages

    canonical_url = absolute_url(
        url_for("pages.public", public_id=entity.public_id)
    )

    def image_url(candidate):
        name = candidate.name
        if candidate.extension:
            name = f"{name}.{candidate.extension}"
        return absolute_url(
            url_for(
                "pages.public_image",
                public_id=entity.public_id,
                asset_name=name,
            )
        )

    indexing = public_pages.runtime_settings()["PUBLIC_PAGE_INDEXING"]
    metadata = public_pages.metadata(
        entity,
        canonical_url=canonical_url,
        site_image_url=absolute_url(
            f"/images/logo-512x512.png?v={CONFIG.BUILD_ID}"
        ),
        public_image_url=image_url,
        indexing=indexing,
    )
    response = make_response(
        render_template(
            "public/public.html",
            document=metadata.pop("document"),
            page=entity,
            metadata=metadata,
        )
    )
    response.headers["X-Robots-Tag"] = metadata["robots"]
    return response


def shared_document(**kwargs: object) -> Response:
    editor_document = {
        "markup": kwargs.get("html"),
        "state": kwargs.get("state"),
    }

    return jsonify(editor_document)


def document_html(html: str | None) -> tuple[Response, int]:
    return jsonify({"markup": html}), 200


def document_image(url: str | None) -> tuple[Response, int]:
    return jsonify({"src": url}), 200


# --- Task Responses ---


def page_task(task: models.Task, **extra: object) -> tuple[Response, int]:
    from lagniappe.web.deferred_autofill import form_state
    submission = task.properties.submission.form_value
    template = get_template_attribute("pages/tasks.html", "task")
    schema = task.submission_schema
    return entity_response(
        (
            jsonify(
                {
                    "html": template(task, task.page),
                    "schema": schema,
                    "submission": submission,
                    "schema_error": task.submission_schema_error,
                    "form_state": form_state(task),
                    **extra,
                }
            ),
            200,
        ),
        task,
        task.page,
    )


def task_settings(task: models.Task) -> tuple[str, int]:
    template = get_template_attribute("pages/tasks.html", "settings_form")
    return entity_response((template(task, task.page), 200), task)


def task_combine_form(
    task: models.Task, compatible: Sequence[models.Task]
) -> tuple[str, int]:
    template = get_template_attribute("pages/tasks.html", "combine_form")
    return template(task, compatible), 200


def task_combine_delta(
    main: models.Task, removed: Iterable[models.Task], page: models.Page
) -> tuple[Response, int]:
    task_template = get_template_attribute("pages/tasks.html", "task")
    empty_template = get_template_attribute("pages/tasks.html", "task_empty")
    order = [task.urlsafe_key for task in page_task_roots(page)]
    payload = {
        "task_delta": {
            "upsert": [
                {
                    "key": main.urlsafe_key,
                    "html": task_template(main, page).strip(),
                }
            ],
            "remove": [task.urlsafe_key for task in removed],
            "order": order,
            "empty": empty_template(page).strip() if not order else None,
        }
    }
    return entity_response(json_response(payload), main, page)


# --- Form Responses ---


def form_submission(
    entity: models.Page | models.Task | models.TaskHistory,
    *,
    original: bool = False,
    archived: bool = False,
) -> tuple[Response, int]:
    if original or archived:
        if original:
            if not isinstance(entity, Entities.TASK):
                raise exceptions.ValidationError("Original completion requires a task.")
            completion = original_completion(entity)
            definition = completion["definition"]
            values = completion["submission"]
        else:
            definition = definition_for(entity, archived=True)
            values = entity.properties.submission.value
        submission = {}
        fields = definition.schema
        if not isinstance(fields, list):
            raise exceptions.ValidationError("Invalid submission schema")
        for schema_field in fields:
            field_id = schema_field["id"]
            if not isinstance(field_id, str) or field_id not in values:
                continue
            field = SchemaFields.create_field(schema_field, entity)
            if field is not None:
                field.db_value = values[field_id]
                if field.form_value is not None:
                    submission[field.id] = field.form_value
    else:
        definition = entity.submission_definition
        values = entity.properties.submission.value
        submission = entity.properties.submission.form_value
    schema = definition.schema
    return jsonify({
        "schema": schema,
        "submission": submission,
        "generation": definition.generation,
        "migration_notice": [] if original or archived else entity.migration_notice,
        "html_fields": rendered_html_fields(entity, definition=definition),
        "schema_error": definition.error,
        "raw_submission": values if definition.error else None,
        "can_uncomplete": bool(original and entity.allowed(Action.EDIT, user=current_user)),
        "content_error": ("Original static content is unavailable." if
            definition.immutable and not definition.content_available and
            isinstance(schema, list) and any(field.get("type") == "html" for field in schema) else None),
    }), 200


def expanded_table_cell(field: Table) -> tuple[Response, int]:
    return jsonify(
        {"schema": field, "submission": field.form_value, "kind": field.kind}
    ), 200


def new_form_restriction(group: models.UserGroup) -> tuple[str, int]:
    template = get_template_attribute("forms/restrictions.html", "group_access")
    return template(group), 200


# --- Page Responses ---


def _public_page_settings_context(page):
    from lagniappe.core.tools.site import public_pages

    return {
        "settings": page.public_settings,
        "images": [
            {"name": image.name, "url": image.url, "alt": image.alt}
            for image in public_pages.document_images(page)
        ],
        "directory_categories": [
            {"id": category.urlsafe_key, "name": category.name}
            for category in sorted(
                page.categories,
                key=lambda category: category.name.casefold(),
            )
        ],
        "site_indexing": public_pages.runtime_settings()[
            "PUBLIC_PAGE_INDEXING"
        ],
        "site_image": f"/images/logo-512x512.png?v={CONFIG.BUILD_ID}",
    }


def page(page: models.Page, focus_task: models.Task | None = None) -> tuple[str, int]:
    public_context = (
        _public_page_settings_context(page)
        if page.allowed(Action.PUBLISH)
        else None
    )
    return render_template(
        "pages/page.html",
        page=page,
        focus_task=focus_task,
        public_context=public_context,
    ), 200


def page_tasks(page: models.Page) -> tuple[str, int]:
    return get_template_attribute("pages/tasks.html", "task_list")(page), 200


def page_files(page: models.Page) -> tuple[str, int]:
    return get_template_attribute("pages/files.html", "file_list")(
        page, page.files
    ), 200


def new_file_upload(
    file: models.File | list[models.File], page: models.Page
) -> tuple[str, int]:
    template = get_template_attribute("pages/files.html", "file_list_item")
    files = file if isinstance(file, (list, tuple)) else [file]
    return "".join(template(uploaded, page) for uploaded in files), 200


def page_info(page: models.Page, **extra: object) -> tuple[Response, int]:
    from lagniappe.web.deferred_autofill import form_state
    template = get_template_attribute("pages/info.html", "info_form")
    schema = page.submission_schema if page.form else None
    submission = page.properties.submission.form_value if page.form else None
    return entity_response(
        (
            jsonify(
                {
                    "html": template(page),
                    "schema": schema,
                    "submission": submission,
                    "form_state": form_state(page),
                    **extra,
                }
            ),
            200,
        ),
        page,
    )


def user_settings(page: models.Page) -> tuple[Response, int]:
    template = get_template_attribute("pages/info.html", "user_settings")
    schema = page.submission_schema if page.form else None
    submission = page.properties.submission.form_value if page.form else None
    is_own_page = current_user.page.key == page.key
    is_owner_viewer = current_user.is_owner
    is_admin_viewer = current_user.is_admin
    return entity_response(
        (
            jsonify(
                {
                    "html": template(
                        page,
                        is_own_page,
                        is_admin_viewer,
                        is_owner_viewer,
                        is_owner_viewer and is_own_page,
                        Resource.USER.allowed(Action.PERMISSIONS),
                    ),
                    "schema": schema,
                    "submission": submission,
                }
            ),
            200,
        ),
        page,
    )


def page_permissions(page: models.Page) -> tuple[str, int]:
    template = get_template_attribute("pages/info.html", "permissions_form")
    return entity_response((template(page), 200), page)


def page_document_settings(entity: models.Project | models.Page) -> tuple[str, int]:
    return entity_response(
        (
            get_template_attribute("pages/document.html", "document_settings")(
                entity,
                _public_page_settings_context(entity),
            ),
            200,
        ),
        entity,
    )


def page_image(page: models.Page) -> tuple[str, int]:
    template = get_template_attribute("pages/photo.html", "dropzone")
    return template(page), 200


# --- Category Responses ---


def category_info(category: models.Category) -> tuple[str, int]:
    template = get_template_attribute("categories/tools.html", "category_info")
    return entity_response((template(category), 200), category)


# --- Project Responses ---


def project_view(project: models.Project) -> tuple[str, int]:
    return render_template("projects/project.html", project=project), 200


def project_info(project: models.Project) -> tuple[str, int]:
    template = get_template_attribute("projects/info.html", "info_form")
    return entity_response((template(project), 200), project)


def new_model_task(model_task: models.ModelTask) -> tuple[str, int]:
    template = get_template_attribute("projects/model_tasks.html", "model_task")
    return entity_response(
        (template(model_task), 200),
        model_task,
        model_task.project if isinstance(model_task.project, Entity) else None,
    )


# --- File Responses ---


def file_page(file: models.File) -> tuple[str, int]:
    return render_template("files/file.html", file=file), 200


def file_info(file: models.File) -> tuple[str, int]:
    return entity_response(
        (get_template_attribute("files/info.html", "info_form")(file), 200),
        file,
    )


def file_download(file_entity: models.File) -> ResponseReturnValue:
    g.NO_CACHE = True
    asset = file_entity.properties.file.value
    if not isinstance(asset, FileAsset):
        return not_found("File not found")

    filename = str(file_entity.filename)
    mimetype = file_entity.mimetype
    disposition = f'attachment; filename="{filename.replace(chr(34), "")}"'

    if file_entity.large:
        if asset.visibility.value == "private":
            signed_url = database_assets.get_signed_url(
                asset.path,
                response_disposition=disposition,
                response_type=mimetype or "application/octet-stream",
            )
            return redirect(signed_url), 302
        url = asset.url
        if url is None:
            return not_found("File not found")
        return redirect(url), 302

    content = asset.get()

    response = make_response(content)
    response.headers["Content-Disposition"] = disposition
    response.headers["Content-Type"] = mimetype or "application/octet-stream"

    return response, 200


def ingress_progress(file: models.Ingress) -> tuple[Response, int]:
    from lagniappe.core.tools.ingress import IngressService

    projected = IngressService(file).progress().to_dict()
    stage_template = get_template_attribute("files/stages.html", "stage")
    progress_html = "".join([stage_template(file, s) for s in IngressStage])

    status = get_template_attribute("files/status.html", "status")(file)
    data = {
        **projected,
        "progress": progress_html.strip(),
        "status": status.strip(),
    }

    return jsonify(data), 200


def select_index_field(file: models.Ingress) -> tuple[str, int]:
    template = get_template_attribute("files/status/verify.html", "index_select")
    return template(file), 200


def ingress_delete_imported(file: models.Ingress) -> tuple[str, int]:
    return render_template("delete/ingress_imported.html", file=file), 200


# --- Home Responses ---


def new_category(category: models.Category) -> tuple[str, int]:
    template = get_template_attribute("home/categories.html", "category")
    return template(category), 200


def new_project(project: models.Project) -> tuple[str, int]:
    template = get_template_attribute("home/projects.html", "project")
    return template(project), 200


def new_page(page: models.Page) -> tuple[str, int]:
    template = get_template_attribute("home/pages.html", "page")
    return template(page), 200


def new_note(note: models.Note, surface: str = "home") -> tuple[str, int]:
    template = get_template_attribute("notes.html", "note_item")
    return template(note, surface), 200


def new_ingress_file(file: models.Ingress) -> tuple[str, int]:
    template = get_template_attribute("home/ingress.html", "imported_file")
    return template(file), 200


def new_tool_report(report: models.AIReport) -> tuple[Response, int]:
    template = get_template_attribute("home/tools.html", "report_item")
    return template(report), 200


def deferred_tool_report(
    report: models.AIReport,
    notification: models.Notification | None,
    job: models.DeferredJob | None = None,
) -> tuple[Response, int]:
    template = get_template_attribute("home/tools.html", "report_item")
    if notification is not None:
        loaded = Entities.fetch_one(notification.urlsafe_key, request=Fetch.direct())
        if isinstance(loaded, Entities.NOTIFICATION):
            notification = loaded
    return json_response(
        {
            "deferred": True,
            "operation": getattr(job, "urlsafe_key", None),
            "notification": (
                notification_item(notification) if notification is not None else None
            ),
            "html": template(report),
        }
    )


def tool_report(report: models.AIReport) -> tuple[str, int]:
    if not report.available:
        return render_template("tools/report.html", report=report), 200
    render_operation_statuses((report,), auth.authenticated_user())
    from lagniappe.core.tools.ai.reporting.schema_updates import report_impact, migration_pending

    page = max(1, request.args.get("schema_page", 1, type=int))
    return render_template("tools/report.html", report=report,
                           schema_impacts=report_impact(report, auth.authenticated_user(), page=page),
                           migration_pending=migration_pending(report)), 200


# @template home/categories.html::category
# @template home/directory.html::list
# @template home/home.html::create
def home_page(home: models.Home) -> tuple[str, int]:
    poll_revisions = channel_revisions(("home-notes", "tasks"), auth.authenticated_user())
    return (
        render_template(
            "home/home.html",
            home=home,
            poll_revisions=poll_revisions,
        ),
        200,
    )


def admin_page() -> tuple[str, int]:
    from lagniappe.core.tools.site.data_protection import data_protection_status

    try:
        protection = data_protection_status()
        protection_error = None
    except Exception as error:
        exceptions.capture(error)
        protection = None
        protection_error = "provider metadata could not be loaded"
    return render_template(
        "home/admin.html",
        data_protection=protection,
        data_protection_error=protection_error,
    ), 200


def privacy_policy() -> tuple[str, int]:
    return render_template("home/privacy_policy.html"), 200


def reporting_privacy() -> tuple[str, int]:
    return render_template("home/reporting_privacy.html"), 200


def activity(section: HomeProperty) -> tuple[str, int]:
    return get_template_attribute("home/notes.html", "list")(section), 200


def page_notes(notes: Iterable[models.Note], page: models.Page) -> tuple[str, int]:
    template = get_template_attribute("pages/notes.html", "note_list")
    return template(page, notes), 200


def notifications(
    notifications: Iterable[models.Notification],
    *,
    aggregate: Mapping[str, object],
    cursor: str | None = None,
    can_message: bool = False,
) -> tuple[str, int]:
    template = get_template_attribute("notifications.html", "list")
    return template(notifications, aggregate, cursor, can_message), 200


def message_page(
    *, initial_conversation: str | None = None, can_message: bool = False
) -> tuple[str, int]:
    return render_template(
        "messages/index.html",
        initial_conversation=initial_conversation,
        can_message=can_message,
    ), 200


def message_clear_modal(key: str, *, peer_name: str) -> tuple[str, int]:
    return render_template(
        "delete/conversation.html",
        key=key,
        peer_name=peer_name,
    ), 200


def home_section(section: HomeProperty) -> tuple[str, int] | None:
    if section.id == "ingress":
        return get_template_attribute("home/ingress.html", "import_list")(section), 200
    elif section.id == "tools":
        return get_template_attribute("home/tools.html", "report_list")(section), 200
    elif section.id == "starred":
        return get_template_attribute("home/starred.html", "list")(section), 200
    elif section.id == "tasks":
        count_template = get_template_attribute("common.html", "task_count")
        return count_template(cast("TaskList", section).count) + get_template_attribute(
            "home/tasks.html", "list"
        )(section), 200
    elif section.id == "pages":
        return get_template_attribute("home/pages.html", "list")(section), 200
    elif section.id == "notes":
        return activity(section)
    elif section.id == "categories":
        return get_template_attribute("home/categories.html", "list")(section), 200
    elif section.id == "projects":
        return get_template_attribute("home/projects.html", "list")(section), 200


def home_task_list() -> tuple[str, int]:

    home = Entities.HOME(user=auth.authenticated_user())
    template = get_template_attribute("home/tasks.html", "list")
    task_list_html = template(home.section("tasks"))

    task_count = database_get.user_task_count(current_user.page)
    count_html = get_template_attribute("common.html", "task_count")(task_count)

    return count_html + task_list_html, 200


def home_task(task: models.Task) -> tuple[Response, int]:
    template = get_template_attribute("home/tasks.html", "task")
    count = database_get.user_task_count(current_user.page)
    return jsonify({"html": template(task), "count": count}), 200


def home_task_removed(task: models.Task | None = None) -> tuple[Response, int]:
    count = database_get.user_task_count(current_user.page)
    payload: dict[str, object] = {"removed": True, "count": count}
    if task is not None:
        payload["name"] = task.name
        payload["scheduled"] = task.properties.due_date.value is not None
    return jsonify(payload), 200


# --- Filter Responses ---


def _filtered_index_poll_context(entity):
    if not entity.temporary:
        context = {"fingerprint": filter_result_revision(entity, auth.authenticated_user())}
        if entity.parent.kind == "project":
            context.update(
                entity_revision=filter_revision(entity, auth.authenticated_user()),
                poll_channel="tasks",
                poll_revision=channel_revisions(("tasks",), auth.authenticated_user())["tasks"],
            )
        return context
    channel = "tasks" if entity.parent.kind == "project" else "categories"
    return {
        "poll_channel": channel,
        "poll_revision": channel_revisions((channel,), auth.authenticated_user())[channel],
    }


def new_filter(filter: models.Filter) -> tuple[str, int]:
    template = get_template_attribute("filters.html", "filter_item")
    return template(filter), 200


def saved_filters(
    entity: models.Project | models.Category, filters: Iterable[models.Filter]
) -> tuple[str, int]:
    if isinstance(entity, Entities.PROJECT):
        template = get_template_attribute("projects/filters.html", "saved_filters")
        return template(entity, filters), 200
    else:
        template = get_template_attribute("categories/tools.html", "saved_filters")
        return template(entity, filters), 200


def filtered_task_index(
    tasks: Iterable[models.Task], filter: models.Filter
) -> tuple[str, int]:
    return (
        render_template(
            "tasks/index.html",
            tasks=tasks,
            filtered=filter,
            **_filtered_index_poll_context(filter),
        ),
        200,
    )


def filtered_page_index(
    pages: Iterable[models.Page], filter: models.Filter
) -> tuple[str, int]:
    return (
        render_template(
            "categories/index.html",
            pages=pages,
            filtered=filter,
            **_filtered_index_poll_context(filter),
        ),
        200,
    )


def filter_condition(
    data: dict[str, object],
    condition: models.Condition,
    filter: bool = False,
    options: bool = False,
) -> tuple[Response, int]:
    if filter:
        badge_template = get_template_attribute("filters.html", "filter_badge")
        data["html"] = badge_template(
            condition.details,
            condition.contract_condition,
        )

    if options:
        options_template = get_template_attribute("filters.html", "filter_condition")
        data["options"] = options_template(condition.field)

    return jsonify(data), 200


# --- User Responses ---


def create_group(group: models.UserGroup) -> tuple[str, int]:
    form_partial = get_template_attribute("users/tools.html", "group_permissions")
    selector_partial = get_template_attribute(
        "users/tools.html",
        "group_selector",
    )

    sections = group.properties.permissions.permissions_form()["sections"]
    return form_partial(group, sections) + selector_partial(group), 200


def group_permissions(group: models.UserGroup, public: bool = False) -> tuple[str, int]:
    if public:
        template = get_template_attribute("users/tools.html", "public_permissions")
    else:
        template = get_template_attribute("users/tools.html", "group_permissions")

    sections = group.properties.permissions.permissions_form()["sections"]
    return entity_response((template(group, sections), 200), group)


# --- Search Responses ---


def index_results_html(
    results: Sequence[Mapping[str, object]],
    create_command: Mapping[str, object] | None = None,
) -> str:
    template = get_template_attribute("nav.html", "index_results")
    return template(results, len(results), create_command=create_command)


def index_results(
    results: Sequence[Mapping[str, object]],
    create_command: Mapping[str, object] | None = None,
) -> tuple[dict[str, str], int]:
    return {"results": index_results_html(results, create_command)}, 200


def created_index_result(result: Mapping[str, object]) -> tuple[Response, int]:
    return jsonify(
        {
            "option": result["details"],
            "results": index_results_html([result]),
        }
    ), 200


def search_results(
    query: str, results: Sequence[Mapping[str, object]], total: int
) -> tuple[dict[str, str], int]:
    template = get_template_attribute("nav.html", "search_results")
    return {"results": template(query, results, total)}, 200


def search_page(
    q: str, results: Sequence[Mapping[str, object]], pagination: Mapping[str, object]
) -> tuple[str, int]:
    return render_template(
        "search/search.html",
        query=q,
        results=results,
        pagination=pagination,
        facets=SearchFacets,
    ), 200


def location_results(
    results: Sequence[Mapping[str, object]], total: int
) -> tuple[dict[str, str], int]:
    template = get_template_attribute("nav.html", "location_results")
    return {"results": template(results, total)}, 200


# --- Delete Responses ---


def delete_entity(
    entity: Entity | None = None, key: str | None = None
) -> tuple[str, int]:
    if not entity:
        return render_template("delete/dne.html", key=key), 200

    kind = "user" if entity.kind == "page" and entity.db.get("user") else entity.kind

    if kind == "form" and entity.key is not None:
        loaded = Entities.fetch(*database_get.form_instance_users(entity.key), request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION))
        instances = [
            instance
            for instance in loaded
            if isinstance(instance, (Entities.PAGE, Entities.TASK))
            and instance.allowed(Action.VIEW, user=current_user)
        ]
        instances.sort(
            key=lambda instance: (instance.kind, (instance.name or "").lower())
        )
        details = [instance.reference_details for instance in instances[:5]]
        return render_template(
            "delete/form.html",
            entity=entity,
            num_instances=len(instances),
            details=details,
            num_remaining=max(0, len(instances) - len(details)),
        ), 200

    return smartypants(render_template(f"delete/{kind}.html", entity=entity)), 200


# --- Manual & Reference Responses ---


def manual_index(section: str, index: Iterable[Mapping[str, str]]) -> Response:
    from lagniappe.core.tools.site import public_pages

    if section not in VALID_MANUAL_SECTIONS:
        raise ValueError("Unknown manual section")
    content_template = f"manual/content/{section}.html"
    public_page = bool(CONFIG.PUBLIC_MANUAL and not current_user.is_authenticated)
    indexing = bool(
        CONFIG.PUBLIC_MANUAL
        and public_pages.runtime_settings()["PUBLIC_PAGE_INDEXING"]
    )
    if CONFIG.PUBLIC_MANUAL:
        sections = [
            {
                **definition,
                "metadata": public_pages.manual_metadata(
                    definition,
                    indexing=indexing,
                ),
            }
            for definition in index
        ]
        search_metadata = next(
            definition["metadata"]
            for definition in sections
            if definition["key"] == section
        )
    else:
        sections = index
        search_metadata = None

    context = {
        "content_template": content_template,
        "sections": sections,
        "search_metadata": search_metadata,
        "public_page": public_page,
    }
    if public_page:
        context.update(page_mode="public")

    response = make_response(
        smartypants(render_template("manual/index.html", **context))
    )
    if search_metadata:
        response.headers["X-Robots-Tag"] = search_metadata["robots"]
    return response


def manual_content(section: str) -> Response:
    response = make_response(
        smartypants(render_template(f"manual/content/{section}.html"))
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def reference_topic(section: str) -> tuple[str, int]:
    from lagniappe.reference import get_topic

    try:
        topic = get_topic(section)
    except KeyError:
        abort(404)
    return render_template("reference/topic.html", topic=topic), 200


def reference_environment_variables(
    variables: Mapping[str, object], download: bool = False
) -> ResponseReturnValue:
    if download:
        display_variables = variables
    else:
        from config.recovery import redact_settings_for_display

        display_variables = redact_settings_for_display(variables)
    yaml_content = yaml.safe_dump(
        display_variables,
        default_flow_style=False,
        sort_keys=True,
        allow_unicode=True,
    )

    if download:
        response = make_response(yaml_content)
        response.headers["Content-Disposition"] = (
            'attachment; filename="lagniappe_settings.yaml"'
        )
        response.headers["Content-Type"] = "application/yaml; charset=utf-8"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response, 200
    else:
        return render_template(
            "reference/env_variables.html", environment_variables=yaml_content
        ), 200


def site_configuration(variables: Mapping[str, object]) -> tuple[str, int]:
    from config.recovery import redact_settings_for_display

    yaml_content = yaml.safe_dump(
        redact_settings_for_display(variables),
        default_flow_style=False,
        sort_keys=True,
        allow_unicode=True,
    )
    return render_template(
        "reference/site_configuration.html", environment_variables=yaml_content
    ), 200
