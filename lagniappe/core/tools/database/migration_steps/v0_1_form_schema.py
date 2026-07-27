"""Version 0.1 canonical form-schema migration."""

import json

from lagniappe.core.properties.schema import (
    SCHEMA_FORMAT_VERSION,
    SchemaValidationError,
    canonicalize_schema,
)

from .base import MigrationDataError


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_form_schema_transform_is_idempotent_and_preserves_history_membership
# @tests tests_unit/test_018b_database_migrations.py::test_form_schema_transform_repairs_invalid_legacy_fields
# @tests tests_unit/test_018b_database_migrations.py::test_form_schema_transform_rejects_unreadable_rows_without_mutation
# @pairs form-schema:canonicalization form-schema:idempotence
# @pairs form-schema:legacy-repair form-schema:history-snapshot
# @pair form-schema:malformed-data
# @pair form-schema:copy-on-write
def canonicalize_form_schema_record(entity, *, snapshot=False, repairs=None):
    """Canonicalize one raw form or form-history row, repairing legacy fields."""

    raw_schema = entity.get("schema")
    if raw_schema is None:
        parsed = []
    elif isinstance(raw_schema, str):
        try:
            parsed = json.loads(raw_schema)
        except (TypeError, ValueError) as error:
            raise MigrationDataError("schema is not valid JSON") from error
    elif isinstance(raw_schema, list):
        parsed = raw_schema
    else:
        raise MigrationDataError("schema must be a JSON list")

    try:
        canonical = canonicalize_schema(
            parsed,
            form_type=entity.get("form_type"),
            snapshot=snapshot,
        )
    except SchemaValidationError as error:
        canonical = canonicalize_schema(
            parsed,
            form_type=entity.get("form_type"),
            snapshot=snapshot,
            discard_invalid=True,
        )
        if repairs is not None:
            repairs.append(f"Removed invalid schema data: {error}")

    before_schema = entity.get("schema")
    before_format = entity.get("schema_format")
    if canonical:
        entity["schema"] = json.dumps(canonical)
    else:
        entity.pop("schema", None)
    entity["schema_format"] = SCHEMA_FORMAT_VERSION
    return (
        entity.get("schema") != before_schema
        or before_format != SCHEMA_FORMAT_VERSION
    )
