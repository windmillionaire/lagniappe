from flask import request, abort, get_template_attribute
from flask_login import current_user

from lagniappe.core.definitions import AI, Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.tools import ai
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.files.html import clean_html
from lagniappe.web.auth import (
    abort_public_user_action,
    permission,
    require_ai_access,
)
from lagniappe.web import responses
from lagniappe.web import direct_uploads

from . import assets


# @testable true
# @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
# @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_editor_recovers_from_failed_load_and_save
# @matrix html-field : authoritative-content form-asset render-fetch retry submitter-key
@assets.route("<key>/html/<field_id>", methods=["GET"])
@permission(requested=Action.VIEW)
def html_field(key, field_id, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    form = entity if isinstance(entity, Entities.FORM) else entity.form
    html = form.get_html_field(field_id) if form else None
    return responses.document_html(html)


# @testable true
# @tests tests_unit/test_004_form_properties.py::test_form_html_fields
# @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_editor_recovers_from_failed_load_and_save
# @matrix html-field : form-asset intentional-clear server-acknowledgement
# @pair html-field:html-fields
@assets.route("<key>/form-html/<field_id>", methods=["PUT"])
@permission(requested=Action.EDIT)
def form_html(key, field_id, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    entity.set_html_field(field_id, request.json["html"])
    entity.save()
    return responses.ok()


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
# @pair sync:document
@assets.route("<key>/document/state", methods=["GET"])
@permission(requested=Action.VIEW)
def get_document_state(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    state = entity.properties.document.state
    return responses.shared_document(**state)


# @testable true
# @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image_generate_toggle
# @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image
# @matrix editor : image-generate-toggle image-upload
@assets.route("<key>/document/image", methods=["POST"])
@permission(requested=Action.EDIT)
def add_document_image(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    field = request.values.get("field")
    role = request.form.get("role", "upload")

    if isinstance(entity, Entities.FORM) and not field:
        return responses.error("field is required")

    if role == "generate":
        require_ai_access(AI.CREATE)
        user_prompt = request.form.get("prompt", "").strip()
        content = request.form.get("content", "").strip()
        if not user_prompt and not content:
            return responses.error("please describe the image you'd like to generate")

        if isinstance(entity, Entities.PAGE):
            page_details = entity.to_ai(user=current_user)
        else:
            page_details = {"document": content}

        try:
            prompt = ai.page_image_generation_prompt(
                user_prompt=user_prompt,
                page_details=page_details,
            )
            file = ai.generate_ai_image(prompt)
        except exceptions.AIException as e:
            return responses.error(str(e), exception=e)
    else:
        abort_public_user_action()
        file = request.files.get("add-image") or direct_uploads.direct_upload_file(
            "add-image"
        )
        if not file:
            return responses.error("no file selected")

    visibility = request.form.get("visibility", "private")

    if field and isinstance(entity, Entities.FORM):
        url = entity.add_html_field_image(field, file, visibility)
    elif field:
        url = entity.fields[field].add_image(file, visibility)
    else:
        url = entity.properties.document.add_image(file, visibility)

    Entities.save(entity)

    return responses.document_image(url)


# @testable false
# @covered-by lagniappe/web/routes/assets/editor.py::add_document_image
# @reason route permission mirrors the final document image upload endpoint
@assets.route("<key>/document/image/direct-upload", methods=["POST"])
@permission(requested=Action.EDIT)
def add_document_image_direct(key, **kwargs):
    abort_public_user_action()

    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/005_pages/test_005g_page_document_ai.py::test_generate_text_explain_includes_selected_text_context
# @tests tests_e2e/005_pages/test_005g_page_document_ai.py::test_generate_text_live_page_context_with_tasks_and_files
# @matrix ai : document-context explain generate-text live-provider page-context selected-text
@assets.route("<key>/document/generate", methods=["POST"])
@permission(requested=Action.EDIT)
def generate_text(key, **kwargs):
    require_ai_access(AI.CREATE)

    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    user_prompt = request.form.get("prompt")
    field = request.values.get("field")

    try:
        context_data = ai.document_generation_context(
            entity,
            user=current_user,
            field=field,
        )
    except exceptions.ValidationError as e:
        return responses.error(str(e))

    if request.form.get("selected_text"):
        context_data["selected_text"] = request.form.get("selected_text").strip()

    prompt = ai.text_generation_prompt(user_prompt, context_data)
    if request.form.get("role") == "explain":
        return responses.explain(prompt)

    try:
        html = ai.generate_ai_text(prompt)
    except exceptions.AIException as e:
        return responses.error(str(e), exception=e)

    cleaned_html = clean_html(html)
    return responses.document_html(cleaned_html)


# @testable true
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_created_on_save
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_restore
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
# @matrix editor : history-list history-pin history-restore
@assets.route("<key>/document/history", methods=["GET"])
@permission(requested=Action.VIEW)
def list_document_history(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    results = database_get.document_history(entity)
    entries = Entities.fetch(*results, request=Fetch.root()) if results else []
    entries = Entities.DOCUMENT_HISTORY.ordered(entries)
    return responses.json_response(
        {
            "entries": [entry.entry for entry in entries],
            "unpinned_count": sum(not entry.pinned for entry in entries),
        }
    )


# @testable true
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
# @matrix editor : current-content history-pin validation
@assets.route("<key>/document/history/pin", methods=["POST"])
@permission(requested=Action.EDIT)
def pin_document_history(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    payload = request.get_json(silent=True) or {}
    try:
        history = Entities.DOCUMENT_HISTORY.create(
            entity,
            name=payload.get("name"),
            html=payload.get("html"),
        )
    except exceptions.ValidationError as error:
        return responses.error(str(error))

    Entities.save(history)
    return responses.json_response({"entry": history.entry})


# @testable true
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
# @matrix editor : confirmation history-clear
@assets.route("<key>/document/history/unpinned", methods=["GET", "DELETE"])
@permission(requested=Action.EDIT)
def unpinned_document_history(key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    results = database_get.document_history(entity)
    entries = Entities.fetch(*results, request=Fetch.root()) if results else []
    unpinned_count = sum(not entry.pinned for entry in entries)

    if request.method == "GET":
        confirmation = get_template_attribute(
            "delete/document_history.html", "confirmation"
        )
        return confirmation(entity, unpinned_count), 200

    cleared = Entities.DOCUMENT_HISTORY.delete_unpinned(entries)
    return responses.json_response({"cleared": cleared})


# @testable true
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_document_history_restore
# @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
# @matrix editor : history-restore parent-scope
@assets.route("<key>/document/history/<history_key>", methods=["GET"])
@permission(requested=Action.VIEW)
def get_document_history(key, history_key, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )
    history = Entities.fetch_one(history_key, request=Fetch.direct())
    if (
        not isinstance(history, Entities.DOCUMENT_HISTORY)
        or history.key.parent != entity.key
    ):
        abort(404)

    doc_html = history.get_asset("document")
    return responses.shared_document(
        html=doc_html.get() if doc_html else None,
    )
