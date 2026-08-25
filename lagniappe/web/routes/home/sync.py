"""Apply revisioned collaborative-document updates."""

from flask import request
from flask_login import current_user

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.core.tools.mentions import service as mentions
from lagniappe.core.tools.polling.forms import validate_sync_payload
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import internal


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
# @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_edits_document_without_ai_or_image_tools
# @matrix sync : checkpoint delta document offline-replay persistence revision
@internal.route("/sync", methods=["POST"])
@logged_in
def sync():
    """Append Yjs deltas and persist only current-generation checkpoints."""
    payload = request.get_json(silent=True) or {}
    error = validate_sync_payload(payload)
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
            update.get(name) is not None for name in ("update", "ydoc", "html")
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
            mentions.deliver_mentions(
                current_user,
                entity,
                update.get("html") or "",
                update.get("mentions") or [],
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
