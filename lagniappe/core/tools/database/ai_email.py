"""Durable AI-email webhook event claims."""

from datetime import datetime, timedelta

from google.cloud.datastore import Entity

from .core import DATA
from .transactions import retry_aborted
from .utility import create_named_key


AI_EMAIL_EVENT_SCHEMA_VERSION = 1
AI_EMAIL_EVENT_PREFIX = "ai-email-event:"


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_ai_email_event_claim_is_durable_and_replay_safe
# @features ai-email webhook
# @dimensions replay transaction lease privacy
@retry_aborted
def claim_ai_email_event(digest, lease_token, now, *, lease_seconds=300):
    """Claim one HMAC-digested provider event without storing its raw ID."""
    digest = str(digest or "").strip().casefold()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("AI email event digest is invalid")
    key = create_named_key("site", f"{AI_EMAIL_EVENT_PREFIX}{digest}")
    with DATA.datastore.transaction() as transaction:
        record = DATA.datastore.get(key, transaction=transaction)
        if record is not None:
            state = str(record.get("state") or "")
            expires = record.get("lease_expires")
            if state in {"accepted", "rejected", "ignored"}:
                return {"claimed": False, "reason": "terminal", "state": state}
            if (
                state == "processing"
                and record.get("lease_token") != lease_token
                and isinstance(expires, datetime)
                and expires > now
            ):
                return {"claimed": False, "reason": "active", "state": state}
        else:
            record = Entity(key=key, exclude_from_indexes=("lease_token",))
            record["created"] = now
        record.update(
            {
                "schema_version": AI_EMAIL_EVENT_SCHEMA_VERSION,
                "state": "processing",
                "lease_token": lease_token,
                "lease_expires": now + timedelta(seconds=lease_seconds),
                "modified": now,
            }
        )
        transaction.put(record)
        return {"claimed": True, "key": key}


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_ai_email_event_claim_is_durable_and_replay_safe
# @features ai-email webhook
# @dimensions replay terminal-compaction transaction
@retry_aborted
def finish_ai_email_event(digest, lease_token, state, now):
    """Compact an owned event claim to a minimal permanent tombstone."""
    if state not in {"accepted", "rejected", "ignored"}:
        raise ValueError("AI email event terminal state is invalid")
    key = create_named_key("site", f"{AI_EMAIL_EVENT_PREFIX}{digest}")
    with DATA.datastore.transaction() as transaction:
        record = DATA.datastore.get(key, transaction=transaction)
        if record is None or record.get("lease_token") != lease_token:
            return False
        created = record.get("created") or now
        compacted = Entity(key=key)
        compacted.update(
            {
                "schema_version": AI_EMAIL_EVENT_SCHEMA_VERSION,
                "state": state,
                "created": created,
                "modified": now,
                "completed": now,
            }
        )
        transaction.put(compacted)
        return True


# @testable true
# @tests tests_unit/test_028_ai_email.py::test_ai_email_event_claim_is_durable_and_replay_safe
# @features ai-email webhook
# @dimensions replay transient-release transaction
@retry_aborted
def release_ai_email_event(digest, lease_token, now):
    """Release an owned claim so a provider retry may resume it immediately."""
    key = create_named_key("site", f"{AI_EMAIL_EVENT_PREFIX}{digest}")
    with DATA.datastore.transaction() as transaction:
        record = DATA.datastore.get(key, transaction=transaction)
        if record is None or record.get("lease_token") != lease_token:
            return False
        record["state"] = "retry"
        record.pop("lease_token", None)
        record.pop("lease_expires", None)
        record["modified"] = now
        transaction.put(record)
        return True
