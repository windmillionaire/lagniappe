"""Lightweight committed-entity fingerprint checks for mounted form notices."""

from flask import request
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs import deferred_job_lock_descriptors
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import home


MAX_EDITED_ENTITIES = 32


# @testable true
# @tests tests_e2e/001_site/test_001f_edited_entities.py::test_edited_endpoint_batches_fingerprint_checks
# @features edited-entity-notice
# @dimensions descriptor-validation batch-limit duplicate-keys
def _descriptors(payload):
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, list) or len(entities) > MAX_EDITED_ENTITIES:
        return None

    descriptors = []
    keys = set()
    for descriptor in entities:
        if not isinstance(descriptor, dict):
            return None
        key = descriptor.get("key")
        fingerprint = descriptor.get("fingerprint")
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(fingerprint, str)
            or not fingerprint
            or key in keys
        ):
            return None
        keys.add(key)
        descriptors.append({"key": key, "fingerprint": fingerprint})
    return descriptors


# @testable true
# @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_edited_operations_are_independent_of_fingerprint_drift
# @pairs deferred-jobs:form-lock edited-entity-notice:active-operation
def _active_operations(entities, user):
    """Project active target locks for editable mounted entities."""
    lock_targets = [
        entity
        for entity in entities
        if entity.allowed(Action.EDIT, user=user)
        and isinstance(entity, (Entities.PAGE, Entities.TASK))
    ]
    active = deferred_job_lock_descriptors(lock_targets)
    return [
        {
            "key": key,
            "locked": True,
            "scope": lock.scope,
            "operation": job.urlsafe_key,
            "revision": int(job.status_revision or 0),
        }
        for key, (lock, job) in active.items()
    ]


# @testable true
# @tests tests_e2e/001_site/test_001f_edited_entities.py::test_edited_endpoint_batches_fingerprint_checks
# @features edited-entity-notice permissions
# @dimensions batch fingerprint unavailable authorization
@home.route("/edited", methods=["POST"])
@logged_in
def edited():
    """Return committed fingerprint drift and active form operations."""
    descriptors = _descriptors(request.get_json(silent=True) or {})
    if descriptors is None:
        return responses.error("Invalid edited entity descriptors.")

    loaded = {
        entity.urlsafe_key: entity
        for entity in Entities.fetch(
            *(descriptor["key"] for descriptor in descriptors),
            request=Fetch.direct(),
        )
    }

    changed = []
    for descriptor in descriptors:
        key = descriptor["key"]
        entity = loaded.get(key)
        if not entity or not entity.allowed(Action.VIEW, user=current_user):
            changed.append({"key": key, "unavailable": True})
            continue
        if descriptor["fingerprint"] != entity.fingerprint:
            changed.append(
                {
                    "key": key,
                    "fingerprint": entity.fingerprint,
                    "modified": entity.modified.isoformat() if entity.modified else None,
                }
            )

    operations = _active_operations(loaded.values(), current_user)

    return responses.json_response({"edited": changed, "operations": operations})
