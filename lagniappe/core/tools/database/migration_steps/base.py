"""Shared value types for durable data migration steps."""

from dataclasses import dataclass


# @testable infrastructure
class MigrationDataError(ValueError):
    """A stored row cannot be migrated without an explicit repair decision."""


# @testable infrastructure
@dataclass(frozen=True)
class MigrationChange:
    """A transform outcome with successful repair details for the audit."""

    changed: bool
    repairs: tuple[str, ...] = ()
