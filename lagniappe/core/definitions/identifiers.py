"""Compact identifiers used by persisted entities and exported assets."""

import hashlib
import os
import uuid


def short_hash(value: str) -> str:
    """Return the first 12 characters of a SHA-256 hex digest."""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def random_hash(length: int = 12) -> str:
    """Return a random lowercase alphanumeric string."""
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(alphabet[byte % len(alphabet)] for byte in os.urandom(length))


def short_uuid() -> str:
    """Return the first segment of a UUID4."""
    return str(uuid.uuid4()).split("-")[0]
