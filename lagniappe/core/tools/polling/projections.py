"""Runtime-safe projections for the adaptive browser polling contract."""

import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs


PERSONAL_CHANNELS = frozenset({"starred", "tool-reports"})
CHANNEL_REVISION_PATHS = {
    "home": (
        "/",
        "/categories/index",
        "/projects/index",
        "/pages/index",
        "/tasks/index",
    ),
    "home-notes": ("/",),
    "categories": ("/categories/index",),
    "projects": ("/projects/index",),
    "pages": ("/pages/index",),
    "tasks": ("/tasks/index",),
    "forms": ("/forms/index",),
    "users": ("/users/index",),
    "ingress": ("/ingress/index",),
    "messages": (),
    "starred": (),
    "tool-reports": ("/reports/index",),
}


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_channel_revisions_batch_only_requested_site_fingerprints
# @matrix polling : channel mounted-scope permissions revision
def channel_paths(channel):
    """Return the durable fingerprint paths owned by one polling channel."""
    return CHANNEL_REVISION_PATHS.get(channel, (f"/{channel}/index",))


# @testable false
# @covered-by lagniappe/core/tools/polling/projections.py::channel_revisions
# @reason single-channel hashing is exercised through the batched public projection
def channel_revision(
    channel,
    user,
    *,
    site_fingerprint=None,
    site_fingerprints=None,
    notification_state=None,
):
    """Return an opaque durable revision scoped to the supplied viewer."""
    site_fingerprint = site_fingerprint or database_utility.site_fingerprint
    entity_revision = getattr(user, "fingerprint", None)
    if not entity_revision:
        modified = getattr(user, "modified", None)
        entity_revision = modified.isoformat() if modified else "unknown"
    paths = channel_paths(channel)
    durable_revisions = [
        site_fingerprints.get(path)
        if site_fingerprints is not None
        else site_fingerprint(path)
        for path in paths
    ]
    permissions = getattr(
        user,
        "authorization_fingerprint",
        getattr(user, "permissions_fingerprint", entity_revision),
    )
    source = json.dumps(
        {
            "channel": channel,
            "durable": durable_revisions,
            "personal": (entity_revision if channel in PERSONAL_CHANNELS else None),
            "messages": (
                {
                    "generation": (notification_state or {}).get("generation"),
                    "revision": (notification_state or {}).get("message_revision", 0),
                }
                if channel == "messages"
                else None
            ),
            "permissions": permissions,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


_NOTIFICATION_STATE_UNSET = object()


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_channel_revisions_batch_only_requested_site_fingerprints
# @matrix polling : batching channel mounted-scope
# @pair messaging:polling-revision
def channel_revisions(
    channels,
    user,
    *,
    fingerprint_loader=None,
    notification_state=_NOTIFICATION_STATE_UNSET,
    notification_loader=None,
):
    """Resolve requested channel cursors through one site-fingerprint batch."""
    channels = tuple(dict.fromkeys(channels))
    paths = tuple(
        dict.fromkeys(path for channel in channels for path in channel_paths(channel))
    )
    fingerprint_loader = fingerprint_loader or database_utility.site_fingerprints
    fingerprints = fingerprint_loader(paths) if paths else {}
    if "messages" in channels and notification_state is _NOTIFICATION_STATE_UNSET:
        notification_loader = notification_loader or cache.peek_notification_state
        try:
            notification_state = notification_loader(user)
        except Exception as error:
            notification_state = None
            exceptions.capture(
                error,
                context={"operation": "poll_message_revision"},
            )
    return {
        channel: channel_revision(
            channel,
            user,
            site_fingerprints=fingerprints,
            notification_state=(
                notification_state
                if notification_state is not _NOTIFICATION_STATE_UNSET
                else None
            ),
        )
        for channel in channels
    }


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_operation_statuses_skip_fresh_cached_jobs_and_batch_stale_jobs
# @matrix deferred-jobs : cache-failure-isolation owner redis-projection
# @matrix polling : batching permissions revision
def operation_statuses(
    descriptors,
    user,
    *,
    status_loader=None,
    state_loader=None,
    state_writer=None,
    now=None,
):
    """Load only operations missing a fresh owner-safe Redis revision."""
    status_loader = status_loader or DeferredJobs.statuses
    state_loader = state_loader or cache.peek_operation_states
    state_writer = state_writer or cache.update_operation_projection
    user_key = getattr(user, "urlsafe_key", None)
    owned = []
    for descriptor in descriptors:
        key = database_get.datastore_key(descriptor["key"])
        parent = getattr(key, "parent", None)
        owner_key = database_get.urlsafe_key(parent) if parent is not None else None
        if user_key and owner_key == user_key:
            owned.append(descriptor)

    states = {}
    if owned:
        try:
            states = state_loader([descriptor["key"] for descriptor in owned])
        except Exception as error:
            exceptions.capture(error, context={"operation": "poll_operation_state"})

    unchanged = {
        descriptor["key"]
        for descriptor in owned
        if cache.operation_state_current(
            states.get(descriptor["key"]),
            descriptor["revision"],
            now=now,
        )
    }
    changed = [
        descriptor
        for descriptor in descriptors
        if descriptor["type"] == "operation"
        and descriptor["key"] not in unchanged
    ]
    statuses = {}
    operation_keys = [descriptor["key"] for descriptor in changed]
    for offset in range(0, len(operation_keys), 50):
        statuses.update(
            {
                status["key"]: status
                for status in status_loader(operation_keys[offset : offset + 50], user)
            }
        )
    if statuses:
        try:
            state_writer(*statuses.values())
        except Exception as error:
            exceptions.capture(error, context={"operation": "poll_operation_repair"})
    return statuses, unchanged


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_render_operation_statuses_batches_and_attaches_known_jobs
# @matrix deferred-jobs : server-render status
# @pair polling:batching
def render_operation_statuses(entities, user, *, status_loader=None):
    """Attach current status projections to server-rendered operation owners."""
    status_loader = status_loader or DeferredJobs.statuses
    entities = list(entities or ())
    keys = []
    owners = {}
    for entity in entities:
        operation = dict(getattr(entity, "deferred_job", None) or {})
        key = operation.get("key")
        if not key:
            continue
        keys.append(key)
        owners.setdefault(key, []).append(entity)

    statuses = {}
    for offset in range(0, len(keys), 50):
        statuses.update(
            {
                status["key"]: status
                for status in status_loader(keys[offset : offset + 50], user)
            }
        )
    for key, records in owners.items():
        for record in records:
            record._operation_status = statuses.get(key)
    return statuses


# @testable false
# @covered-by lagniappe/core/tools/polling/projections.py::lock_result
# @reason result envelope construction is asserted through the public lock projection
def _result(descriptor, status, *, revision=None, payload=None):
    result = {
        "id": descriptor["id"],
        "type": descriptor["type"],
        "status": status,
        "poll_after_ms": 15_000,
    }
    if revision is not None:
        result["revision"] = revision
    if payload is not None:
        result["payload"] = payload
    return result


# @testable false
# @covered-by lagniappe/core/tools/polling/projections.py::lock_result
# @reason revision comparison is asserted through the public lock projection
def _revision_result(descriptor, revision, payload=None):
    changed = descriptor["revision"] != revision
    return _result(
        descriptor,
        "changed" if changed else "unchanged",
        revision=revision,
        payload=payload if changed else None,
    )


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_form_lock_revision_is_independent_of_entity_fingerprint
# @pairs deferred-jobs:form-lock polling:revision
def lock_result(descriptor, entity, active_locks, *, user):
    """Project one form lock without reading Flask's process-global actor."""
    if not entity or not entity.allowed(Action.VIEW, user=user):
        return _result(descriptor, "unavailable")
    active = active_locks.get(descriptor["key"])
    if not active:
        return _revision_result(descriptor, "unlocked", {"locked": False})
    lock, job = active
    revision = f"{job.urlsafe_key}:{int(job.status_revision or 0)}"
    return _revision_result(
        descriptor,
        revision,
        {
            "key": descriptor["key"],
            "locked": True,
            "scope": lock.scope,
            "operation": job.urlsafe_key,
            "revision": int(job.status_revision or 0),
        },
    )
