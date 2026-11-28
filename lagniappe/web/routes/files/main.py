from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from dataclasses import dataclass

from flask import Response, g, request

from lagniappe.core.definitions import AI, Action, Resource
from lagniappe.core.entities import Entities
from lagniappe.core import exceptions
from lagniappe.core.tools.ai.reporting.completion import files as report_files
from lagniappe.core.tools.auth.references import SubmittedReferenceResolver
from lagniappe.core.tools.files.constants import MAX_ARTIFACT_BYTES
from lagniappe.web.auth import (
    authenticated_user,
    abort_public_user_action,
    permission,
    require_ai_access,
)
from lagniappe.web import responses
from lagniappe.web import direct_uploads

from . import files


@files.route("/<key>", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def view(key: str, **kwargs: Unpack[EntityContext[models.File]]) -> ResponseReturnValue:
    file = kwargs["entity"]

    return responses.file_page(file)


@files.route("/<key>/info/replace", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def info(key: str, **kwargs: Unpack[EntityContext[models.File]]) -> ResponseReturnValue:
    return responses.file_info(kwargs["entity"])


@files.route("/<key>/download", methods=["GET"])
@permission(Resource.FILE, Action.VIEW, no_store=True)
def download(
    key: str, **kwargs: Unpack[EntityContext[models.File | models.Ingress]]
) -> ResponseReturnValue:
    entity = kwargs["entity"]
    if not isinstance(entity, (Entities.FILE, Entities.INGRESS)):
        return responses.not_found("File not found")

    return responses.file_download(entity)


@files.route("/<key>/artifact-preview", methods=["GET"])
@permission(Resource.FILE, Action.VIEW, no_store=True)
def artifact_preview(
    key: str, **kwargs: Unpack[EntityContext[models.File]]
) -> ResponseReturnValue:
    file = kwargs["entity"]
    if not isinstance(file, Entities.FILE) or not file.is_artifact:
        return responses.not_found("Artifact not found")
    asset = file.file
    if asset is None or asset.size is None or not 0 < asset.size <= MAX_ARTIFACT_BYTES:
        return responses.not_found("Artifact not found")
    content = asset.get()
    if not content or len(content) > MAX_ARTIFACT_BYTES:
        return responses.not_found("Artifact not found")
    g.artifact_preview = True
    return Response(content, content_type="text/html; charset=utf-8")


@files.route("/<key>/delete", methods=["DELETE"])
@permission(Resource.FILE, Action.DELETE)
def delete(
    key: str, **kwargs: Unpack[EntityContext[models.File]]
) -> ResponseReturnValue:
    abort_public_user_action()

    file = kwargs["entity"]
    Entities.delete(file)
    return responses.ok()


@files.route("/<key>/update", methods=["PUT"])
@permission(Resource.FILE, Action.EDIT)
def update(
    key: str, **kwargs: Unpack[EntityContext[models.File]]
) -> ResponseReturnValue:
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
            owner = SubmittedReferenceResolver(authenticated_user(), request.form.get("owner-key")).one(
                request.form.get("owner-key"), expected=(Entities.PAGE, Entities.TASK),
                action=Action.EDIT, required=True,
            )
            changed = file.move_to(owner)
        except (exceptions.ValidationError, ValueError) as error:
            return responses.error(str(error))
    file.update(request.form)
    Entities.save(file)
    file.dispatch_pending_processing(actor=authenticated_user())
    if changed:
        return responses.json_response({"reload": True})
    return responses.file_info(file)


def _uploaded_page_files():
    uploads = [
        *request.files.getlist("file-upload"),
        *direct_uploads.direct_upload_files("file-upload"),
    ]
    return [upload for upload in uploads if getattr(upload, "filename", None)]


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


@dataclass
class _PageUploadBatch:
    input_files: list[models.File]


def _summarize_page_uploads(files: list[models.File]) -> list[models.File]:
    if len(files) <= 1 or request.form.get("summarize") is None:
        return []

    report = _PageUploadBatch(files)
    return report_files.summarize_report_input_files(
        report,
        search=request.form.get("search-summary") is not None,
        raise_quota=False,
    )


@files.route("/<key>/html", methods=["GET"])
@permission(Resource.FILE, Action.VIEW)
def get_html(
    key: str, **kwargs: Unpack[EntityContext[models.File]]
) -> ResponseReturnValue:
    file = kwargs["entity"]

    markup = file.properties.text.markup
    return responses.document_html(markup if isinstance(markup, str) else None)


@files.route("/<key>/upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def upload(
    key: str, **kwargs: Unpack[EntityContext[models.Page]]
) -> ResponseReturnValue:
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
        uploaded_file.dispatch_pending_processing(actor=authenticated_user())

    return responses.new_file_upload(uploaded_files, page)


@files.route("/<key>/upload/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def upload_direct(key: str, **kwargs: object) -> ResponseReturnValue:
    abort_public_user_action()

    return direct_uploads.direct_upload_response()
