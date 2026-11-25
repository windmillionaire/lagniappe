"""Version 0.1 canonical form-schema migration."""

import json
from collections.abc import MutableMapping

from config.form_schema import (
    SCHEMA_FORMAT_VERSION,
    SchemaValidationError,
)
from config.form_schema import (
    normalize_form_schema as canonicalize_schema,
)

from .base import MigrationDataError


def canonicalize_form_schema_record(
    entity: MutableMapping[str, object],
    *,
    snapshot: bool = False,
    repairs: list[str] | None = None,
) -> bool:
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

    form_type = entity.get("form_type")
    if form_type is not None and not isinstance(form_type, str):
        raise MigrationDataError("form_type must be a string")
    try:
        canonical = canonicalize_schema(
            parsed,
            form_type=form_type,
            snapshot=snapshot,
        )
    except SchemaValidationError as error:
        canonical = canonicalize_schema(
            parsed,
            form_type=form_type,
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
