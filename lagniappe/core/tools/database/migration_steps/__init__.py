"""Append-only migration steps; import versioned implementations explicitly."""

from .base import MigrationChange, MigrationDataError

__all__ = [
    "MigrationChange",
    "MigrationDataError",
]
