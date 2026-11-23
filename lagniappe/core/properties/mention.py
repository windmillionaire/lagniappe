"""Persisted document-mention marker values and deterministic identity."""

from __future__ import annotations

from google.cloud.datastore import Key
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lagniappe.core.entities.entity import Entity
    from typing import TypeGuard


import hashlib
import re

from .base_db import DBProperty


MAX_MENTIONS_PER_CHECKPOINT = 64
OCCURRENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mention_delivery_ledger_survives_notification_replay
# @pair mentions:idempotency
def occurrence_identity(document: Entity, occurrence_id: str) -> str:
    return hashlib.sha256(
        f"{document.urlsafe_key}\0{occurrence_id}".encode()
    ).hexdigest()


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:payload-validation
def valid_occurrence_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(OCCURRENCE_ID_PATTERN.fullmatch(value))


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:payload-validation
def valid_recipient(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value) and len(value) <= 512


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:payload-validation
def valid_display_name(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


# @testable true
# @tests tests_unit/test_027c_mentions.py::test_mentions_validate_saved_occurrences_dedupe_and_sanitize
# @pair mentions:public-sanitization
def public_display_name(value: object) -> str:
    name = str(value or "").strip()
    return name.removeprefix("@").strip()


class Document(DBProperty[Key]):
    _id = "document"


class Actor(DBProperty[Key]):
    _id = "actor"


class Recipient(DBProperty[Key]):
    _id = "recipient"


class OccurrenceID(DBProperty[str]):
    _id = "occurrence_id"


class DisplayName(DBProperty[str]):
    _id = "display_name"
