"""Runtime-safe contracts shared by form mutation and sync routes."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity
    from collections.abc import Mapping
    from lagniappe.core.entities.page import Page
    from lagniappe.core.entities.task import Task


def validate_sync_payload(payload: object) -> str | None:
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


def offline_replay_conflicts(entity: Entity, form: Mapping[str, object]) -> bool:
    """Return whether an offline form targets an outdated entity revision."""
    expected = form.get("offline-fingerprint")
    return bool(
        str(form.get("offline", "")).lower() == "true"
        and expected
        and expected != entity.fingerprint
    )


def is_form_field(entity: Page | Task, field_id: str | None) -> bool:
    """Return whether a quick-edit field belongs to an entity's form surface."""
    form = getattr(entity, "form", None)
    return bool(
        field_id
        and form
        and any(
            isinstance(field, dict) and field.get("id") == field_id
            for field in (form.schema or ())
        )
    )
