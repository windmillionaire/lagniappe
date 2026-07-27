"""Document collaboration routes: register, update, fetch, and deregister."""

from flask import request
from flask_login import current_user

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache
from lagniappe.web import responses
from lagniappe.web.auth import logged_in

from . import home


# @testable false
# @covered-by lagniappe/web/routes/home/sync.py::register
# @covered-by lagniappe/web/routes/home/sync.py::sync
# @covered-by lagniappe/web/routes/home/sync.py::state
# @reason sync kind predicate is exercised through document sync workflows
def _is_document(sync_id):
    return isinstance(sync_id, str) and sync_id.endswith(":document")


# @testable false
# @covered-by lagniappe/web/routes/home/sync.py::register
# @covered-by lagniappe/web/routes/home/sync.py::sync
# @covered-by lagniappe/web/routes/home/sync.py::state
# @reason cache/register/update state resolution is exercised through public sync endpoints
def _resolve_state(sync_data, entity, register=True):
    """Return ``(state, users)`` for ``sync_data['sync_id']``.

    When ``register`` is true and a token is present, registers the caller as a
    viewer (refreshing TTLs). Tokenless callers read cached state without
    joining presence. Both paths seed the cache from the entity on a miss.
    """
    sync_id = sync_data["sync_id"]
    token = sync_data.get("token")
    if register and token:
        state, users = cache.get_state(sync_id, token, current_user.details)
    else:
        state, users = cache.get_cached_state(sync_id), []

    update_state = False

    if not state:
        state = entity.state(sync_id)
        update_state = True
    if sync_data.get("ydoc"):
        state["ydoc"] = sync_data.get("ydoc")
        update_state = True

    if update_state:
        cache.set_state(sync_id, state)

    return state, users


# @testable false
# @covered-by lagniappe/web/routes/home/sync.py::sync
# @reason persistence branch is part of the sync update endpoint contract
def _persist_state(sync_data, entity):
    """Persist document asset data when an update carries saved HTML."""
    if "html" in sync_data:
        entity.properties.document.save(**sync_data)
        entity.save()


# @testable true
# @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_live_sync_rejects_form_widget_payloads
# @pairs sync:document-only forms:no-live-sync
def _validate_sync_payload(payload):
    if not isinstance(payload, dict):
        return "Invalid sync payload."

    updates = payload.get("updates", [])
    if not isinstance(updates, list):
        return "Sync payload updates must be a list."

    for update in updates:
        if not isinstance(update, dict):
            return "Sync update must be an object."
        if not update.get("key") or not update.get("sync_id"):
            return "Sync update missing key or sync_id."
        if not _is_document(update.get("sync_id")):
            return "Only document widgets may use live sync."

    return None


# @testable false
# @covered-by lagniappe/web/routes/home/sync.py::sync
# @reason broadcast-recipient filtering is part of sync update fanout
def _recipients(token, users):
    """Tokens that should receive a broadcast for an update authored by ``token``."""
    return [u["token"] for u in users if u.get("token") != token]


# @testable false
# @covered-by lagniappe/web/routes/home/sync.py::sync
# @reason tokenless public-page persistence is part of the sync update endpoint contract
def _tokenless_personal_document_save(sync_data, entity):
    user_page = getattr(current_user, "page", None)
    return (
        "html" in sync_data
        and user_page
        and getattr(user_page, "hash", None) == getattr(entity, "hash", None)
    )


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
# @features sync
# @dimensions document collaboration presence
@home.route("/register", methods=["POST"])
@logged_in
def register():
    """Register a client for every widget it has on screen or queued offline.

    Returns the modified widgets (those whose cached fingerprint disagrees
    with the fingerprint the client had). Offline records ride along so the
    client can play their pending changes into the modified widgets before
    posting them on the next /sync.
    """
    payload = request.json
    token = payload["token"]
    user_details = current_user.details

    widgets = [
        widget
        for widget in payload["active"] + payload["offline"]
        if isinstance(widget, dict) and _is_document(widget.get("sync_id"))
    ]
    keys = {w["key"] for w in widgets}
    entities = {
        e.urlsafe_key: e for e in Entities.fetch(*keys, request=Fetch.direct())
    }
    modified = {}

    for widget in [w for w in widgets if w["key"] in entities]:
        sync_id = widget["sync_id"]
        if sync_id in modified:
            continue

        entity = entities[widget["key"]]
        widget["token"] = token
        state, users = _resolve_state(widget, entity)

        updated = widget.get("fingerprint") != state.get("fingerprint")
        if updated:
            widget.update({"users": users, "user": user_details, **state})
            modified[sync_id] = widget

    return responses.json_response({"modified": list(modified.values())})


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_sync_response_contract_is_browser_visible
# @tests tests_e2e/008_users/test_008c_user_settings.py::test_public_user_edits_document_without_ai_or_image_tools
# @features sync
# @dimensions document sync-state response-contract
@home.route("/sync", methods=["POST"])
@logged_in
def sync():
    """Apply each update, refresh the cache, broadcast to co-viewers."""
    payload = request.json

    error = _validate_sync_payload(payload)
    if error:
        return responses.error(error)

    token = payload.get("token")
    updates = payload.get("updates", [])

    keys = {u["key"] for u in updates}
    entities = {
        e.urlsafe_key: e
        for e in Entities.fetch(*keys, request=Fetch.direct())
        if e
    }

    if len(entities) != len(keys):
        return responses.error("Sync update references an unknown entity.")

    for update in updates:
        entity = entities[update["key"]]
        if not token:
            if _tokenless_personal_document_save(update, entity):
                _persist_state(update, entity)
                cache.clear_state(update["sync_id"])
            continue

        update["token"] = token

        state, users = _resolve_state(update, entity)
        update["state"] = state
        _persist_state(update, entity)

        recipients = _recipients(token, users)
        if recipients:
            responses.sync_update(update, recipients)

    return responses.ok()


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
# @features sync
# @dimensions document sync-state presence
@home.route("/state", methods=["POST"])
@logged_in
def state():
    """Return the current state + co-viewers for a single widget."""
    payload = request.json
    entity = Entities.fetch_one(
        payload["key"],
        request=Fetch.direct(),
    )
    if not _is_document(payload.get("sync_id")):
        return responses.error("Only document widgets may use live sync.")

    state, users = _resolve_state(payload, entity, register=bool(payload.get("token")))

    return responses.json_response(
        {
            "users": users,
            "user": current_user.details,
            **state,
        }
    )


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
# @features sync
# @dimensions document deregistration stale-sessions
@home.route("/deregister", methods=["POST"])
@logged_in
def deregister():
    """Drop a client's token from every registration it was part of."""
    payload = request.json or {}
    cache.deregister(payload.get("token"), payload.get("sync_ids", []))
    return responses.ok()
