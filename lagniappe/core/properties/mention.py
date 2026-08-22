"""Persisted document-mention marker values and deterministic identity."""

import hashlib
import re

from .base_db import DBProperty


MAX_MENTIONS_PER_CHECKPOINT = 64
OCCURRENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mention_delivery_ledger_survives_notification_replay
# @pair mentions:idempotency
def occurrence_identity(document, occurrence_id):
    return hashlib.sha256(
        f"{document.urlsafe_key}\0{occurrence_id}".encode()
    ).hexdigest()


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:payload-validation
def valid_occurrence_id(value):
    return isinstance(value, str) and bool(OCCURRENCE_ID_PATTERN.fullmatch(value))


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:payload-validation
def valid_recipient(value):
    return isinstance(value, str) and bool(value) and len(value) <= 512


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:payload-validation
def valid_display_name(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:public-sanitization
def public_display_name(value):
    name = str(value or "").strip()
    return name.removeprefix("@").strip()


class Document(DBProperty):
    _id = "document"


class Actor(DBProperty):
    _id = "actor"


class Recipient(DBProperty):
    _id = "recipient"


class OccurrenceID(DBProperty):
    _id = "occurrence_id"


class DisplayName(DBProperty):
    _id = "display_name"
