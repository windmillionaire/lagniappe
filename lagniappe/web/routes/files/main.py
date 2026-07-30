from types import SimpleNamespace

from flask import request

from lagniappe.core.definitions import AI, Action, Fetch, Resource
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, database
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
# @features file
# @dimensions load tabs text-tab text-asset preview pdf-preview pdf-toolbar file-upload page-upload file-mobile linked-entities reverse-links badges
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
# @features file
# @dimensions download filename mimetype
@files.route("/<key>/download", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def download(key, **kwargs):
    entity = kwargs["entity"]
    if not isinstance(entity, Entities.FILE):
        return responses.not_found("File not found")

    return responses.file_download(entity)


# @testable true
# @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
# @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_file_to_page
# @features ingress pages
# @dimensions delete
@files.route("/<key>/delete", methods=["DELETE"])
@permission(Resource.FILE, Action.DELETE)
def delete(key, **kwargs):
    abort_public_user_action()

    file = kwargs["entity"]
    removed_pages = []

    if hasattr(file.properties, "pages"):
        Entities.fetch(*file.pages, request=Fetch.direct())
        for p in [p for p in file.pages if p.allowed(Action.EDIT)]:
            if file.properties.pages.remove(p):
                removed_pages.append(p)
    else:
        Entities.delete(file)
        return responses.ok()

    if file.pages:
        Entities.save(file, *file.pages, *removed_pages)
    else:
        Entities.delete(file)
        Entities.save(*removed_pages)

    return responses.ok()


# @testable true
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_info_update_persists_name_and_summary
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_info_page_links_can_be_added_and_removed
# @tests tests_unit/test_006_file_properties.py::test_extract_process
# @tests tests_unit/test_006_file_properties.py::test_summarize_process
# @features file
# @dimensions info-update display-name summary extract summarize linked-pages add remove reload
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
    previous_pages = Entities.fetch(*file.pages, request=Fetch.direct())
    file.update(request.form)
    if request.form.get("pages-control") == "true":
        _update_file_pages(file, request.form)

    removed_pages = _removed_pages(previous_pages, file.pages)
    Entities.save(file, *file.pages, *removed_pages)
    file.dispatch_pending_processing()

    if _page_links_changed(previous_pages, file.pages):
        return responses.json_response({"reload": True})

    return responses.file_info(file)


# @testable false
# @covered-by lagniappe/web/routes/files/main.py::update
# @reason route-local parser preserves uneditable relations while applying submitted page links
def _update_file_pages(file, form):
    submitted_ids = set(form.getlist("page"))
    submitted_keys = {
        key
        for key in (database.get.datastore_key(identifier) for identifier in submitted_ids)
        if key
    }
    loaded_pages = Entities.fetch(
        *submitted_ids,
        *file.pages,
        request=Fetch.direct(),
    )
    pages_by_key = {page.key: page for page in loaded_pages}
    submitted = [
        page
        for page in loaded_pages
        if isinstance(page, Entities.PAGE)
        and page.key in submitted_keys
        and page.allowed(Action.EDIT)
    ]
    preserved = [
        pages_by_key.get(page.key, page)
        for page in file.pages
        if not pages_by_key.get(page.key, page).allowed(Action.EDIT)
    ]

    pages = {page.key: page for page in [*preserved, *submitted] if page}
    file.properties.pages.value = list(pages.values())


# @testable false
# @covered-by lagniappe/web/routes/files/main.py::update
# @reason small relation diff helper owned by the file info update route
def _removed_pages(previous_pages, current_pages):
    current_keys = {page.key for page in current_pages}
    return [page for page in previous_pages if page.key not in current_keys]


# @testable false
# @covered-by lagniappe/web/routes/files/main.py::update
# @reason small relation diff helper owned by the file info update route
def _page_links_changed(previous_pages, current_pages):
    previous_keys = {page.key for page in previous_pages}
    current_keys = {page.key for page in current_pages}
    return previous_keys != current_keys


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
@files.route("/<key>/html", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def get_html(key, **kwargs):
    file = kwargs["entity"]

    return responses.document_html(file.properties.text.markup)


# @testable true
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_file_to_page
# @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_multiple_files_to_page_hides_existing_file_select
# @tests tests_e2e/002_home/test_002n_file_consumer_routes.py::test_batch_page_upload_rejects_actor_without_ai_create_before_summary
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_text_file_renders_original_content_in_text_tab
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_image_shows_desktop_preview
# @pair file:file-upload
# @pair file:page-upload
# @pair file:multi-file
# @pair pages:file-upload
# @pair pages:page-upload
# @pair pages:multi-file
# @pair ai:batch-summary
# @pair ai:access-gate
# @pair ai:provider-boundary
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

    if not uploads and not existing_file:
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
    elif existing_file:
        uploaded_files = [Entities.FILE(existing_file)]
        uploaded_files[0].properties.pages.add(page)

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
