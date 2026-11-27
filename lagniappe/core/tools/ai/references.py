"""AI-facing short reference helpers."""

import re
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User
    from ..cache.details import CachedDetail
    from ..files.html import SafeHTML
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities import Identifier

from lagniappe.core.definitions import Action
from lagniappe.core.tools import cache
from lagniappe.core.tools.files.html import render_markdown


HASH_REFERENCE_REGEX = re.compile(r"\bhash:([0-9a-z]{12})\b")
HASH_PREFIXED_ID_REGEX = re.compile(r"\bhash:(ah[A-Za-z0-9_-]{30,})\b")
HASH_TOKEN_REGEX = re.compile(r"\bhash:([A-Za-z0-9_-]+)\b")


def stored_file_identifiers(entity: Entity) -> list[Identifier]:
    """Return attachment IDs from a raw Task or TaskHistory record."""
    identifiers = entity.db.get("files") or []
    if not isinstance(identifiers, list):
        raise TypeError("Stored file references must be an array")
    return identifiers


def render_ai_markdown(text: str) -> SafeHTML:
    """Render model Markdown after resolving known AI references for browser use."""
    return render_markdown(normalize_hash_references(text))


def hash_reference(entity: object) -> str | None:
    """Return the explicit AI reference token for an entity hash."""
    entity_hash = getattr(entity, "hash", None)
    return f"hash:{entity_hash}" if entity_hash else None


def personal_page_reference(user: User) -> dict[str, object]:
    """Return the authenticated user's guaranteed editable Page reference."""
    page = user.page
    return {
        "kind": "page",
        "hash": hash_reference(page),
        "name": page.name,
        "url": page.url,
        "can_view": page.allowed(Action.VIEW, user=user),
        "can_edit": page.allowed(Action.EDIT, user=user),
    }


@overload
def normalize_hash_references[V](value: dict[str, V], *, resolved_details: dict[str, CachedDetail] | None = None) -> dict[str, V]: ...
@overload
def normalize_hash_references(value: str, *, resolved_details: dict[str, CachedDetail] | None = None) -> str: ...
@overload
def normalize_hash_references[V](value: list[V], *, resolved_details: dict[str, CachedDetail] | None = None) -> list[V]: ...
@overload
def normalize_hash_references(value: object, *, resolved_details: dict[str, CachedDetail] | None = None) -> object: ...


def normalize_hash_references(value: object, *, resolved_details: dict[str, CachedDetail] | None = None) -> object:
    """Replace known ``hash:...`` tokens with executable entity ids.

    The payload is scanned first so all hashes are resolved in one cache lookup.
    Unknown hashes remain unchanged.
    """
    hashes = _collect_hash_references(value)
    executable_ids = _collect_hash_prefixed_ids(value)
    replacements = {
        f"hash:{entity_id}": entity_id for entity_id in executable_ids
    }

    if hashes:
        details = cache.get_details_by_hash(hashes)
        if resolved_details is not None:
            resolved_details.update(details)
        replacements.update(
            {
                f"hash:{entity_hash}": item["id"]
                for entity_hash, item in details.items()
                if isinstance(item, dict) and "id" in item and item["id"]
            }
        )
    if not replacements:
        return value

    return _replace_hash_references(value, replacements)


def _collect_hash_references(value):
    hashes = []
    if isinstance(value, dict):
        for key, child in value.items():
            hashes.extend(_collect_hash_references(key))
            if key != "artifact_html":
                hashes.extend(_collect_hash_references(child))
    elif isinstance(value, list):
        for child in value:
            hashes.extend(_collect_hash_references(child))
    elif isinstance(value, str):
        hashes.extend(HASH_REFERENCE_REGEX.findall(value))
    return list(dict.fromkeys(hashes))


def _collect_hash_prefixed_ids(value):
    ids = []
    if isinstance(value, dict):
        for key, child in value.items():
            ids.extend(_collect_hash_prefixed_ids(key))
            if key != "artifact_html":
                ids.extend(_collect_hash_prefixed_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.extend(_collect_hash_prefixed_ids(child))
    elif isinstance(value, str):
        ids.extend(HASH_PREFIXED_ID_REGEX.findall(value))
    return list(dict.fromkeys(ids))


def _replace_hash_references(value, replacements):
    if isinstance(value, dict):
        return {
            _replace_hash_references(key, replacements): (
                child if key == "artifact_html" else _replace_hash_references(child, replacements)
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_hash_references(child, replacements) for child in value]
    if not isinstance(value, str):
        return value

    return HASH_TOKEN_REGEX.sub(
        lambda match: replacements.get(match.group(0), match.group(0)),
        value,
    )
