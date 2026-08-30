from types import SimpleNamespace
from flask import (
    Response,
    g,
    get_template_attribute,
    jsonify,
    make_response,
    redirect,
    render_template,
    url_for,
)
from flask_login import current_user
from smartypants import smartypants
import yaml

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Action,
    Fetch,
    IngressStage,
    Resource,
    SearchFacets,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import assets as database_assets
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools import cache
from lagniappe.core.tools.polling.projections import (
    channel_revision,
    channel_revisions,
    render_operation_statuses,
)
from lagniappe.core.tools.tasks.ordering import page_task_roots


# --- General Responses ---


def offline():
    return render_template("home/offline.html"), 200


# @testable true
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
# @tests tests_e2e/005_pages/test_005j_page_notes.py::test_page_note_text_photo_and_delete_modal
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_rejects_non_csv_upload
# @pair request-errors:plain-validation
def error(error, exception=None):
    if exception:
        exceptions.capture(exception)
    return Response(str(error), status=422, mimetype="text/plain")


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::_contract_error_response
# @reason filter request tests assert the route-owned 400 response
def bad_request(error):
    return Response(str(error), status=400, mimetype="text/plain")


def not_found(error):
    return error, 404


def explain(prompt):
    preview = prompt.preview() if hasattr(prompt, "preview") else prompt.build()
    modal = render_template("reference/prompt.html", prompt=preview)
    return jsonify({"modal": modal}), 200


def cell(field, entity, column=None, embedded=False):
    template = get_template_attribute("cell.html", "format_table_cell")
    column_data = {"link": True, "parent": True}
    column_data.update(column or {})
    column = SimpleNamespace(**column_data)
    parent = SimpleNamespace(table=SimpleNamespace(embedded=embedded))
    return template(field, entity, column, parent), 200


# @testable true
# @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_visibility_panel_includes_category_form_columns
# @matrix category-index : missing-field mixed-form render
# @template cell.html::cell
def table(entities, parent):
    template = get_template_attribute("table.html", "table")
    return template(entities, parent), 200


def ok():
    return "", 200


def image_response(image_data, mimetype):
    return Response(image_data, mimetype=mimetype), 200


def file_response(
    file_data,
    mimetype,
    *,
    status=200,
    byte_range=None,
    accept_ranges=False,
):
    g.NO_CACHE = True
    response = Response(file_data, mimetype=mimetype, status=status)
    if accept_ranges:
        response.headers["Accept-Ranges"] = "bytes"
    if byte_range:
        response.headers["Content-Range"] = byte_range.content_range
        response.headers["Content-Length"] = str(byte_range.length)
    return response, status


def file_range_not_satisfiable(size, mimetype):
    g.NO_CACHE = True
    response = Response("", mimetype=mimetype, status=416)
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Range"] = f"bytes */{size}"
    return response, 416


def json_response(data, status=200):
    return jsonify(data), status


# @testable infrastructure
def publish_notification_state(state):
    """Attach compact notification state to the current response lifecycle."""
    g.NOTIFICATION_STATE = cache.public_notification_state(state)


# @testable true
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_update_category_info_from_tools
# @matrix web-headers : acknowledgement entity-revision local-save
def entity_response(response, *entities):
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


# @testable false
# @manual true
# @reason pending/completed notification replacement is exercised through notification workflows
# @matrix notifications : item-html pending target
def notification_item(notification):
    template = get_template_attribute("notifications.html", "item")
    return template(notification).strip()


# --- Index Responses ---


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_forms_index_page
# @tests tests_e2e/006_tasks/test_006c_task_index.py::test_tasks_table_columns
# @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_shows_public_users
# @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_renders_first_batch_before_cursor_continuation
# @pairs categories:first-batch indexes:rendering reconnect-refresh:root-fingerprint task-index:columns
def index(name, index, **context):
    fingerprint = (
        database_utility.site_fingerprint(f"/{name}/index")
        if name in {"forms", "tasks", "users"}
        else None
    )
    poll_channel = "categories" if name == "categories" else name
    poll_revision = (
        channel_revision(
            poll_channel,
            current_user,
            site_fingerprints={f"/{name}/index": fingerprint},
        )
        if fingerprint
        else channel_revisions((poll_channel,), current_user)[poll_channel]
    )
    return (
        render_template(
            f"{name}/index.html",
            index=index,
            fingerprint=fingerprint,
            poll_channel=poll_channel,
            poll_revision=poll_revision,
            **context,
        ),
        200,
    )


def rows(entities, parent):
    entities = entities if isinstance(entities, list) else [entities]
    template = get_template_attribute("table.html", "rows")
    return f"<table>{template(entities, parent)}</table>", 200


# --- Document Responses ---


# @testable true
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_public_document_images_are_anonymous_and_revocable
# @matrix public-pages : metadata preview public-rendering
def public_document(entity):
    from lagniappe.core.tools.email.notifications.links import absolute_url
    from lagniappe.core.tools.site import public_pages

    canonical_url = absolute_url(
        url_for("pages.public", public_id=entity.public_id)
    )

    # @testable false
    # @covered-by lagniappe/web/responses.py::public_document
    # @reason route-specific absolute image adapter is part of public rendering
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


def shared_document(**kwargs):
    editor_document = {
        "markup": kwargs.get("html"),
        "state": kwargs.get("state"),
    }

    return jsonify(editor_document)


def document_html(html):
    return jsonify({"markup": html}), 200


def document_image(url):
    return jsonify({"src": url}), 200


# --- Task Responses ---


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def page_task(task, **extra):
    submission = task.properties.submission.form_value
    template = get_template_attribute("pages/tasks.html", "task")
    schema = task.form.schema if task.form else None
    return entity_response(
        (
            jsonify(
                {
                    "html": template(task, task.page),
                    "schema": schema,
                    "submission": submission,
                    **extra,
                }
            ),
            200,
        ),
        task,
        task.page,
    )


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def task_settings(task):
    template = get_template_attribute("pages/tasks.html", "settings_form")
    return entity_response((template(task, task.page), 200), task)


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
# @matrix task-combine : checkbox-form compatible
def task_combine_form(task, compatible):
    template = get_template_attribute("pages/tasks.html", "combine_form")
    return template(task, compatible), 200


# @testable true
# @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
# @matrix task-combine : delta ordering remove upsert
def task_combine_delta(main, removed, page):
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


def form_submission(entity):
    form = entity.form

    schema = form.schema if form else None
    submission = entity.properties.submission.form_value if form else None
    html = (
        {p.id: p.value for p in form.html_fields}
        if form and isinstance(entity, Entities.TASK)
        else None
    )

    return jsonify(
        {"schema": schema, "submission": submission, "html_fields": html}
    ), 200


def expanded_table_cell(field):
    return jsonify(
        {"schema": field, "submission": field.form_value, "kind": field.kind}
    ), 200


def new_form_restriction(group):
    template = get_template_attribute("forms/restrictions.html", "group_access")
    return template(group), 200


# --- Page Responses ---


# @testable false
# @covered-by lagniappe/web/responses.py::page
# @covered-by lagniappe/web/responses.py::page_document_settings
# @reason response context adapter delegates extraction and normalization to tested services
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


# @testable infrastructure
def page(page, focus_task=None):
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


def page_tasks(page):
    return get_template_attribute("pages/tasks.html", "task_list")(page), 200


def page_files(page):
    return get_template_attribute("pages/files.html", "file_list")(
        page, page.files
    ), 200


def new_file_upload(file, page):
    template = get_template_attribute("pages/files.html", "file_list_item")
    files = file if isinstance(file, (list, tuple)) else [file]
    return "".join(template(uploaded, page) for uploaded in files), 200


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def page_info(page, **extra):
    template = get_template_attribute("pages/info.html", "info_form")
    schema = page.form.schema if page.form else None
    submission = page.properties.submission.form_value if page.form else None
    return entity_response(
        (
            jsonify(
                {
                    "html": template(page),
                    "schema": schema,
                    "submission": submission,
                    **extra,
                }
            ),
            200,
        ),
        page,
    )


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def user_settings(page):
    template = get_template_attribute("pages/info.html", "user_settings")
    schema = page.form.schema if page.form else None
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


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def page_permissions(page):
    template = get_template_attribute("pages/info.html", "permissions_form")
    return entity_response((template(page), 200), page)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def page_document_settings(entity):
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


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def page_view_access(page):
    group_list_template = get_template_attribute(
        "pages/restrictions.html", "restricted_group_list"
    )
    group_list = group_list_template(page)

    viewers = [{"icon": "siteOwner", "text": "Site Owner", "kind": "user"}]
    for group in page.view_access:
        if group.name == "public":
            viewers.append({"icon": "users", "text": "Public", "kind": "group"})
        else:
            viewers.append({"icon": "group", "text": group.name, "kind": "group"})

    data = {
        "viewers": viewers,
        "group_list": group_list,
    }
    return entity_response((jsonify(data), 200), page)


def page_image(page):
    template = get_template_attribute("pages/photo.html", "dropzone")
    return template(page), 200


# --- Category Responses ---


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def category_info(category):
    template = get_template_attribute("categories/tools.html", "category_info")
    return entity_response((template(category), 200), category)


# --- Project Responses ---


def project_view(project):
    return render_template("projects/project.html", project=project), 200


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def project_info(project):
    template = get_template_attribute("projects/info.html", "info_form")
    return entity_response((template(project), 200), project)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def new_model_task(model_task):
    template = get_template_attribute("projects/model_tasks.html", "model_task")
    return entity_response(
        (template(model_task), 200),
        model_task,
        model_task.project,
    )


# --- File Responses ---


def file_page(file):
    return render_template("files/file.html", file=file), 200


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def file_info(file):
    return entity_response(
        (get_template_attribute("files/info.html", "info_form")(file), 200),
        file,
    )


# @testable true
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_download_uses_original_filename_and_mimetype
# @matrix file : download filename mimetype
def file_download(file_entity):
    g.NO_CACHE = True
    asset = file_entity.properties.file.value
    if asset is None:
        return not_found("File not found")

    filename = file_entity.filename
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
        return redirect(asset.url), 302

    content = asset.get()

    response = make_response(content)
    response.headers["Content-Disposition"] = disposition
    response.headers["Content-Type"] = mimetype or "application/octet-stream"

    return response, 200


# @testable infrastructure
def ingress_progress(file):
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


def select_index_field(file):
    template = get_template_attribute("files/status/verify.html", "index_select")
    return template(file), 200


def ingress_delete_imported(file):
    return render_template("delete/ingress_imported.html", file=file), 200


# --- Home Responses ---


def new_category(category):
    template = get_template_attribute("home/categories.html", "category")
    return template(category), 200


def new_project(project):
    template = get_template_attribute("home/projects.html", "project")
    return template(project), 200


def new_page(page):
    template = get_template_attribute("home/pages.html", "page")
    return template(page), 200


# @testable false
# @covered-by lagniappe/web/routes/pages/notes.py::create_note
# @reason shared rendering response is exercised through the public note creation routes
def new_note(note, surface="home"):
    template = get_template_attribute("notes.html", "note_item")
    return template(note, surface), 200


def new_ingress_file(file):
    template = get_template_attribute("home/ingress.html", "imported_file")
    return template(file), 200


def new_tool_report(report):
    template = get_template_attribute("home/tools.html", "report_item")
    return template(report), 200


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::create_organize_report
# @covered-by lagniappe/web/routes/tools/main.py::run_report
# @reason deferred report acknowledgement is route plumbing verified through create and execution workflows
def deferred_tool_report(report, notification, job=None):
    template = get_template_attribute("home/tools.html", "report_item")
    if notification is not None:
        notification = (
            Entities.fetch_one(notification.urlsafe_key, request=Fetch.direct())
            or notification
        )
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


# @testable false
# @covered-by lagniappe/web/routes/tools/main.py::report
# @reason report route coverage owns status hydration and full-page rendering
def tool_report(report):
    render_operation_statuses((report,), current_user)
    return render_template("tools/report.html", report=report), 200


# @testable true
# @tests tests_e2e/002_home/test_002h_home_permissions.py::test_category_home_rows_only_offer_star_controls
# @tests tests_e2e/002_home/test_002h_home_permissions.py::test_empty_home_model_lists_settle_to_disabled_zero_state
# @pairs permissions:active-tasks-directory permissions:home-actions permissions:own-page-only
# @template home/categories.html::category
# @template home/directory.html::list
# @template home/home.html::create
def home_page(home):
    poll_revisions = channel_revisions(("home-notes", "tasks"), current_user)
    return (
        render_template(
            "home/home.html",
            home=home,
            poll_revisions=poll_revisions,
        ),
        200,
    )


# @testable true
# @tests tests_e2e/002_home/test_002f_home_directory.py::test_admin_directory_link_opens_admin_settings
# @tests tests_e2e/008_users/test_008f_site_administrators.py::test_site_settings_requires_administrator
# @matrix admin : page-load site-settings
def admin_page():
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


# @testable false
# @covered-by lagniappe/web/routes/home/site.py::privacy_policy
# @reason static public document rendered through the route
def privacy_policy():
    return render_template("home/privacy_policy.html"), 200


# @testable false
# @covered-by lagniappe/web/routes/home/site.py::reporting_privacy
# @reason static public document rendered through the route
def reporting_privacy():
    return render_template("home/reporting_privacy.html"), 200


# @testable false
# @covered-by lagniappe/web/routes/home/main.py::get
def activity(section):
    return get_template_attribute("home/notes.html", "list")(section), 200


# @testable false
# @covered-by lagniappe/web/routes/pages/notes.py::get_notes
# @reason response wrapper delegates Page note rendering to the tested collection route
def page_notes(notes, page):
    template = get_template_attribute("pages/notes.html", "note_list")
    return template(page, notes), 200


# @testable infrastructure
def notifications(notifications, *, aggregate, cursor=None, can_message=False):
    template = get_template_attribute("notifications.html", "list")
    return template(notifications, aggregate, cursor, can_message), 200


# @testable infrastructure
def message_page(*, initial_conversation=None, can_message=False):
    return render_template(
        "messages/index.html",
        initial_conversation=initial_conversation,
        can_message=can_message,
    ), 200


# @testable infrastructure
# @covered-by lagniappe/web/routes/messages/main.py::clear_modal
def message_clear_modal(key, *, peer_name):
    return render_template(
        "delete/conversation.html",
        key=key,
        peer_name=peer_name,
    ), 200


# @testable false
# @covered-by lagniappe/web/routes/home/main.py::get
def home_section(section):
    if section.id == "ingress":
        return get_template_attribute("home/ingress.html", "import_list")(section), 200
    elif section.id == "tools":
        return get_template_attribute("home/tools.html", "report_list")(section), 200
    elif section.id == "starred":
        return get_template_attribute("home/starred.html", "list")(section), 200
    elif section.id == "tasks":
        count_template = get_template_attribute("common.html", "task_count")
        return count_template(section.count) + get_template_attribute(
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


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::update
# @reason route response adapter is exercised through its owning task mutation
def home_task_list():
    home = Entities.HOME()
    template = get_template_attribute("home/tasks.html", "list")
    task_list_html = template(home.section("tasks"))

    task_count = database_get.user_task_count(current_user.page)
    count_html = get_template_attribute("common.html", "task_count")(task_count)

    return count_html + task_list_html, 200


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::update
# @reason route response adapter is exercised through its owning task mutation
def home_task(task):
    template = get_template_attribute("home/tasks.html", "task")
    count = database_get.user_task_count(current_user.page)
    return jsonify({"html": template(task), "count": count}), 200


# @testable false
# @covered-by lagniappe/web/routes/tasks/main.py::update
# @reason route response adapter is exercised through its owning task mutation
def home_task_removed():
    count = database_get.user_task_count(current_user.page)
    return jsonify({"removed": True, "count": count}), 200


# --- Filter Responses ---


# @testable false
# @covered-by lagniappe/web/responses.py::filtered_task_index
# @covered-by lagniappe/web/responses.py::filtered_page_index
# @reason filtered index response tests exercise the rendered polling contract
def _filtered_index_poll_context(channel):
    return {
        "poll_channel": channel,
        "poll_revision": channel_revisions((channel,), current_user)[channel],
    }


def new_filter(filter):
    template = get_template_attribute("filters.html", "filter_item")
    return template(filter), 200


def saved_filters(entity, filters):
    if isinstance(entity, Entities.PROJECT):
        template = get_template_attribute("projects/filters.html", "saved_filters")
        return template(entity, filters), 200
    elif isinstance(entity, Entities.CATEGORY):
        template = get_template_attribute("categories/tools.html", "saved_filters")
        return template(entity, filters), 200


# @testable true
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_saved_in_progress_filter_removes_completed_task_after_back_navigation
# @tests tests_e2e/004_projects/test_004f_project_filters.py::test_saved_in_progress_filter_refreshes_after_reconnect
# @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_completed_button
# @pairs filters:saved-filter polling:task-index reconnect-refresh:task-index
def filtered_task_index(tasks, filter):
    return (
        render_template(
            "tasks/index.html",
            tasks=tasks,
            filtered=filter,
            **_filtered_index_poll_context("tasks"),
        ),
        200,
    )


# @testable true
# @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filter_save_and_run
# @pairs polling:category-index reconnect-refresh:category-index
def filtered_page_index(pages, filter):
    return (
        render_template(
            "categories/index.html",
            pages=pages,
            filtered=filter,
            **_filtered_index_poll_context("categories"),
        ),
        200,
    )


# @testable false
# @covered-by lagniappe/web/routes/filters/main.py::condition
# @covered-by lagniappe/web/routes/filters/main.py::options
# @reason condition and option routes own rendered filter response behavior
def filter_condition(data, condition, filter=False, options=False):
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


def create_group(group):
    form_partial = get_template_attribute("users/tools.html", "group_permissions")
    selector_partial = get_template_attribute(
        "users/tools.html",
        "group_selector",
    )

    return form_partial(group) + selector_partial(group), 200


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::entity_response
def group_permissions(group, public=False, update=False):
    data = group.properties.permissions.permissions_form()
    if not public:
        data["name"] = group.name

    if public:
        template = get_template_attribute("users/tools.html", "public_permissions")
    else:
        template = get_template_attribute("users/tools.html", "group_permissions")

    if update:
        data["html"] = template(group)

    return entity_response((jsonify(data), 200), group)


# --- Search Responses ---


def index_results_html(results, create_command=None):
    template = get_template_attribute("nav.html", "index_results")
    return template(results, len(results), create_command=create_command)


def index_results(results, create_command=None):
    return {"results": index_results_html(results, create_command)}, 200


def created_index_result(result):
    return jsonify(
        {
            "option": result["details"],
            "results": index_results_html([result]),
        }
    ), 200


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_click_result_navigates
# @tests tests_e2e/009_search/test_009a_search_page.py::test_result_links_correct
# @tests tests_e2e/009_search/test_009a_search_page.py::test_navbar_task_results_render_current_completion_state
# @matrix search : navbar-results result-links result-navigation task-model
def search_results(query, results, total):
    template = get_template_attribute("nav.html", "search_results")
    return {"results": template(query, results, total)}, 200


# @testable true
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_page_shows_query
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_no_results
# @tests tests_e2e/009_search/test_009a_search_page.py::test_search_result_titles
# @tests tests_e2e/009_search/test_009a_search_page.py::test_task_facet_includes_task_and_model_results_with_links
# @matrix search : no-results query-display result-links result-title
def search_page(q, results, pagination):
    return render_template(
        "search/search.html",
        query=q,
        results=results,
        pagination=pagination,
        facets=SearchFacets,
    ), 200


def location_results(results, total):
    template = get_template_attribute("nav.html", "location_results")
    return {"results": template(results, total)}, 200


# --- Delete Responses ---


# @testable true
# @tests tests_e2e/003_forms/test_003a_forms.py::test_form_delete_modal_lists_page_and_task_users
# @matrix forms : delete-modal instance-query preview-limit
def delete_entity(entity=None, key=None):
    if not entity:
        return render_template("delete/dne.html", key=key), 200

    kind = "user" if entity.kind == "page" and entity.db.get("user") else entity.kind

    if kind == "form":
        instances = [
            instance
            for instance in Entities.fetch(
                *database_get.form_instance_users(entity.key),
                request=Fetch.direct(),
            )
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


# @testable true
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_search_metadata_and_navigation
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_discovery_follows_live_setting
# @matrix manual : canonical-url metadata search-discovery section-navigation
def manual_index(section, index):
    from lagniappe.core.tools.site import public_pages

    page_content = smartypants(render_template(f"manual/content/{section}.html"))
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
        "content": page_content,
        "sections": sections,
        "search_metadata": search_metadata,
        "public_page": public_page,
    }
    if public_page:
        context.update(page_mode="public")

    response = make_response(render_template("manual/index.html", **context))
    if search_metadata:
        response.headers["X-Robots-Tag"] = search_metadata["robots"]
    return response


# @testable true
# @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_search_metadata_and_navigation
# @matrix manual : ajax-section noindex
def manual_content(section):
    response = make_response(
        smartypants(render_template(f"manual/content/{section}.html"))
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def reference_topic(section):
    return smartypants(render_template(f"reference/{section}.html")), 200


# @testable true
# @tests tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_sections_expand_help_and_configuration
# @matrix admin : configuration-display recovery-export secrets web-headers
def reference_environment_variables(variables, download=False):
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


# @testable true
# @tests tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_sections_expand_help_and_configuration
# @matrix admin : configuration-display secrets
def site_configuration(variables):
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
