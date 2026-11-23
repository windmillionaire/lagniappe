from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Request
    from flask.typing import ResponseReturnValue

from flask import jsonify, make_response, request, session
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from lagniappe import CONFIG
from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import dates, filters
from lagniappe.core.tools.services import task_queue
from lagniappe.core.tools.email.notifications import delivery as email_delivery
from lagniappe.core.tools.email.notifications.errors import NotificationEmailError
from lagniappe.core.tools.notifications.service import create_process_notification
from lagniappe.core.tools.deferred_jobs.errors import DeferredJobInfrastructureError
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.ingress import IngressService
from . import process


# Validate OIDC token from Cloud Tasks
def authenticate_task(request: Request) -> dict[str, object] | None:
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


@process.route("/jobs", methods=["POST"])
def deferred_job_process() -> ResponseReturnValue:
    """Run one durable job; Cloud Tasks carries only its Datastore key."""
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    job_key = payload.get("job_key")
    if set(payload) != {"job_key"} or not isinstance(job_key, str) or not job_key:
        return jsonify({"success": False, "error": "Invalid job payload."}), 400

    try:
        result = DeferredJobs.run(job_key)
    except DeferredJobInfrastructureError as error:
        return jsonify({"success": False, "error": str(error)}), 503

    return jsonify(
        {
            "success": result.success,
            "state": result.state.value,
            "error": result.error,
        }
    ), 200


@process.route("/jobs/feedback", methods=["POST"])
def deferred_job_feedback() -> ResponseReturnValue:
    """Publish a user-facing update if a deferred job is still active."""
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    job_key = payload.get("job_key")
    if set(payload) != {"job_key"} or not isinstance(job_key, str) or not job_key:
        return jsonify({"success": False, "error": "Invalid job payload."}), 400
    return jsonify(
        {
            "success": True,
            "updated": DeferredJobs.feedback(job_key),
        }
    )


@process.route("/jobs/reconcile", methods=["POST"])
def deferred_job_reconcile() -> ResponseReturnValue:
    """Recover stranded deferred work from durable dispatch metadata."""
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if payload != {"reconcile": True}:
        return jsonify({"success": False, "error": "Invalid reconcile payload."}), 400
    return jsonify({"success": True, **DeferredJobs.reconcile()}), 200


@process.route("/notification-email", methods=["POST"])
def notification_email_delivery() -> ResponseReturnValue:
    """Deliver one opaque event-driven notification email task."""
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    delivery_key = payload.get("delivery_key")
    if set(payload) != {"delivery_key"} or not isinstance(delivery_key, str) or not delivery_key:
        return jsonify({"success": False, "error": "Invalid email payload."}), 400
    try:
        result = email_delivery.deliver(delivery_key)
    except NotificationEmailError as error:
        return jsonify({"success": False, "error": str(error)}), 503
    except Exception as error:
        exceptions.capture(
            error,
            context={
                "operation": "notification-email-delivery",
                "delivery_key": payload["delivery_key"],
            },
        )
        return jsonify({"success": False, "error": str(error)}), 503
    return jsonify({"success": True, **result}), 200


@process.route("/uncomplete-task", methods=["POST"])
def uncomplete_task() -> ResponseReturnValue:
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    allowed = {"key", "token"} if payload.get("token") else {"key", "next_due_date"}
    task_key = payload.get("key")
    if not isinstance(task_key, str) or not task_key or not set(payload).issubset(allowed):
        return jsonify({"success": False, "error": "Invalid task payload."}), 400

    task = None

    try:
        task = Entities.fetch_one(
            task_key,
            request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
        )
        if not isinstance(task, Entities.TASK):
            return make_response("", 200)
        token = str(payload.get("token") or "")
        active_schedule = task.properties.schedule.active
        if token:
            valid = (
                task.completed
                and task.active
                and active_schedule is not None
                and token == task.scheduled_uncomplete_token
            )
        else:
            next_due = payload.get("next_due_date")
            expected_due = (
                dates.utc_date_string_to_utc_datetime(next_due)
                if isinstance(next_due, str) and next_due
                else None
            )
            valid = bool(
                task.completed
                and task.active
                and active_schedule is not None
                and expected_due is not None
                and task.due_date == expected_due
            )
        if not valid:
            return make_response("", 200)
        next_due_date = task.due_date
        task.uncomplete()
        task.due_date = next_due_date
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


@process.route("/update-cache", methods=["POST"])
def update_cache() -> ResponseReturnValue:
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if set(payload) != {"cache_key", "entity_key", "user_key"} or not all(
        payload.get(key) for key in ("cache_key", "entity_key", "user_key")
    ):
        return jsonify({"success": False, "error": "Invalid cache payload."}), 400

    entity_key = payload.get("entity_key")
    if not isinstance(entity_key, str):
        return jsonify({"success": False, "error": "Invalid cache payload."}), 400
    user = None
    entity = None

    try:
        user_key = payload.get("user_key")
        if user_key is not None and not isinstance(user_key, str):
            raise ValueError("Invalid user key.")
        user = Entities.USER(user_key)
        entity = Entities.fetch_one(
            entity_key,
            request=Fetch.direct(),
        )
        if not isinstance(entity, (Entities.CATEGORY, Entities.PROJECT)):
            raise ValueError("Invalid filter cache target.")
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


@process.route("/ingress", methods=["POST"])
def ingress() -> ResponseReturnValue:
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    if not set(payload).issubset({"key", "timezone", "user_key"}) or not all(
        payload.get(key) for key in ("key", "user_key")
    ):
        return jsonify({"success": False, "error": "Invalid ingress payload."}), 400

    session["timezone"] = payload.get("timezone", "UTC")

    file_key = payload.get("key")
    if not isinstance(file_key, str):
        return jsonify({"success": False, "error": "Invalid ingress payload."}), 400
    file = None
    service = None

    try:
        file = Entities.fetch_one(
            file_key,
            request=Fetch.direct(),
        )
        if not isinstance(file, Entities.INGRESS):
            raise ValueError("Invalid import target.")
        service = IngressService(file)
        outcome = service.run_batch()

        if outcome.state == "stopped":
            return jsonify({"success": True}), 200

        if outcome.state == "completed":
            user_key = payload.get("user_key")
            create_process_notification(
                {"user_key": user_key} if isinstance(user_key, str) else {},
                f"Data import complete for {file.name}",
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
                        "file": file.db,
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


@process.route("/reconcile-restrictions", methods=["POST"])
def reconcile_restrictions() -> ResponseReturnValue:
    from lagniappe.core.tools.cache.restrictions import reconcile_batch, enqueue
    payload = authenticate_task(request)
    if payload is None:
        return make_response("Unauthorized", 401)
    source_key = payload.get("source_key")
    cursor = payload.get("cursor")
    offset = payload.get("offset", 0)
    revision = payload.get("revision")
    owners = payload.get("owner_keys")
    if (not isinstance(source_key, str) or not source_key
            or (cursor is not None and not isinstance(cursor, str))
            or not isinstance(offset, int)
            or (revision is not None and not isinstance(revision, str))
            or (owners is not None and not isinstance(owners, list))
            or not set(payload) <= {"source_key", "cursor", "offset", "revision", "owner_keys"}
            or ("revision" in payload and not isinstance(payload["revision"], str))
            or ("owner_keys" in payload and (
                not isinstance(payload["owner_keys"], list)
                or any(not isinstance(key, str) for key in payload["owner_keys"])
            ))):
        return jsonify({"success": False}), 400
    try:
        remaining = reconcile_batch(source_key, cursor, offset, revision, owners)
        if remaining:
            enqueue(remaining)
    except Exception as error:
        exceptions.capture(error, context={"operation": "reconcile-restrictions"})
        return jsonify({"success": False, "retry": True}), 503
    return jsonify({"success": True})
