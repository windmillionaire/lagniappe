"""Shared migration contracts, raw-row scanning, and audit result helpers.

Catalog orchestration and versioned steps depend on this module; it must not
import the catalog, ledger runner, or historical migration implementations.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Iterable

from google.cloud.datastore import Entity as DatastoreEntity

from config.datastore import encode_urlsafe_key


MIGRATION_CHUNK_SIZE = 100
MAX_RECORDED_ERRORS = 25
MAX_RECORDED_REPAIRS = 25


# @testable infrastructure
class MigrationDataError(ValueError):
    """A stored row cannot be migrated without an explicit repair decision."""


# @testable infrastructure
@dataclass(frozen=True)
class MigrationChange:
    """A transform outcome with successful repair details for the audit."""

    changed: bool
    repairs: tuple[str, ...] = ()


# @testable infrastructure
class MigrationLeaseLost(RuntimeError):
    """The active migration request no longer owns the execution lease."""


# @testable infrastructure
@dataclass(frozen=True)
class MigrationContext:
    """Services available to a registered migration runner."""

    query_factory: Callable
    writer: Callable
    datastore: object
    heartbeat: Callable[[], None] = lambda: None


# @testable infrastructure
@dataclass(frozen=True)
class MigrationDefinition:
    """Immutable identity and implementation for one ordered migration."""

    sequence: int
    id: str
    introduced_in: str
    label: str
    runner: Callable[[MigrationContext], dict]
    legacy_audit_keys: tuple[str, ...] = ()


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/v2_0_permissions.py::migrate_file_ownership
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason file scan failures and saved failure projection exercise the same raw-row link
def _file_record_reference(entity):
    name = entity.get("name") or entity.get("filename")
    return {
        "url": f"/files/{encode_urlsafe_key(entity.key)}",
        "link_label": name.strip() if isinstance(name, str) and name.strip() else "Open file",
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason result-envelope construction is exercised through registered runners
def _result(migration_id, label):
    return {
        "id": migration_id,
        "label": label,
        "examined": 0,
        "changed": 0,
        "repaired": 0,
        "skipped": 0,
        "failed": 0,
        "repairs": [],
        "errors": [],
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/base.py::scan_kind
# @reason bounded detail aggregation is exercised through scan and runner tests
def _append_error(result, identifier, error, *, reference=None):
    result["failed"] += 1
    if len(result["errors"]) < MAX_RECORDED_ERRORS:
        detail = {
            "key": identifier,
            "message": str(error) or type(error).__name__,
        }
        detail.update(reference or {})
        result["errors"].append(detail)


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/base.py::scan_kind
# @reason bounded repair aggregation is exercised through form-schema migration tests
def _append_repair(result, identifier, message, *, reference=None):
    result["repaired"] = result.get("repaired", 0) + 1
    repairs = result.setdefault("repairs", [])
    if len(repairs) < MAX_RECORDED_REPAIRS:
        detail = {"key": identifier, "message": message}
        detail.update(reference or {})
        repairs.append(detail)


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/base.py::scan_kind
# @reason callback normalization is exercised through linked scan details
def _reference_detail(callback, entity):
    if not callback:
        return {}
    try:
        value = callback(entity)
    except Exception:
        return {}
    if isinstance(value, str):
        return {"url": value}
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in ("url", "link_label")
        if isinstance(value.get(key), str) and value[key]
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/base.py::scan_kind
# @reason raw row identifiers are audit-owned infrastructure
def _entity_identifier(entity):
    key = getattr(entity, "key", None)
    if key is None:
        return "unknown"
    try:
        return encode_urlsafe_key(key)
    except (AttributeError, TypeError, ValueError):
        return str(key)


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/base.py::scan_kind
# @reason copy-on-write construction is exercised through generic scan tests
def _clone_entity(entity):
    key = getattr(entity, "key", None)
    if key is None:
        return deepcopy(entity)
    clone = DatastoreEntity(
        key=key,
        exclude_from_indexes=tuple(
            getattr(entity, "exclude_from_indexes", ()) or ()
        ),
    )
    clone.update(deepcopy(dict(entity)))
    return clone


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/base.py::scan_kind
# @reason bounded iteration is exercised through generic scan tests
def _chunks(iterable: Iterable, size=MIGRATION_CHUNK_SIZE):
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


# @testable false
# @covered-by lagniappe/core/tools/database/migration_steps/base.py::scan_kind
# @reason write accounting is exercised through generic scan tests
def _save_changed(result, changed, writer, reference=None):
    if not changed:
        return
    entities = [entity for entity, _repairs in changed]
    try:
        writer(*entities)
    except Exception as error:
        for entity in entities:
            detail = _reference_detail(reference, entity)
            _append_error(
                result,
                _entity_identifier(entity),
                error,
                reference=detail,
            )
        return
    result["changed"] += len(entities)
    for entity, repairs in changed:
        detail = _reference_detail(reference, entity)
        for message in repairs:
            _append_repair(
                result,
                _entity_identifier(entity),
                message,
                reference=detail,
            )


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_scan_kind_is_copy_on_write_chunked_and_failure_isolated
# @matrix database migrations : chunks copy-on-write failures heartbeat inactive-rows raw-scan
def scan_kind(result, context, kind, predicate, transform, reference=None):
    """Apply one transform to matching raw rows and update ``result`` counts."""

    try:
        rows = context.query_factory(kind).fetch_iter()
        for chunk in _chunks(rows):
            changed = []
            for entity in chunk:
                if not predicate(entity):
                    continue
                result["examined"] += 1
                candidate = _clone_entity(entity)
                try:
                    outcome = transform(candidate)
                except Exception as error:
                    detail = _reference_detail(reference, entity)
                    _append_error(
                        result,
                        _entity_identifier(entity),
                        error,
                        reference=detail,
                    )
                    continue
                if isinstance(outcome, MigrationChange):
                    did_change = outcome.changed
                    repairs = outcome.repairs
                else:
                    did_change = outcome
                    repairs = ()
                if did_change:
                    changed.append((candidate, repairs))
                else:
                    result["skipped"] += 1
            _save_changed(result, changed, context.writer, reference)
            context.heartbeat()
    except MigrationLeaseLost:
        raise
    except Exception as error:
        kind_name = getattr(kind, "value", kind)
        _append_error(result, f"{kind_name}:query", error)
    return result
