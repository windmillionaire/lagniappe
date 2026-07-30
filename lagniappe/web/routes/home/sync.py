"""Apply revisioned collaborative-document updates."""

from flask import request
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import home


def _is_document(sync_id):
    return isinstance(sync_id, str) and sync_id.endswith(":document")


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_sync_response_contract_is_browser_visible
# @features sync
# @dimensions validation document-only client-identity
def _validate_sync_payload(payload):
    if not isinstance(payload, dict):
        return "Invalid sync payload."
    if (
        not isinstance(payload.get("client_id"), str)
        or not payload["client_id"]
        or len(payload["client_id"]) > 128
    ):
        return "Sync payload missing client_id."
    updates = payload.get("updates")
    if not isinstance(updates, list) or len(updates) > 64:
        return "Sync payload updates must be a bounded list."
    for update in updates:
        if not isinstance(update, dict):
            return "Sync update must be an object."
        if (
            not isinstance(update.get("key"), str)
            or not update["key"]
            or len(update["key"]) > 512
            or not _is_document(update.get("sync_id"))
            or len(update["sync_id"]) > 512
        ):
            return "Only identified document widgets may use live sync."
        revision = update.get("revision")
        if (
            revision is not None
            and (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 0
            )
        ):
            return "Document revision must be a non-negative integer."
        generation = update.get("generation")
        if generation is not None and (
            not isinstance(generation, str) or len(generation) > 128
        ):
            return "Document generation is invalid."
        if not isinstance(update.get("save"), bool):
            return "Document save mode is invalid."
        touch_parent = update.get("touch_parent", False)
        if not isinstance(touch_parent, bool) or (
            touch_parent and not update["save"]
        ):
            return "Document parent touch is invalid."
        for name in ("update", "ydoc", "html"):
            if update.get(name) is not None and not isinstance(update[name], str):
                return f"Document {name} must be encoded text."
    return None


# @testable false
# @covered-by lagniappe/web/routes/home/sync.py::sync
# @reason durable document fallback normalization is exercised through sync persistence
def _document_seed(entity):
    document = entity.properties.document
    seed = {
        "ydoc": document.ydoc,
        "fingerprint": document.fingerprint,
    }
    if not seed["ydoc"] and document.html:
        seed["markup"] = document.html
    return seed


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_sync_response_contract_is_browser_visible
# @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_edits_document_without_ai_or_image_tools
# @features sync
# @dimensions document revision delta checkpoint persistence offline-replay
@home.route("/sync", methods=["POST"])
@logged_in
def sync():
    """Append Yjs deltas and persist only current-generation checkpoints."""
    payload = request.get_json(silent=True) or {}
    error = _validate_sync_payload(payload)
    if error:
        return responses.error(error)

    updates = payload["updates"]
    keys = list(dict.fromkeys(update["key"] for update in updates))
    entities = {
        entity.urlsafe_key: entity
        for entity in Entities.fetch(*keys, request=Fetch.direct())
        if entity and entity.allowed(Action.EDIT, user=current_user)
    }
    if len(entities) != len(keys):
        return responses.error("Sync update references an unavailable entity.")
    if any(
        (entities[update["key"]].sync_ids.get("document") or {}).get("id")
        != update["sync_id"]
        for update in updates
    ):
        return responses.error("Sync update does not match its document entity.")

    acknowledgements = []
    for update in updates:
        entity = entities[update["key"]]
        seed = _document_seed(entity)
        has_document_payload = any(
            update.get(name) is not None
            for name in ("update", "ydoc", "html")
        )
        if has_document_payload:
            acknowledgement = cache.apply_document_update(
                update["sync_id"],
                seed=seed,
                generation=update.get("generation"),
                revision=update.get("revision"),
                update=update.get("update"),
                ydoc=update.get("ydoc"),
                author=current_user.details,
            )
        else:
            acknowledgement = {
                "generation": update.get("generation"),
                "revision": int(update.get("revision") or 0),
                "fingerprint": seed["fingerprint"],
                "checkpoint_accepted": False,
            }

        checkpoint_persisted = (
            acknowledgement["checkpoint_accepted"] and "html" in update
        )
        entity_touched = False
        if checkpoint_persisted:
            entity.properties.document.save(
                html=update.get("html"),
                ydoc=update.get("ydoc"),
            )
            Entities.save_document_checkpoint(
                entity,
                advance_parent=update.get("touch_parent", False),
            )
            entity_touched = update.get("touch_parent", False)
            cache.update_document_asset(
                update["sync_id"],
                seed=_document_seed(entity),
            )
        elif update.get("touch_parent") and not has_document_payload:
            Entities.advance_document_parent(entity)
            entity_touched = True
        acknowledgements.append(
            {
                "sync_id": update["sync_id"],
                **acknowledgement,
                "checkpoint_persisted": checkpoint_persisted,
                "entity_touched": entity_touched,
            }
        )

    return responses.json_response({"updates": acknowledgements})
