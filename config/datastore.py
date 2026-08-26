"""Installer-only database validation and database-aware key encoding."""

from __future__ import annotations

import base64
import binascii
import re

from google.protobuf.message import DecodeError


DEFAULT_DATABASE_ID = "(default)"
DATABASE_ID_PATTERN = re.compile(r"\A[a-z][a-z0-9-]{2,61}[a-z0-9]\Z")
UUID_PATTERN = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


# @testable true
# @tests tests_unit/test_016_config.py::test_installer_database_id_validation
# @pair data-lifecycle:named-scratch-database
def validate_database_id(value, *, allow_default=True):
    value = str(value or "").strip()
    if allow_default and value == DEFAULT_DATABASE_ID:
        return value
    if (
        not DATABASE_ID_PATTERN.fullmatch(value)
        or not 4 <= len(value) <= 63
        or UUID_PATTERN.fullmatch(value)
    ):
        raise ValueError(
            "Datastore database IDs must be 4-63 lowercase letters, digits, or "
            "hyphens, start with a letter, end with a letter or digit, and not "
            "resemble a UUID."
        )
    return value


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_database_aware_urlsafe_key_round_trip
# @pair database:named-key-encoding
def encode_urlsafe_key(key):
    """Encode a Datastore Key, retaining a named database when present."""
    raw_database_id = getattr(key, "database", None)
    database_id = str(raw_database_id or DEFAULT_DATABASE_ID)
    if database_id == DEFAULT_DATABASE_ID:
        if raw_database_id:
            from google.cloud.datastore import Key

            key = Key(
                *key.flat_path,
                project=key.project,
                namespace=key.namespace,
            )
        return key.to_legacy_urlsafe().decode("ascii")
    from google.cloud.datastore import Key
    from google.cloud.datastore import key as key_module

    default_key = Key(
        *key.flat_path,
        project=key.project,
        namespace=key.namespace,
    )
    token = default_key.to_legacy_urlsafe()
    padding = b"=" * (-len(token) % 4)
    reference = key_module._app_engine_key_pb2.Reference()
    reference.ParseFromString(base64.urlsafe_b64decode(token + padding))
    reference.database_id = validate_database_id(database_id, allow_default=False)
    return base64.urlsafe_b64encode(reference.SerializeToString()).rstrip(b"=").decode("ascii")


# @testable true
# @tests tests_unit/test_018_database_utility.py::test_database_aware_urlsafe_key_round_trip
# @pair database:named-key-encoding
def decode_urlsafe_key(value):
    """Decode default or named-database legacy Reference tokens."""
    from google.cloud.datastore import Key
    from google.cloud.datastore import key as key_module

    if not isinstance(value, (str, bytes)):
        raise ValueError("Datastore key token must be text or bytes.")
    encoded = value if isinstance(value, bytes) else value.encode("ascii")
    if not encoded or not re.fullmatch(rb"[A-Za-z0-9_-]+", encoded):
        raise ValueError("Datastore key token is not canonical urlsafe base64.")
    padding = b"=" * (-len(encoded) % 4)
    reference = key_module._app_engine_key_pb2.Reference()
    try:
        reference.ParseFromString(base64.b64decode(encoded + padding, altchars=b"-_", validate=True))
    except (binascii.Error, DecodeError, ValueError) as error:
        raise ValueError("Datastore key token is invalid.") from error
    if not reference.path.element:
        raise ValueError("Datastore key token has no path.")
    database_id = str(reference.database_id or DEFAULT_DATABASE_ID)
    if database_id == DEFAULT_DATABASE_ID:
        return Key.from_legacy_urlsafe(encoded)
    return Key(
        *key_module._get_flat_path(reference.path),
        project=key_module._clean_app(reference.app),
        namespace=key_module._get_empty(reference.name_space, ""),
        database=validate_database_id(database_id, allow_default=False),
    )


__all__ = [
    "DEFAULT_DATABASE_ID",
    "decode_urlsafe_key",
    "encode_urlsafe_key",
    "validate_database_id",
]
