"""Short-lived authorization claims for newly uploaded Task attachments."""

from __future__ import annotations

import hashlib

from itsdangerous import BadData, URLSafeTimedSerializer

from lagniappe import CONFIG


TASK_ATTACHMENT_CLAIM_MAX_AGE = 60 * 60
TASK_ATTACHMENT_CLAIM_SALT = "lagniappe-task-attachment-v1"


# @testable false
# @covered-by lagniappe/core/tools/auth/task_attachments.py::sign_task_attachment_claim
# @covered-by lagniappe/core/tools/auth/task_attachments.py::valid_task_attachment_claim
# @reason serializer configuration is exercised through signed claim operations
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        CONFIG.SECRET_KEY,
        salt=TASK_ATTACHMENT_CLAIM_SALT,
        signer_kwargs={"digest_method": hashlib.sha256},
    )


# @testable false
# @covered-by lagniappe/core/tools/auth/task_attachments.py::sign_task_attachment_claim
# @covered-by lagniappe/core/tools/auth/task_attachments.py::valid_task_attachment_claim
# @reason entity identity normalization is exercised through signed claim operations
def _key(entity):
    return getattr(entity, "urlsafe_key", None)


# @testable true
# @tests tests_unit/test_031_submitted_references.py::test_task_attachment_claim_is_actor_file_scope_bound_and_expiring
# @matrix task-attachments : actor expiry file scope signed-claim
def sign_task_attachment_claim(*, actor, file, scope) -> str:
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


# @testable true
# @tests tests_unit/test_031_submitted_references.py::test_task_attachment_claim_is_actor_file_scope_bound_and_expiring
# @matrix task-attachments : actor expiry file scope signed-claim tamper validation
def valid_task_attachment_claim(
    claim,
    *,
    actor,
    file,
    scope,
    max_age=TASK_ATTACHMENT_CLAIM_MAX_AGE,
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
