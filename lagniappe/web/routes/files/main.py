from types import SimpleNamespace

from flask import request
from flask_login import current_user

from lagniappe.core.definitions import AI, Action, Resource
from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.tools import ai
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.web.auth import (
    abort_public_user_action,
    permission,
    require_ai_access,
)
from lagniappe.web import responses
from lagniappe.web import direct_uploads

from . import files


# @testable true
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_text_tab_renders_uploaded_text_content
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_text_file_renders_original_content_in_text_tab
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_image_shows_desktop_preview
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_pdf_renders_pdf_preview_widget
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_pdf_toolbar_navigates_pages
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_mobile_preview_uses_preview_tab
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_mobile_pdf_preview_renders_canvas
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_page_shows_linked_page_and_task_badges
# @matrix file : badges file-mobile file-upload linked-entities load page-upload pdf-preview pdf-toolbar preview reverse-links tabs text-asset text-tab
@files.route("/<key>", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def view(key, **kwargs):
    file = kwargs["entity"]

    return responses.file_page(file)


# @testable infrastructure
# @covered-by lagniappe/web/responses.py::file_info
@files.route("/<key>/info/replace", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def info(key, **kwargs):
    return responses.file_info(kwargs["entity"])


# @testable true
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_download_uses_original_filename_and_mimetype
# @tests tests_unit/test_006_file_properties.py::test_uploaded_file_story_lists_pages_that_reference_it
# @matrix file : download filename mimetype
# @pair file:attached-pages
@files.route("/<key>/download", methods=["GET"])
@permission(Resource.FILE, Action.VIEW, no_store=True)
def download(key, **kwargs):
    entity = kwargs["entity"]
    if not isinstance(entity, Entities.FILE):
        return responses.not_found("File not found")

    return responses.file_download(entity)


# @testable true
# @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
# @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_file_to_page
# @matrix ingress pages : delete
@files.route("/<key>/delete", methods=["DELETE"])
@permission(Resource.FILE, Action.DELETE)
def delete(key, **kwargs):
    abort_public_user_action()

    file = kwargs["entity"]
    Entities.delete(file)
    return responses.ok()


# @testable true
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_info_update_persists_name_and_summary
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_info_moves_between_page_and_task
# @tests tests_unit/test_006_file_properties.py::test_extract_process
# @tests tests_unit/test_006_file_properties.py::test_summarize_process
# @matrix file : add display-name extract info-update linked-pages reload remove summarize summary
@files.route("/<key>/update", methods=["PUT"])
@permission(Resource.FILE, Action.EDIT)
def update(key, **kwargs):
    abort_public_user_action()

    if (
        request.form.get("enable-summarize") is not None
        or request.form.get("summarize") is not None
    ):
        require_ai_access(AI.CREATE)

    file = kwargs["entity"]
    if request.form.get("pages-control") or request.form.getlist("page"):
        return responses.error("Select one File owner.")
    changed = False
    if request.form.get("owner-control"):
        try:
            owner = SubmittedReferenceResolver(current_user, request.form.get("owner-key")).one(
                request.form.get("owner-key"), expected=(Entities.PAGE, Entities.TASK),
                action=Action.EDIT, required=True,
            )
            changed = file.move_to(owner)
        except (exceptions.ValidationError, ValueError) as error:
            return responses.error(str(error))
    file.update(request.form)
    Entities.save(file)
    file.dispatch_pending_processing()
    if changed:
        return responses.json_response({"reload": True})
    return responses.file_info(file)


# @testable false
# @covered-by lagniappe/web/routes/files/main.py::upload
# @reason upload parsing is exercised through the page upload route
def _uploaded_page_files():
    uploads = [
        *request.files.getlist("file-upload"),
        *direct_uploads.direct_upload_files("file-upload"),
    ]
    return [upload for upload in uploads if getattr(upload, "filename", None)]


# @testable false
# @covered-by lagniappe/web/routes/files/main.py::upload
# @reason per-upload metadata normalization is owned by the page upload route
def _page_upload_data(upload, multiple_uploads=False, batch_summarize=False):
    data = request.form.to_dict()
    data["filename"] = upload.filename
    data["mimetype"] = upload.content_type

    if multiple_uploads:
        data.pop("display-name", None)
        data.pop("name", None)

    if batch_summarize:
        data.pop("enable-summarize", None)
        data.pop("summarize", None)
        data.pop("search-summary", None)

    return data


# @testable false
# @covered-by lagniappe/web/routes/files/main.py::upload
# @reason batch summaries reuse the organize prepass and are route-local glue
def _summarize_page_uploads(files):
    if len(files) <= 1 or request.form.get("summarize") is None:
        return []

    report = SimpleNamespace(input_files=files)
    return ai.summarize_report_input_files(
        report,
        search=request.form.get("search-summary") is not None,
        raise_quota=False,
    )


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_as_html
# @tests tests_unit/test_006_file_properties.py::test_text_asset_falls_back_to_original_text_file
# @matrix file : html-preview text-asset
@files.route("/<key>/html", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def get_html(key, **kwargs):
    file = kwargs["entity"]

    return responses.document_html(file.properties.text.markup)


# @testable true
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_file_to_page
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_multiple_files_to_page_without_existing_file_select
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_page_editor_without_ai_create_is_rejected_before_batch_summary
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_text_file_renders_original_content_in_text_tab
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_image_shows_desktop_preview
# @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_forged_hidden_file_key_cannot_be_linked_to_editable_task_or_page
# @matrix ai : access-gate batch-summary provider-boundary
# @matrix file pages : file-upload multi-file page-upload submitted-reference
@files.route("/<key>/upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def upload(key, **kwargs):
    abort_public_user_action()

    summarize_requested = request.form.get("summarize") is not None
    if summarize_requested:
        require_ai_access(AI.CREATE)

    page = kwargs["entity"]

    uploads = _uploaded_page_files()
    existing_file = request.form.get("existing-file")

    if existing_file:
        return responses.error("Upload a new File or move it from File Info.")

    if not uploads:
        return responses.error("No file uploaded")

    if uploads:
        multiple_uploads = len(uploads) > 1
        batch_summarize = multiple_uploads and summarize_requested
        uploaded_files = [
            Entities.FILE().create(
                page=page,
                upload=upload,
                data=_page_upload_data(
                    upload,
                    multiple_uploads=multiple_uploads,
                    batch_summarize=batch_summarize,
                ),
            )
            for upload in uploads
        ]
        _summarize_page_uploads(uploaded_files)
    Entities.save(*uploaded_files, page)
    for uploaded_file in uploaded_files:
        uploaded_file.dispatch_pending_processing()

    return responses.new_file_upload(uploaded_files, page)


# @testable false
# @covered-by lagniappe/web/routes/files/main.py::upload
# @reason route permission mirrors the final upload endpoint
@files.route("/<key>/upload/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def upload_direct(key, **kwargs):
    abort_public_user_action()

    return direct_uploads.direct_upload_response()
