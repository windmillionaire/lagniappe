"""Redis-backed sync state.

The sync system pivots on three concepts:

* a **sync_id** ("entity_hash", "entity_hash:widget", or
  "entity_hash:related_hash:widget") identifies a single syncable widget.
  ``WIDGET`` registration sets hold the tokens that want push updates for
  that widget;
* an **entity_hash** identifies the underlying entity. ``ENTITY`` viewer sets
  hold the tokens looking at the entity in any of its widgets, used to
  broadcast delete events;
* a **token** is the FCM messaging token for a particular tab/device. The
  ``USERS`` hash maps tokens to JSON-encoded user-detail dicts (with the
  token embedded) so we can look up who to talk to from a registration set.

All keys expire after :data:`FIVE_MINUTES`; long-lived viewers refresh the
TTL on every poll via :func:`get_state`.
"""

import json

from .core import cache
from .keys import Sync

FIVE_MINUTES = 300


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_sync_id_hashes_parse_widget_ids
# @features sync
# @dimensions composite-sync-id registration
def _entity_hashes(sync_id):
    """Return every entity-ish hash encoded before the widget suffix."""
    parts = [p for p in (sync_id or "").split(":") if p]
    if not parts:
        return []
    if len(parts) > 1:
        return parts[:-1]
    return parts


# @testable false
# @covered-by lagniappe/core/tools/cache/sync.py::get_state
# @reason user payload shape is owned by sync registration state
def _encode_user(token, user):
    return json.dumps({**user, "token": token}, sort_keys=True)


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_get_cached_state_does_not_register_viewer
# @features sync
# @dimensions sync-state state-only
def get_cached_state(sync_id):
    """Return cached widget state without registering a viewer token."""
    with cache.pipeline() as pipe:
        pipe.hget(Sync.STATE.value, sync_id)
        pipe.hexpire(Sync.STATE.value, FIVE_MINUTES, sync_id)
        result = pipe.execute()

    raw_state = result[0]
    return json.loads(raw_state) if raw_state else {}


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
# @tests tests_unit/test_010_sync_cache.py::test_get_state_registers_every_hash_in_composite_sync_id
# @features sync
# @dimensions document sync-state presence composite-sync-id registration
def get_state(sync_id, token, user):
    """Register ``token`` for ``sync_id`` and return its cached state plus co-viewers.

    Refreshes every TTL involved in this registration so abandoned tokens age
    out naturally. The returned ``users`` list contains user-detail dicts with
    the recipient ``token`` embedded so callers can route broadcasts without a
    second round-trip.
    """
    widget_key = Sync.WIDGET.key(sync_id)
    entity_keys = [Sync.ENTITY.key(h) for h in _entity_hashes(sync_id)]
    user_payload = _encode_user(token, user)

    with cache.pipeline() as pipe:
        pipe.sadd(widget_key, token)
        pipe.expire(widget_key, FIVE_MINUTES)
        for entity_key in entity_keys:
            pipe.sadd(entity_key, token)
            pipe.expire(entity_key, FIVE_MINUTES)
        pipe.hset(Sync.USERS.value, token, user_payload)
        pipe.hexpire(Sync.USERS.value, FIVE_MINUTES, token)
        pipe.hget(Sync.STATE.value, sync_id)
        pipe.hexpire(Sync.STATE.value, FIVE_MINUTES, sync_id)
        pipe.smembers(widget_key)
        results = pipe.execute()

    raw_state = results[-3]
    raw_tokens = results[-1]

    state = json.loads(raw_state) if raw_state else {}
    tokens = [t.decode("utf-8") for t in raw_tokens]

    if not tokens:
        return state, []

    raw_users = cache.hmget(Sync.USERS.value, tokens)
    users = [json.loads(u) for u in raw_users if u]
    return state, users


# @testable true
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
# @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_sync_response_contract_is_browser_visible
# @features sync
# @dimensions document collaboration persistence response-contract
def set_state(sync_id, state):
    """Persist ``state`` for ``sync_id`` and refresh its TTL."""
    if not state:
        return

    with cache.pipeline() as pipe:
        pipe.hset(Sync.STATE.value, sync_id, json.dumps(state))
        pipe.hexpire(Sync.STATE.value, FIVE_MINUTES, sync_id)
        pipe.execute()


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_clear_state_deletes_cached_widget_state
# @features sync
# @dimensions sync-state invalidation
def clear_state(sync_id):
    """Drop the cached state for ``sync_id``."""
    with cache.pipeline() as pipe:
        pipe.hdel(Sync.STATE.value, sync_id)
        pipe.execute()


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_deregister_removes_token_from_composite_hashes
# @features sync
# @dimensions document deregistration stale-sessions composite-sync-id
def deregister(token, sync_ids):
    """Remove ``token`` from every registration set it had joined.

    ``sync_ids`` is the list the client knew it was registered to (typically
    everything in its ``active`` and ``offline`` arrays at the moment of
    unload). The user details entry is dropped unconditionally so co-viewers
    stop seeing them in active-user lists on their next poll.
    """
    if not token:
        return

    entity_hashes = {h for s in sync_ids or [] for h in _entity_hashes(s)}

    with cache.pipeline() as pipe:
        for sync_id in sync_ids or []:
            pipe.srem(Sync.WIDGET.key(sync_id), token)
        for h in entity_hashes:
            pipe.srem(Sync.ENTITY.key(h), token)
        pipe.hdel(Sync.USERS.value, token)
        pipe.execute()


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_discard_viewer_tokens_invalidates_registrations
# @features sync
# @dimensions stale-token invalidation
def discard_viewer_tokens(tokens):
    """Invalidate FCM registrations while their expiring set entries age out."""
    tokens = tuple(dict.fromkeys(token for token in tokens or [] if token))
    if not tokens:
        return

    with cache.pipeline() as pipe:
        pipe.hdel(Sync.USERS.value, *tokens)
        pipe.execute()


# @testable true
# @tests tests_unit/test_010_sync_cache.py::test_active_viewers_unions_entity_registration_sets
# @features sync
# @dimensions active-viewers entity-registration dedupe empty-input stale-sessions
def active_viewers(hashes):
    """Return valid tokens viewing any of ``hashes`` (entity-level)."""
    if not hashes:
        return set()

    with cache.pipeline() as pipe:
        for h in hashes:
            pipe.smembers(Sync.ENTITY.key(h))
        results = pipe.execute()

    tokens = {t.decode("utf-8") for members in results for t in members}
    if not tokens:
        return set()

    ordered_tokens = sorted(tokens)
    registrations = cache.hmget(Sync.USERS.value, ordered_tokens)
    return {
        token
        for token, registration in zip(ordered_tokens, registrations)
        if registration
    }
