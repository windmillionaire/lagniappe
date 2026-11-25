"""Runtime-safe projections for the adaptive browser polling contract."""

from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from ...entities.entity import Entity
    from ...entities.page import Page
    from ...entities.user import User
    from ...properties.deferred_job_lifecycle import JobStatus
    from ..cache.notification_state import NotificationState
    from ..cache.operations import OperationState
    from ..deferred_jobs.locks import ActiveLock
    from .contract import KeyDescriptor, OperationDescriptor

import hashlib
import json

from lagniappe.core import exceptions
from lagniappe.core.definitions import Action
from lagniappe.core.tools import cache
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from .contract import CHANNEL_REVISION_PATHS, poll_result, revision_result


type StatusLoader = Callable[[list[str], User], list[JobStatus]]


class StatusWriter(Protocol):
    def __call__(self, *statuses: JobStatus) -> object: ...


class _Unspecified(Enum):
    NOTIFICATION_STATE = "notification_state"


PERSONAL_CHANNELS = frozenset({"starred", "tool-reports"})


def filter_revision(entity: Entity, user: User) -> str:
    """Scope a saved Filter's parent/definition revision to its viewer."""
    return f"{entity.fingerprint}:{user.authorization_fingerprint}"


def filter_result_revision(entity: Entity, user: User) -> str:
    """Include every durable authority used by a preview or saved result page."""
    parent = cast("Entity", entity.parent) if entity.entity_kind == "filter" else entity
    revision = filter_revision(entity, user)
    if parent.entity_kind == "project":
        revision += f":{database_utility.site_fingerprint('/tasks/index')}"
    return revision


def page_tasks_revision(page: Page, user: User) -> str:
    """Include saved Task Form definitions without reading the Page's Tasks."""
    return f"{page.fingerprint}:{database_utility.site_fingerprint('/forms/index')}"


def channel_paths(channel: str) -> tuple[str, ...]:
    """Return the durable fingerprint paths owned by one polling channel."""
    return CHANNEL_REVISION_PATHS.get(channel, (f"/{channel}/index",))


def channel_revision(
    channel: str,
    user: User,
    *,
    site_fingerprint: Callable[[str], str | None] | None = None,
    site_fingerprints: Mapping[str, str | None] | None = None,
    notification_state: NotificationState | None = None,
) -> str:
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


_NOTIFICATION_STATE_UNSET = _Unspecified.NOTIFICATION_STATE


def channel_revisions(
    channels: Iterable[str],
    user: User,
    *,
    fingerprint_loader: Callable[[tuple[str, ...]], Mapping[str, str | None]] | None = None,
    notification_state: NotificationState | None | _Unspecified = _NOTIFICATION_STATE_UNSET,
    notification_loader: Callable[[User], NotificationState | None] | None = None,
) -> dict[str, str]:
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
                if not isinstance(notification_state, _Unspecified)
                else None
            ),
        )
        for channel in channels
    }


def operation_statuses(
    descriptors: list[OperationDescriptor],
    user: User,
    *,
    status_loader: StatusLoader | None = None,
    state_loader: Callable[[list[str]], dict[str, OperationState | None]] | None = None,
    state_writer: StatusWriter | None = None,
    now: float | None = None,
) -> tuple[dict[str, JobStatus], set[str]]:
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


def render_operation_statuses(entities: Iterable[Entity] | None, user: User, *, status_loader: StatusLoader | None = None) -> dict[str, JobStatus]:
    """Attach current status projections to server-rendered operation owners."""
    status_loader = status_loader or DeferredJobs.statuses
    entities = list(entities or ())
    keys = []
    owners = {}
    for entity in entities:
        if getattr(entity, "entity_kind", None) == "report" and not entity.available:
            continue
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


def lock_result(descriptor: KeyDescriptor, entity: Entity | None, active_locks: Mapping[str, ActiveLock], *, user: User) -> dict[str, object]:
    """Project one form lock without reading Flask's process-global actor."""
    if not entity or not entity.allowed(Action.VIEW, user=user):
        return poll_result(descriptor, "unavailable")
    active = active_locks.get(descriptor["key"])
    if not active:
        return revision_result(descriptor, "unlocked", {"locked": False})
    lock, job = active
    revision = f"{job.urlsafe_key}:{int(job.status_revision or 0)}"
    return revision_result(
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
