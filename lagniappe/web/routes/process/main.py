from flask import jsonify, make_response, request, session
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import dates, filters, task_queue
from lagniappe.core.tools.notifications import create_process_notification
from lagniappe.core.tools.deferred_jobs import (
    DeferredJobInfrastructureError,
    DeferredJobs,
)
from lagniappe.core.tools.ingress import IngressService
from . import process


# Validate OIDC token from Cloud Tasks
# @testable false
# @manual true
# @reason requires Cloud Tasks OIDC provider validation
def authenticate_task(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]  # Remove 'Bearer ' prefix

    try:
        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=request.url
        )

        if claims.get("iss") != "https://accounts.google.com":
            return None

        expected_email = CONFIG.INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL

        if not expected_email or claims.get("email") != expected_email:
            return None

        payload = request.get_json(silent=True)
        return payload if isinstance(payload, dict) else {}

    except Exception as e:
        exceptions.capture(
            e,
            {
                "process": {
                    "operation": "authenticate_task",
                    "request": request.get_json(silent=True),
                }
            },
        )
        return None


# @testable false
# @manual true
# @reason requires Cloud Tasks OIDC authentication and provider delivery
# @features deferred-jobs
# @dimensions process-route versioned-envelope
@process.route("/jobs", methods=["POST"])
def deferred_job_process():
    """Run one durable job; Cloud Tasks carries only its Datastore key."""
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if set(payload) != {"job_key"} or not payload.get("job_key"):
        return jsonify({"success": False, "error": "Invalid job payload."}), 400

    try:
        result = DeferredJobs.run(payload["job_key"])
    except DeferredJobInfrastructureError as error:
        return jsonify({"success": False, "error": str(error)}), 503

    return jsonify(
        {
            "success": result.success,
            "state": result.state.value,
            "error": result.error,
        }
    ), 200


# @testable false
# @manual true
# @reason requires Cloud Tasks OIDC authentication and delayed delivery
# @features deferred-jobs notifications
# @dimensions long-running feedback
@process.route("/jobs/feedback", methods=["POST"])
def deferred_job_feedback():
    """Publish a user-facing update if a deferred job is still active."""
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if set(payload) != {"job_key"} or not payload.get("job_key"):
        return jsonify({"success": False, "error": "Invalid job payload."}), 400
    return jsonify(
        {
            "success": True,
            "updated": DeferredJobs.feedback(payload["job_key"]),
        }
    )


# @testable false
# @manual true
# @reason requires Cloud Scheduler OIDC authentication and production queue state
# @features deferred-jobs
# @dimensions reconciliation scheduler recovery
@process.route("/jobs/reconcile", methods=["POST"])
def deferred_job_reconcile():
    """Recover stranded deferred work from durable dispatch metadata."""
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if payload != {"reconcile": True}:
        return jsonify({"success": False, "error": "Invalid reconcile payload."}), 400
    return jsonify({"success": True, **DeferredJobs.reconcile()}), 200


# @testable true
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_uncomplete_after_complete
# @tests tests_unit/test_013e_task_complete_lifecycle.py::test_task_complete_with_schedule_queues_uncomplete
@process.route("/uncomplete-task", methods=["POST"])
def uncomplete_task():
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if not payload.get("key") or not set(payload).issubset({"key", "next_due_date"}):
        return jsonify({"success": False, "error": "Invalid task payload."}), 400

    task = None

    try:
        task = Entities.fetch_one(
            payload["key"],
            request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
        )
        task.uncomplete()
        if payload.get("next_due_date"):
            task.due_date = dates.utc_date_string_to_utc_datetime(
                payload["next_due_date"]
            )
        task.save()
    except Exception as e:
        exceptions.capture(
            e,
            context={
                "operation": "uncomplete_task",
                "payload": payload,
                "task": task.db if task else None,
            },
        )
        return jsonify({"success": False, "error": str(e)}), 500

    return make_response("", 200)


# @testable true
# @tests tests_e2e/001_site/test_001a_environment.py::test_cache_setup
# @tests tests_e2e/001_site/test_001e_entity_lifecycle.py::test_entity_save_persists_relations_process_payloads_and_cache
@process.route("/update-cache", methods=["POST"])
def update_cache():
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if set(payload) != {"cache_key", "entity_key", "user_key"} or not all(
        payload.get(key) for key in ("cache_key", "entity_key", "user_key")
    ):
        return jsonify({"success": False, "error": "Invalid cache payload."}), 400

    user = None
    entity = None

    try:
        user = Entities.USER(payload.get("user_key"))
        entity = Entities.fetch_one(
            payload.get("entity_key"),
            request=Fetch.direct(),
        )
        filters.FilterCache(entity, user=user).update(queue=False)
    except Exception as e:
        exceptions.capture(
            e,
            context={
                "operation": "update_cache",
                "payload": payload,
                "user": user.db if user else None,
                "entity": entity.db if entity else None,
            },
        )
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True}), 200


# @testable true
# @tests tests_unit/test_006b_ingress_entity.py::test_importer_story_processes_page_rows_into_entities_and_results
# @tests tests_unit/test_006b_ingress_entity.py::test_completed_ingress_shows_results
@process.route("/ingress", methods=["POST"])
def ingress():
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if not set(payload).issubset({"key", "timezone", "user_key"}) or not all(
        payload.get(key) for key in ("key", "user_key")
    ):
        return jsonify({"success": False, "error": "Invalid ingress payload."}), 400

    session["timezone"] = payload.get("timezone", "UTC")

    file = None
    service = None

    try:
        file = Entities.fetch_one(
            payload["key"],
            request=Fetch.direct(),
        )
        service = IngressService(file)
        outcome = service.run_batch()

        if outcome.state == "stopped":
            return jsonify({"success": True}), 200

        if outcome.state == "completed":
            create_process_notification(
                payload,
                f"Data import complete for {service.entity.name}",
            )
        elif outcome.dispatch_next:
            try:
                task_queue.create_task(
                    request.url,
                    payload,
                    task_id=service.idempotency_key(
                        f"dispatch:{service.execution.get('dispatch_sequence', 0)}"
                    )[:32],
                )
            except Exception as dispatch_error:
                exceptions.capture(
                    dispatch_error,
                    context={
                        "operation": "ingress_followup_dispatch",
                        "payload": payload,
                        "file": service.entity.db,
                    },
                )
                return jsonify({"success": False, "retry": True}), 503
    except Exception as e:
        exceptions.capture(
            e,
            context={
                "operation": "ingress",
                "payload": payload,
                "file": file.db if file else None,
            },
        )
        return jsonify({"success": False, "error": str(e)}), 200

    return jsonify({"success": True}), 200
