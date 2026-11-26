"""Versioned adaptive polling for mounted browser state."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue
    from lagniappe.core.tools.cache.notification_state import NotificationState

from flask import g, request

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.deferred_jobs.locks import deferred_job_lock_descriptors
from lagniappe.core.tools.polling.contract import (
    PollContractError,
    PollRequest,
    parse_poll_request,
    poll_result,
    revision_result,
)
from lagniappe.core.tools.polling.projections import (
    channel_revisions as _channel_revisions,
    channel_paths,
    filter_revision,
    lock_result as _project_lock_result,
    operation_statuses as _operation_statuses,
)
from lagniappe.web import responses
from lagniappe.web.auth import authenticated_user, logged_in

from . import internal


class _NotificationRevisionOptions(TypedDict, total=False):
    notification_state: NotificationState | None


def _poll_context():
    """Share only validated, bounded polling roots with the fresh auth lookup."""
    try:
        parsed = parse_poll_request(request.get_json(silent=True))
    except PollContractError:
        # Authentication still precedes reporting a malformed polling payload.
        return {}
    g.poll_request = parsed
    descriptors = parsed.subscriptions
    paths = [
        path for descriptor in descriptors if descriptor["type"] == "channel"
        for path in channel_paths(descriptor["channel"])
    ]
    return {
        "context_keys": tuple(set(database_utility.site_fingerprint_keys(paths).values())),
        "context_entity_keys": tuple(dict.fromkeys(
            descriptor["key"] for descriptor in descriptors
            if descriptor["type"] != "channel" and descriptor["type"] != "operation"
        )),
    }


def _entity_result(descriptor, entity, *, ingress=False):
    if not entity or not entity.allowed(Action.VIEW, user=authenticated_user()):
        return poll_result(descriptor, "unavailable")
    revision = (
        filter_revision(entity, authenticated_user())
        if isinstance(entity, Entities.FILTER) else entity.fingerprint
    )
    payload = (
        {"refresh": True}
        if ingress
        else {
            "fingerprint": revision,
            "modified": entity.modified.isoformat() if entity.modified else None,
        }
    )
    return revision_result(descriptor, revision, payload)


def _document_result(descriptor, entity, client_id):
    if not entity or not entity.allowed(Action.VIEW, user=authenticated_user()):
        return poll_result(descriptor, "unavailable")
    document = entity.sync_ids.get("document")
    document_id = document.get("id") if isinstance(document, dict) else None
    if document_id != descriptor["sync_id"]:
        return poll_result(descriptor, "unavailable")
    payload = cache.poll_document(
        descriptor["sync_id"],
        seed=lambda: entity.state(descriptor["sync_id"]),
        client_id=client_id,
        user=authenticated_user().details,
        generation=descriptor["generation"],
        revision=descriptor["revision"],
        presence_digest=descriptor["presence_digest"],
    )
    changed = bool(
        descriptor["generation"] != payload["generation"]
        or descriptor["revision"] != payload["revision"]
        or "users" in payload
    )
    return poll_result(
        descriptor,
        "changed" if changed else "unchanged",
        revision=payload["revision"],
        payload=payload if changed else None,
    )


@internal.route("/poll", methods=["POST"])
@logged_in(context=_poll_context)
def poll() -> ResponseReturnValue:
    """Resolve every due browser subscription through one typed contract."""
    try:
        parsed = g.get("poll_request")
        if not isinstance(parsed, PollRequest):
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

    entity_keys = [
        descriptor["key"] for descriptor in descriptors
        if descriptor["type"] != "channel" and descriptor["type"] != "operation"
    ]
    operations = [descriptor for descriptor in descriptors if descriptor["type"] == "operation"]
    prefetched = g.get("request_context_entities")
    entities = (
        {key: prefetched[key] for key in entity_keys if key in prefetched}
        if prefetched is not None else {
            entity.urlsafe_key: entity
            for entity in Entities.fetch(*dict.fromkeys(entity_keys), request=Fetch.direct())
        }
    )
    Entities.fetch(
        *(entity for entity in entities.values()
          if isinstance(entity, (Entities.TASK, Entities.FILE, Entities.MODEL_TASK))),
        *(entity.task for entity in entities.values()
          if isinstance(entity, Entities.TASK_HISTORY)),
        request=Fetch.nested(because=FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION),
    )
    lock_entities = [
        entities.get(descriptor["key"]) for descriptor in descriptors if descriptor["type"] == "form-lock"
    ]
    lock_entities = [
        entity
        for entity in lock_entities
        if entity
        and entity.allowed(Action.EDIT, user=authenticated_user())
        and isinstance(entity, (Entities.PAGE, Entities.TASK))
    ]
    active_locks = deferred_job_lock_descriptors(lock_entities) if lock_entities else {}

    notification_polled = notification_request is not None
    notification_state = None
    prefetched_operation_states = None
    if operations and notification_polled:
        try:
            notification_state, prefetched_operation_states = cache.peek_poll_states(
                authenticated_user(),
                [descriptor["key"] for descriptor in operations],
            )
        except Exception as error:
            prefetched_operation_states = {}
            exceptions.capture(error, context={"operation": "poll_redis_state"})

    operation_statuses, unchanged_operations = (
        _operation_statuses(
            operations,
            authenticated_user(),
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
        if operations
        else ({}, set())
    )

    if notification_polled:
        try:
            if prefetched_operation_states is None:
                notification_state = cache.peek_notification_state(authenticated_user())
            if notification_state is None and notification_request and notification_request["seed"]:
                notification_state = cache.seed_notification_state(authenticated_user())
            responses.publish_notification_state(notification_state)
        except Exception as error:
            exceptions.capture(
                error,
                context={"operation": "poll_notification_state"},
            )

    channels = [descriptor["channel"] for descriptor in descriptors if descriptor["type"] == "channel"]
    revision_options: _NotificationRevisionOptions = {}
    if notification_polled:
        revision_options["notification_state"] = notification_state
    channel_revisions = _channel_revisions(
        channels,
        authenticated_user(),
        fingerprint_loader=lambda paths: database_utility.site_fingerprints(
            paths, records=g.get("request_context_records"),
        ),
        **revision_options,
    )

    results = []
    for descriptor in descriptors:
        try:
            if descriptor["type"] == "entity":
                result = _entity_result(
                    descriptor,
                    entities.get(descriptor["key"]),
                )
            elif descriptor["type"] == "ingress":
                result = _entity_result(
                    descriptor,
                    entities.get(descriptor["key"]),
                    ingress=True,
                )
            elif descriptor["type"] == "form-lock":
                result = _project_lock_result(
                    descriptor,
                    entities.get(descriptor["key"]),
                    active_locks,
                    user=authenticated_user(),
                )
            elif descriptor["type"] == "channel":
                revision = channel_revisions[descriptor["channel"]]
                result = revision_result(
                    descriptor,
                    revision,
                    {"refresh": True},
                )
            elif descriptor["type"] == "operation":
                if descriptor["key"] in unchanged_operations:
                    result = poll_result(
                        descriptor,
                        "unchanged",
                        revision=descriptor["revision"],
                    )
                else:
                    status = operation_statuses.get(descriptor["key"])
                    result = (
                        revision_result(
                            descriptor,
                            status["revision"],
                            status,
                        )
                        if status
                        else poll_result(descriptor, "unavailable")
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
            result = poll_result(descriptor, "error", poll_after_ms=15_000)
        results.append(result)

    return responses.json_response({"version": parsed.version, "results": results})
