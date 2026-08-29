"""Runtime-neutral persisted data-migration ledger identifiers."""

LEDGER_SCHEMA_VERSION = 1
MIGRATION_STATUS_PREFIX = "data-migration:"
ASSET_GENERATION_MIGRATION_ID = "AST-001"


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::_migration_key
# @reason runtime-neutral identifier formatting is exercised through migration ledger keys
def migration_status_identifier(migration_id):
    """Return the stable Datastore name for one migration status record."""
    return f"{MIGRATION_STATUS_PREFIX}{str(migration_id).strip()}"


__all__ = [
    "ASSET_GENERATION_MIGRATION_ID",
    "LEDGER_SCHEMA_VERSION",
    "MIGRATION_STATUS_PREFIX",
    "migration_status_identifier",
]
