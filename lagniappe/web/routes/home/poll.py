"""Versioned adaptive polling for mounted browser state."""

from flask import request
from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.deferred_jobs import deferred_job_lock_descriptors
from lagniappe.core.tools.polling import (
    channel_revisions as _channel_revisions,
    lock_result as _project_lock_result,
    operation_statuses as _operation_statuses,
)
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import internal


POLL_PROTOCOL_VERSION = 1
MAX_POLL_SUBSCRIPTIONS = 64
MAX_POLL_KEY_LENGTH = 512
MAX_POLL_IDENTIFIER_LENGTH = MAX_POLL_KEY_LENGTH + 128
POLL_TYPES = frozenset(
    {"entity", "channel", "form-lock", "document", "operation", "ingress"}
)
CHANNELS = frozenset(
    {
        "categories",
        "projects",
        "pages",
        "tasks",
        "forms",
        "users",
        "ingress",
        "home",
        "home-notes",
        "starred",
        "tool-reports",
    }
)
POLL_AFTER_MS = {
    "entity": 15_000,
    "channel": 15_000,
    "form-lock": 15_000,
    "document": 2_000,
    "operation": 4_000,
    "ingress": 2_500,
}


# @testable true
# @tests tests_e2e/001_site/test_001f_edited_entities.py::test_poll_endpoint_batches_entity_changes
# @tests tests_e2e/001_site/test_001f_edited_entities.py::test_cold_notification_state_seeds_through_one_poll
# @features polling
# @dimensions protocol validation batching identifiers
def _descriptors(payload):
    """Validate the public polling envelope and return normalized descriptors."""
    if not isinstance(payload, dict) or payload.get("version") != POLL_PROTOCOL_VERSION:
        return None
    client_id = payload.get("client_id")
    subscriptions = payload.get("subscriptions")
    if (
        not isinstance(client_id, str)
        or not client_id.strip()
        or len(client_id) > 128
        or not isinstance(subscriptions, list)
        or len(subscriptions) > MAX_POLL_SUBSCRIPTIONS
    ):
        return None

    normalized = []
    ids = set()
    for descriptor in subscriptions:
        if not isinstance(descriptor, dict):
            return None
        identifier = descriptor.get("id")
        subscription_type = descriptor.get("type")
        revision = descriptor.get("revision")
        if (
            not isinstance(identifier, str)
            or not identifier.strip()
            or len(identifier) > MAX_POLL_IDENTIFIER_LENGTH
            or identifier in ids
            or subscription_type not in POLL_TYPES
            or (
                revision is not None
                and (
                    isinstance(revision, bool)
                    or not isinstance(revision, (int, str))
                    or (isinstance(revision, int) and revision < 0)
                    or (isinstance(revision, str) and len(revision) > 512)
                )
            )
        ):
            return None
        ids.add(identifier)
        item = {
            "id": identifier,
            "type": subscription_type,
            "revision": descriptor.get("revision"),
        }
        if subscription_type == "channel":
            if descriptor.get("channel") not in CHANNELS:
                return None
            item["channel"] = descriptor["channel"]
        elif subscription_type == "document":
            generation = descriptor.get("generation")
            presence_digest = descriptor.get("presence_digest")
            if (
                not isinstance(descriptor.get("key"), str)
                or not descriptor["key"]
                or len(descriptor["key"]) > MAX_POLL_KEY_LENGTH
                or not isinstance(descriptor.get("sync_id"), str)
                or not descriptor["sync_id"].endswith(":document")
                or len(descriptor["sync_id"]) > MAX_POLL_KEY_LENGTH
                or (
                    revision is not None
                    and (
                        not isinstance(revision, int)
                        or isinstance(revision, bool)
                        or revision < 0
                    )
                )
                or (
                    generation is not None
                    and (not isinstance(generation, str) or len(generation) > 128)
                )
                or (
                    presence_digest is not None
                    and (
                        not isinstance(presence_digest, str)
                        or len(presence_digest) > 128
                    )
                )
            ):
                return None
            item.update(
                {
                    "key": descriptor["key"],
                    "sync_id": descriptor["sync_id"],
                    "generation": descriptor.get("generation"),
                    "presence_digest": descriptor.get("presence_digest"),
                }
            )
        else:
            if (
                not isinstance(descriptor.get("key"), str)
                or not descriptor["key"]
                or len(descriptor["key"]) > MAX_POLL_KEY_LENGTH
            ):
                return None
            item["key"] = descriptor["key"]
        normalized.append(item)

    closed = payload.get("closed_documents") or []
    if (
        not isinstance(closed, list)
        or len(closed) > MAX_POLL_SUBSCRIPTIONS
        or any(
            not isinstance(sync_id, str)
            or not sync_id.endswith(":document")
            or len(sync_id) > MAX_POLL_KEY_LENGTH
            for sync_id in closed
        )
    ):
        return None
    notification_state = payload.get("notification_state")
    if notification_state is not None:
        if not isinstance(notification_state, dict):
            return None
        generation = notification_state.get("generation")
        revision = notification_state.get("revision")
        seed = notification_state.get("seed", False)
        if (
            (
                generation is not None
                and (not isinstance(generation, str) or len(generation) > 128)
            )
            or (
                revision is not None
                and (
                    isinstance(revision, bool)
                    or not isinstance(revision, int)
                    or revision < 0
                )
            )
            or not isinstance(seed, bool)
        ):
            return None
        notification_state = {
            "generation": generation,
            "revision": revision,
            "seed": seed,
        }
    return client_id, normalized, list(dict.fromkeys(closed)), notification_state


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
        "poll_after_ms": poll_after_ms or POLL_AFTER_MS[descriptor["type"]],
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
    changed = str(descriptor.get("revision") or "") != str(revision)
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
    document_id = (getattr(entity, "sync_ids", {}) or {}).get("document", {}).get("id")
    if (
        not entity
        or not entity.allowed(Action.VIEW, user=current_user)
        or document_id != descriptor["sync_id"]
    ):
        return _result(descriptor, "unavailable")
    payload = cache.poll_document(
        descriptor["sync_id"],
        seed=entity.state(descriptor["sync_id"]),
        client_id=client_id,
        user=current_user.details,
        generation=descriptor.get("generation"),
        revision=descriptor.get("revision"),
        presence_digest=descriptor.get("presence_digest"),
    )
    changed = bool(
        descriptor.get("generation") != payload["generation"]
        or int(descriptor.get("revision") or 0) != int(payload["revision"])
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
# @dimensions protocol entity channel operation document presence permissions authorization fingerprint unavailable owner batching progress revision timing lifecycle
# @pairs notifications:cold-seed notifications:ping notifications:redis-projection
# @pairs polling:personal-state polling:piggyback web-headers:notification-state
# @pairs polling:protocol polling:operation polling:owner polling:permissions
# @pairs polling:batching polling:progress polling:timing polling:revision
# @pairs polling:entity polling:channel polling:fingerprint polling:authorization
# @pair polling:validation
# @pair polling:unavailable
@internal.route("/poll", methods=["POST"])
@logged_in
def poll():
    """Resolve every due browser subscription through one typed contract."""
    parsed = _descriptors(request.get_json(silent=True) or {})
    if parsed is None:
        return responses.error("Invalid polling request.")
    client_id, descriptors, closed_documents, notification_request = parsed
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

    channels = [descriptor["channel"] for descriptor in grouped["channel"]]
    channel_revisions = _channel_revisions(channels, current_user)

    if notification_polled:
        try:
            if prefetched_operation_states is None:
                notification_state = cache.peek_notification_state(current_user)
            if notification_state is None and notification_request.get("seed"):
                notification_state = cache.seed_notification_state(current_user)
            responses.publish_notification_state(notification_state)
        except Exception as error:
            exceptions.capture(
                error,
                context={"operation": "poll_notification_state"},
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
                        revision=descriptor.get("revision"),
                    )
                else:
                    status = operation_statuses.get(descriptor["key"])
                    result = (
                        _revision_result(
                            descriptor,
                            int(status["revision"]),
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
        {"version": POLL_PROTOCOL_VERSION, "results": results}
    )
