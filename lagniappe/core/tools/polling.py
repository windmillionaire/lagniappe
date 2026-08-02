"""Runtime-safe projections for the adaptive browser polling contract."""

import hashlib
import json

from lagniappe.core.definitions import Action
from lagniappe.core.tools import database
from lagniappe.core.tools.deferred_jobs import DeferredJobs


PERSONAL_CHANNELS = frozenset({"notifications", "starred", "tool-reports"})
CHANNEL_REVISION_PATHS = {
    "home": (
        "/",
        "/categories/index",
        "/projects/index",
        "/pages/index",
        "/tasks/index",
    ),
    "tool-reports": ("/reports/index",),
}


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_notification_channel_revision_uses_loaded_user_only
# @pairs polling:channel polling:revision polling:permissions
# @pairs notifications:personal-activity notifications:revision notifications:datastore-read-isolation
def channel_revision(channel, user, *, site_fingerprint=None):
    """Return an opaque durable revision scoped to the supplied viewer."""
    site_fingerprint = site_fingerprint or database.site_fingerprint
    entity_revision = getattr(user, "fingerprint", None)
    if not entity_revision:
        modified = getattr(user, "modified", None)
        entity_revision = modified.isoformat() if modified else "unknown"
    paths = (
        ()
        if channel == "notifications"
        else CHANNEL_REVISION_PATHS.get(
            channel, ("/" if channel == "home" else f"/{channel}/index",)
        )
    )
    durable_revisions = [site_fingerprint(path) for path in paths]
    permissions = getattr(
        user,
        "authorization_fingerprint",
        getattr(user, "permissions_fingerprint", entity_revision),
    )
    source = json.dumps(
        {
            "channel": channel,
            "durable": durable_revisions,
            "personal": (
                int(getattr(user, "notification_revision", 0) or 0)
                if channel == "notifications"
                else entity_revision
                if channel in PERSONAL_CHANNELS
                else None
            ),
            "permissions": permissions,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_operation_statuses_skip_current_jobs_and_batch_stale_jobs
# @pairs polling:revision polling:batching deferred-jobs:datastore-read-isolation
def operation_statuses(descriptors, user, *, status_loader=None):
    """Load only operations invalidated by the viewer's durable cursor."""
    status_loader = status_loader or DeferredJobs.statuses
    operation_revision = int(getattr(user, "operation_revision", 0) or 0)
    changed = [
        descriptor
        for descriptor in descriptors
        if descriptor["type"] == "operation"
        and descriptor.get("operation_revision") != operation_revision
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
    return operation_revision, statuses


# @testable false
# @covered-by lagniappe/core/tools/polling.py::lock_result
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
# @covered-by lagniappe/core/tools/polling.py::lock_result
# @reason revision comparison is asserted through the public lock projection
def _revision_result(descriptor, revision, payload=None):
    changed = str(descriptor.get("revision") or "") != str(revision)
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
