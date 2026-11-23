"""Short-lived authorization claims for newly uploaded Task attachments."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.user import User
    from lagniappe.core.entities.entity import Entity
    from lagniappe.core.entities.file import File


import hashlib

from itsdangerous import BadData, URLSafeTimedSerializer

from lagniappe import CONFIG


TASK_ATTACHMENT_CLAIM_MAX_AGE = 60 * 60
TASK_ATTACHMENT_CLAIM_SALT = "lagniappe-task-attachment-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        CONFIG.SECRET_KEY,
        salt=TASK_ATTACHMENT_CLAIM_SALT,
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def _key(entity):
    return getattr(entity, "urlsafe_key", None)


def sign_task_attachment_claim(*, actor: User, file: File, scope: Entity) -> str:
    """Sign permission to attach one new File within one authorized scope."""
    payload = {
        "v": 1,
        "actor": _key(actor),
        "file": _key(file),
        "scope_kind": getattr(scope, "entity_kind", None),
        "scope": _key(scope),
    }
    if not all(payload.values()):
        raise ValueError("Task attachment claim inputs must be persisted entities")
    return _serializer().dumps(payload)


def valid_task_attachment_claim(
    claim: str | None,
    *,
    actor: User,
    file: File,
    scope: Entity,
    max_age: int = TASK_ATTACHMENT_CLAIM_MAX_AGE,
) -> bool:
    """Return whether a claim authorizes this exact attachment operation."""
    if not claim:
        return False
    try:
        payload = _serializer().loads(claim, max_age=int(max_age))
    except (BadData, TypeError, ValueError):
        return False

    return payload == {
        "v": 1,
        "actor": _key(actor),
        "file": _key(file),
        "scope_kind": getattr(scope, "entity_kind", None),
        "scope": _key(scope),
    }


__all__ = [
    "TASK_ATTACHMENT_CLAIM_MAX_AGE",
    "sign_task_attachment_claim",
    "valid_task_attachment_claim",
]
