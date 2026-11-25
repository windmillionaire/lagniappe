"""Deterministic entity revisions shared by durable and cached projections."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime

from ..tools.auth.restrictions import normalize_restrictions


def base_fingerprint(modified: datetime) -> str:
    """Hash the durable modification timestamp without changing its meaning."""
    return hashlib.md5(modified.isoformat().encode("utf-8")).hexdigest()


def restricted_fingerprint(
    base: str,
    restricted_to: Mapping[str, Iterable[str]] | None,
    *,
    form_version: str | None = None,
) -> str:
    """Include independent source clauses and the entity's own Form version.

    ``None`` omits the Form component for Files; ``""`` represents a Page or
    Task without a Form. Source boundaries matter; group order and duplicates do not.
    """
    parts = [base]
    if form_version is not None:
        parts.append(form_version)
    parts.append(json.dumps(normalize_restrictions(restricted_to), sort_keys=True, separators=(",", ":")))
    return hashlib.md5(":".join(parts).encode("utf-8")).hexdigest()
