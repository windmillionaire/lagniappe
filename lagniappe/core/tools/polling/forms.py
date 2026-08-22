"""Runtime-safe contracts shared by form mutation and sync routes."""


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_sync_payload_validation_is_document_only_and_bounded
# @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_live_sync_rejects_form_widget_payloads
# @pairs sync:validation sync:document-only sync:client-identity forms:no-live-sync
def validate_sync_payload(payload):
    """Return a public validation error, or ``None`` for a valid sync payload."""
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
        sync_id = update.get("sync_id")
        if (
            not isinstance(update.get("key"), str)
            or not update["key"]
            or len(update["key"]) > 512
            or not isinstance(sync_id, str)
            or not sync_id.endswith(":document")
            or len(sync_id) > 512
        ):
            return "Only identified document widgets may use live sync."
        revision = update.get("revision")
        if revision is not None and (
            not isinstance(revision, int) or isinstance(revision, bool) or revision < 0
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
        if not isinstance(touch_parent, bool) or (touch_parent and not update["save"]):
            return "Document parent touch is invalid."
        for name in ("update", "ydoc", "html"):
            if update.get(name) is not None and not isinstance(update[name], str):
                return f"Document {name} must be encoded text."
        from ..mentions.content import validate_mentions_payload

        mention_error = validate_mentions_payload(update.get("mentions"))
        if mention_error:
            return mention_error
    return None


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_offline_replay_conflict_requires_stale_origin_fingerprint
# @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_task_offline_replay_rejects_a_stale_origin_fingerprint
# @pairs offline:replay-precondition forms:conflict-review
def offline_replay_conflicts(entity, form):
    """Return whether an offline form targets an outdated entity revision."""
    expected = form.get("offline-fingerprint")
    return bool(
        str(form.get("offline", "")).lower() == "true"
        and expected
        and expected != entity.fingerprint
    )


# @testable true
# @tests tests_unit/test_024_autofill_form_state.py::test_form_field_membership_uses_the_attached_schema
# @pairs deferred-jobs:form-lock deferred-jobs:quick-edit
def is_form_field(entity, field_id):
    """Return whether a quick-edit field belongs to an entity's form surface."""
    return bool(
        field_id
        and getattr(entity, "form", None)
        and any(
            isinstance(field, dict) and field.get("id") == field_id
            for field in (entity.form.schema or ())
        )
    )
