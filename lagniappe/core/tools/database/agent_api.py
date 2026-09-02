"""Transactional storage for one external-agent credential per user."""

from google.cloud.datastore import Entity as DatastoreEntity

from .core import DATA
from .transactions import retry_aborted
from .utility import create_named_key


EXCLUDED_FIELDS = ("token_digest",)


# @testable false
# @covered-by lagniappe/core/tools/database/agent_api.py::rotate_credential
# @reason named key construction is exercised through transactional rotation
def credential_key(identifier):
    return create_named_key("agent_api_credential", identifier)


# @testable false
# @covered-by lagniappe/core/tools/auth/agent_api.py::authenticate_credential
# @reason raw lookup is owned by the authenticated credential boundary
def get_credential(identifier):
    return DATA.datastore.get(credential_key(identifier))


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_credential_rotation_and_revocation_are_transactional
# @matrix agent-api : credential persistence revoke rotate
@retry_aborted
def rotate_credential(
    identifier,
    user_key,
    *,
    token_digest,
    display_prefix,
    issued_at,
    expires_at,
):
    """Replace the user's sole credential and return its public metadata."""
    key = credential_key(identifier)
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(key, transaction=transaction)
        generation = int((current or {}).get("generation") or 0) + 1
        row = DatastoreEntity(key=key, exclude_from_indexes=EXCLUDED_FIELDS)
        row.update(
            {
                "user": user_key,
                "credential_id": identifier,
                "generation": generation,
                "token_digest": token_digest,
                "display_prefix": display_prefix,
                "issued_at": issued_at,
                "expires_at": expires_at,
                "active": True,
            }
        )
        transaction.put(row)
    return row


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_credential_rotation_and_revocation_are_transactional
# @matrix agent-api : credential persistence revoke rotate
@retry_aborted
def revoke_credential(identifier, user_key, *, revoked_at):
    """Invalidate the user's credential without deleting its audit metadata."""
    key = credential_key(identifier)
    with DATA.datastore.transaction() as transaction:
        current = DATA.datastore.get(key, transaction=transaction)
        if current is None or current.get("user") != user_key:
            return None
        current["generation"] = int(current.get("generation") or 0) + 1
        current["active"] = False
        current["revoked_at"] = revoked_at
        current.pop("token_digest", None)
        transaction.put(current)
    return current
