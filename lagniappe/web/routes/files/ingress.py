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
from lagniappe.core.tools import task_queue
from lagniappe.core.tools.ingress import IngressService
from lagniappe.web.auth import permission
from lagniappe.web import responses
from lagniappe.web import direct_uploads

from . import files


# @testable true
# @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
# @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_opens_with_processed_csv_status
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_error_state_persists_after_reopen
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_rejects_non_csv_upload
# @features ingress
# @dimensions file-input drag-drop upload-counts process-csv stage-wizard reopen non-csv validation
@files.route("/ingress", methods=["GET", "POST"])
@permission(Resource.SITE)
def ingress(**kwargs):
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
        service = IngressService(file)
        try:
            service.require_supported()
        except IngressError as error:
            return responses.json_response({"error": str(error)}, 409)
        if service.stage.name == "COMPLETED":
            removed = service.entity.prune_missing_results()
            if removed:
                service.entity.save()
        return responses.ingress_progress(service.entity)


# @testable false
# @covered-by lagniappe/web/routes/files/ingress.py::ingress
# @reason route permission mirrors the final ingress upload endpoint
@files.route("/ingress/direct-upload", methods=["POST"])
@permission(Resource.SITE)
def ingress_direct(**kwargs):
    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_stage_navigation_reconciles_downstream_status
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_error_state_persists_after_reopen
# @features ingress
# @dimensions stage-wizard set-stage error-handling persistence
@files.route("/ingress/<key>/stage", methods=["PUT", "GET"])
@permission(Resource.SITE)
def ingress_stage(key, **kwargs):
    file = kwargs["entity"]
    target = (
        (request.get_json(silent=True) or {}).get("stage")
        if request.method == "PUT"
        else request.args.get("stage")
    )
    try:
        IngressService(file).navigate(target)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    except ValueError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.ingress_progress(file)


# @testable true
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
# @features ingress
# @dimensions stage-wizard
@files.route("/ingress/<key>/update", methods=["PATCH"])
@permission(Resource.SITE)
def ingress_update(key, **kwargs):
    file = kwargs["entity"]
    try:
        section = IngressService(file).update_current(request.form)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.json_response(section)


# @testable true
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
# @tests tests_unit/test_006b_ingress_entity.py::test_next_advances_after_finalize
# @features ingress
# @dimensions stage-wizard
@files.route("/ingress/<key>/next", methods=["PUT"])
@permission(Resource.SITE)
def ingress_next(key, **kwargs):
    file = kwargs["entity"]
    try:
        IngressService(file).advance(request.form)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.ingress_progress(file)


# @testable true
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_page_import_stages
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_advances_through_task_import_stages
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_importing_stage_streams_results_and_completes
# @tests tests_unit/test_006b_ingress_entity.py::test_importer_story_processes_page_rows_into_entities_and_results
# @features ingress
# @dimensions stage-wizard verify-import import-results completed
@files.route("/ingress/<key>/import", methods=["POST"])
@permission(Resource.SITE)
def ingress_import(key, **kwargs):
    file = kwargs["entity"]
    service = IngressService(file)
    already_active = False
    try:
        already_active = (
            service.stage.name == "IMPORTING"
            and service.run_status
            in {
                IngressRunStatus.QUEUED.value,
                IngressRunStatus.RUNNING.value,
            }
        )
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
        return responses.ingress_progress(service.entity)

    if already_active:
        return responses.ingress_progress(service.entity)

    if CONFIG.local:
        while service.run_status == IngressRunStatus.QUEUED.value:
            service.run_batch(limit=2)
        return responses.ingress_progress(service.entity)

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
        service.mark_dispatch_failed(
            "Import could not be started. Please try again."
        )
        exceptions.capture(
            e,
            context={
                "operation": "ingress_import_start",
                "payload": payload,
                "file": service.entity.db,
            },
        )
        return responses.ingress_progress(service.entity)

    return responses.ingress_progress(service.entity)


# @testable false
# @manual true
# @reason production remote import stop/restart depends on asynchronous importing state
# @features ingress
# @dimensions stop restart
@files.route("/ingress/<key>/stop", methods=["POST"])
@permission(Resource.SITE)
def ingress_stop(key, **kwargs):
    file = kwargs["entity"]
    try:
        service = IngressService(file)
        service.stop()
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.ingress_progress(service.entity)


# @testable false
# @covered-by lagniappe/core/entities/ingress.py::Ingress.delete_imported_entities
# @reason route delegates bulk deletion to the core ingress entity and returns the standard progress payload
# @features ingress
# @dimensions bulk-delete row-results
@files.route("/ingress/<key>/delete-imported", methods=["GET", "DELETE"])
@permission(Resource.SITE)
def ingress_delete_imported(key, **kwargs):
    file = kwargs["entity"]

    if request.method == "GET":
        return responses.ingress_delete_imported(file)

    service = IngressService(file)
    service.delete_imported()
    service.save()

    return responses.ingress_progress(file)


# @testable true
# @tests tests_e2e/011_files/test_011b_file_ingress_wizard.py::test_import_wizard_task_page_form_lookup_updates_index_fields
# @tests tests_unit/test_006b_ingress_entity.py::test_import_wizard_story_builds_or_selects_the_submission_form
# @features ingress
# @dimensions task-import page-form-lookup
@files.route("/ingress/<key>/get-page-form", methods=["GET"])
@permission(Resource.SITE)
def ingress_get_page_form(key, **kwargs):
    file = kwargs["entity"]
    update_form_index = request.values.get("update-form-index")
    try:
        IngressService(file).select_page_form(update_form_index)
    except IngressError as error:
        return responses.json_response({"error": str(error)}, 409)
    return responses.select_index_field(file)
