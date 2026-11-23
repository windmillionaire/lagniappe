from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.entities import types as models
    from lagniappe.web.auth import EntityContext
    from typing import Unpack

from flask import request, session, url_for
from flask_login import current_user

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Fetch,
    IngressError,
    IngressRunStatus,
    Resource,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.services import task_queue
from lagniappe.core.tools.ingress import IngressService
from lagniappe.web.auth import permission
from lagniappe.web import responses
from lagniappe.web import direct_uploads

from . import files


@files.route("/ingress", methods=["GET", "POST"])
@permission(Resource.SITE)
def ingress(**kwargs: object) -> ResponseReturnValue:
    if request.method == "POST":
        upload = request.files.get("ingress-file") or direct_uploads.direct_upload_file(
            "ingress-file"
        )

        if not upload:
            return responses.error("No file uploaded")

        try:
            file = Entities.INGRESS.create(upload)
        except (ValueError, exceptions.ValidationError) as e:
            return responses.error(str(e), exception=e)

        file.save()

        return responses.new_ingress_file(file)

    else:
        key = request.args.get("key")
        loaded = Entities.fetch(key, request=Fetch.direct())
        file = loaded[0] if loaded else None
        if not isinstance(file, Entities.INGRESS):
            return responses.not_found("Import not found")
        service = IngressService(file)
        try:
            service.require_supported()
        except IngressError as error:
            return responses.json_response({"error": str(error)}, 409)
        if service.stage.name == "COMPLETED":
            removed = file.prune_missing_results()
            if removed:
                file.save()
        return responses.ingress_progress(file)


@files.route("/ingress/direct-upload", methods=["POST"])
@permission(Resource.SITE)
def ingress_direct(**kwargs: object) -> ResponseReturnValue:
    return direct_uploads.direct_upload_response()


@files.route("/ingress/<key>/stage", methods=["PUT", "GET"])
@permission(Resource.SITE)
def ingress_stage(
    key: str, **kwargs: Unpack[EntityContext[models.Ingress]]
) -> ResponseReturnValue:
    file = kwargs["entity"]
    target = (
        (request.get_json(silent=True) or {}).get("stage")
        if request.method == "PUT"
        else request.args.get("stage")
    )
    try:
        if not isinstance(target, str):
            raise ValueError(f"Invalid stage: {target}")
        IngressService(file).navigate(target)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    except ValueError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.ingress_progress(file)


@files.route("/ingress/<key>/update", methods=["PATCH"])
@permission(Resource.SITE)
def ingress_update(
    key: str, **kwargs: Unpack[EntityContext[models.Ingress]]
) -> ResponseReturnValue:
    file = kwargs["entity"]
    try:
        section = IngressService(file).update_current(request.form)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.json_response(section)


@files.route("/ingress/<key>/next", methods=["PUT"])
@permission(Resource.SITE)
def ingress_next(
    key: str, **kwargs: Unpack[EntityContext[models.Ingress]]
) -> ResponseReturnValue:
    file = kwargs["entity"]
    try:
        IngressService(file).advance(request.form)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.ingress_progress(file)


@files.route("/ingress/<key>/import", methods=["POST"])
@permission(Resource.SITE)
def ingress_import(
    key: str, **kwargs: Unpack[EntityContext[models.Ingress]]
) -> ResponseReturnValue:
    file = kwargs["entity"]
    service = IngressService(file)
    already_active = False
    try:
        already_active = service.stage.name == "IMPORTING" and service.run_status in {
            IngressRunStatus.QUEUED.value,
            IngressRunStatus.RUNNING.value,
        }
        service.start(
            {
                "timezone": session.get("timezone", "UTC"),
                "user_key": current_user.urlsafe_key,
            }
        )
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)

    if service.run_status not in {
        IngressRunStatus.QUEUED.value,
        IngressRunStatus.RUNNING.value,
    }:
        return responses.ingress_progress(file)

    if already_active:
        return responses.ingress_progress(file)

    if CONFIG.local:
        while service.run_status == IngressRunStatus.QUEUED.value:
            service.run_batch(limit=2)
        return responses.ingress_progress(file)

    task_endpoint = url_for("process.ingress", _external=True)
    payload = {
        "key": file.urlsafe_key,
        "timezone": session.get("timezone", "UTC"),
        "user_key": current_user.urlsafe_key,
    }
    try:
        task_queue.create_task(
            task_endpoint,
            payload,
            task_id=service.idempotency_key(
                f"dispatch:{service.execution.get('dispatch_sequence', 0)}"
            )[:32],
        )
    except Exception as e:
        service.mark_dispatch_failed("Import could not be started. Please try again.")
        exceptions.capture(
            e,
            context={
                "operation": "ingress_import_start",
                "payload": payload,
                "file": service.entity.db,
            },
        )
        return responses.ingress_progress(file)

    return responses.ingress_progress(file)


@files.route("/ingress/<key>/stop", methods=["POST"])
@permission(Resource.SITE)
def ingress_stop(
    key: str, **kwargs: Unpack[EntityContext[models.Ingress]]
) -> ResponseReturnValue:
    file = kwargs["entity"]
    try:
        if not isinstance(file, Entities.INGRESS):
            return responses.not_found("Import not found")
        service = IngressService(file)
        service.stop()
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.ingress_progress(file)


@files.route("/ingress/<key>/delete-imported", methods=["GET", "DELETE"])
@permission(Resource.SITE)
def ingress_delete_imported(
    key: str, **kwargs: Unpack[EntityContext[models.Ingress]]
) -> ResponseReturnValue:
    file = kwargs["entity"]

    if request.method == "GET":
        return responses.ingress_delete_imported(file)

    service = IngressService(file)
    service.delete_imported()
    service.save()

    return responses.ingress_progress(file)


@files.route("/ingress/<key>/get-page-form", methods=["GET"])
@permission(Resource.SITE)
def ingress_get_page_form(
    key: str, **kwargs: Unpack[EntityContext[models.Ingress]]
) -> ResponseReturnValue:
    file = kwargs["entity"]
    update_form_index = request.values.get("update-form-index")
    try:
        IngressService(file).select_page_form(update_form_index)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.select_index_field(file)
