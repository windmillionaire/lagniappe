"""Versioned adaptive polling for mounted browser state."""

from flask import request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.deferred_jobs import deferred_job_lock_descriptors
from lagniappe.core.tools.polling_contract import (
    POLL_TYPES,
    PollContractError,
    parse_poll_request,
)
from lagniappe.core.tools.polling import (
    channel_revisions as _channel_revisions,
    lock_result as _project_lock_result,
    operation_statuses as _operation_statuses,
)
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import internal


POLL_AFTER_MS = {
    "entity": 15_000,
    "channel": 15_000,
    "form-lock": 15_000,
    "document": 2_000,
    "operation": 4_000,
    "ingress": 2_500,
}


# @testable false
# @covered-by lagniappe/web/routes/home/poll.py::poll
# @reason common result envelope is exercised through polling route coverage
def _result(
    descriptor,
    status,
    *,
    revision=None,
    payload=None,
    poll_after_ms=None,
):
    result = {
        "id": descriptor["id"],
        "type": descriptor["type"],
        "status": status,
        "poll_after_ms": (
            POLL_AFTER_MS[descriptor["type"]]
            if poll_after_ms is None
            else poll_after_ms
        ),
    }
    if revision is not None:
        result["revision"] = revision
    if payload is not None:
        result["payload"] = payload
    return result


# @testable false
# @covered-by lagniappe/web/routes/home/poll.py::poll
# @reason per-type changed/unchanged projection is exercised through route coverage
def _revision_result(descriptor, revision, payload=None):
    changed = descriptor["revision"] != revision
    return _result(
        descriptor,
        "changed" if changed else "unchanged",
        revision=revision,
        payload=payload if changed else None,
    )


# @testable false
# @covered-by lagniappe/web/routes/home/poll.py::poll
# @reason entity permission projection is exercised through route coverage
def _entity_result(descriptor, entity, *, ingress=False):
    if not entity or not entity.allowed(Action.VIEW, user=current_user):
        return _result(descriptor, "unavailable")
    payload = (
        {"refresh": True}
        if ingress
        else {
            "fingerprint": entity.fingerprint,
            "modified": entity.modified.isoformat() if entity.modified else None,
        }
    )
    return _revision_result(descriptor, entity.fingerprint, payload)


# @testable false
# @covered-by lagniappe/web/routes/home/poll.py::poll
# @reason document permission and Redis projection are exercised through route coverage
def _document_result(descriptor, entity, client_id):
    if not entity or not entity.allowed(Action.VIEW, user=current_user):
        return _result(descriptor, "unavailable")
    document = entity.sync_ids.get("document")
    document_id = document.get("id") if isinstance(document, dict) else None
    if document_id != descriptor["sync_id"]:
        return _result(descriptor, "unavailable")
    payload = cache.poll_document(
        descriptor["sync_id"],
        seed=entity.state(descriptor["sync_id"]),
        client_id=client_id,
        user=current_user.details,
        generation=descriptor["generation"],
        revision=descriptor["revision"],
        presence_digest=descriptor["presence_digest"],
    )
    changed = bool(
        descriptor["generation"] != payload["generation"]
        or descriptor["revision"] != payload["revision"]
        or "users" in payload
    )
    return _result(
        descriptor,
        "changed" if changed else "unchanged",
        revision=payload["revision"],
        payload=payload if changed else None,
    )


# @testable true
# @tests tests_e2e/001_site/test_001f_edited_entities.py::test_poll_endpoint_batches_entity_changes
# @tests tests_e2e/001_site/test_001f_edited_entities.py::test_cold_notification_state_seeds_through_one_poll
# @tests tests_e2e/002_home/test_002o_deferred_jobs.py::test_poll_operation_is_owner_safe
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
# @features polling
# @dimensions protocol entity channel operation document presence permissions authorization fingerprint identifiers unavailable owner batching progress revision timing lifecycle
# @pairs notifications:cold-seed notifications:ping notifications:redis-projection
# @pairs polling:personal-state polling:piggyback web-headers:notification-state
# @pairs polling:protocol polling:operation polling:owner polling:permissions
# @pairs polling:batching polling:progress polling:timing polling:revision
# @pairs polling:entity polling:channel polling:fingerprint polling:authorization
# @pair polling:validation
# @pair polling:unavailable
# @pair polling:identifiers
@internal.route("/poll", methods=["POST"])
@logged_in
def poll():
    """Resolve every due browser subscription through one typed contract."""
    try:
        parsed = parse_poll_request(request.get_json(silent=True))
    except PollContractError as error:
        return responses.json_response(
            {
                "error": "Invalid polling request.",
                "code": "invalid_poll_contract",
                "path": error.path,
                "reason": error.reason,
            },
            status=422,
        )
    client_id = parsed.client_id
    descriptors = parsed.subscriptions
    closed_documents = parsed.closed_documents
    notification_request = parsed.notification_state
    if closed_documents:
        cache.close_presence(client_id, closed_documents)

    grouped = {
        subscription_type: [
            descriptor
            for descriptor in descriptors
            if descriptor["type"] == subscription_type
        ]
        for subscription_type in POLL_TYPES
    }

    entity_keys = [
        descriptor["key"]
        for subscription_type in ("entity", "form-lock", "document", "ingress")
        for descriptor in grouped[subscription_type]
    ]
    entities = {
        entity.urlsafe_key: entity
        for entity in Entities.fetch(
            *dict.fromkeys(entity_keys), request=Fetch.direct()
        )
    }
    lock_entities = [
        entities.get(descriptor["key"]) for descriptor in grouped["form-lock"]
    ]
    lock_entities = [
        entity
        for entity in lock_entities
        if entity
        and entity.allowed(Action.EDIT, user=current_user)
        and isinstance(entity, (Entities.PAGE, Entities.TASK))
    ]
    active_locks = deferred_job_lock_descriptors(lock_entities) if lock_entities else {}

    notification_polled = notification_request is not None
    notification_state = None
    prefetched_operation_states = None
    if grouped["operation"] and notification_polled:
        try:
            notification_state, prefetched_operation_states = cache.peek_poll_states(
                current_user,
                [descriptor["key"] for descriptor in grouped["operation"]],
            )
        except Exception as error:
            prefetched_operation_states = {}
            exceptions.capture(error, context={"operation": "poll_redis_state"})

    operation_statuses, unchanged_operations = (
        _operation_statuses(
            grouped["operation"],
            current_user,
            state_loader=(
                (
                    lambda keys: {
                        key: prefetched_operation_states.get(key) for key in keys
                    }
                )
                if prefetched_operation_states is not None
                else cache.peek_operation_states
            ),
        )
        if grouped["operation"]
        else ({}, set())
    )

    if notification_polled:
        try:
            if prefetched_operation_states is None:
                notification_state = cache.peek_notification_state(current_user)
            if notification_state is None and notification_request["seed"]:
                notification_state = cache.seed_notification_state(current_user)
            responses.publish_notification_state(notification_state)
        except Exception as error:
            exceptions.capture(
                error,
                context={"operation": "poll_notification_state"},
            )

    channels = [descriptor["channel"] for descriptor in grouped["channel"]]
    channel_revisions = _channel_revisions(
        channels,
        current_user,
        **(
            {"notification_state": notification_state}
            if notification_polled
            else {}
        ),
    )

    results = []
    for descriptor in descriptors:
        try:
            subscription_type = descriptor["type"]
            if subscription_type == "entity":
                result = _entity_result(
                    descriptor,
                    entities.get(descriptor["key"]),
                )
            elif subscription_type == "ingress":
                result = _entity_result(
                    descriptor,
                    entities.get(descriptor["key"]),
                    ingress=True,
                )
            elif subscription_type == "form-lock":
                result = _project_lock_result(
                    descriptor,
                    entities.get(descriptor["key"]),
                    active_locks,
                    user=current_user,
                )
            elif subscription_type == "channel":
                revision = channel_revisions[descriptor["channel"]]
                result = _revision_result(
                    descriptor,
                    revision,
                    {"refresh": True},
                )
            elif subscription_type == "operation":
                if descriptor["key"] in unchanged_operations:
                    result = _result(
                        descriptor,
                        "unchanged",
                        revision=descriptor["revision"],
                    )
                else:
                    status = operation_statuses.get(descriptor["key"])
                    result = (
                        _revision_result(
                            descriptor,
                            status["revision"],
                            status,
                        )
                        if status
                        else _result(descriptor, "unavailable")
                    )
            else:
                result = _document_result(
                    descriptor,
                    entities.get(descriptor["key"]),
                    client_id,
                )
        except Exception as error:
            exceptions.capture(
                error,
                context={
                    "operation": "poll_subscription",
                    "subscription_type": descriptor["type"],
                },
            )
            result = _result(descriptor, "error", poll_after_ms=15_000)
        results.append(result)

    return responses.json_response(
        {"version": parsed.version, "results": results}
    )
