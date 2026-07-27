"""Append-only data migration catalog, runner, and durable site ledger."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Callable, Iterable
from uuid import uuid4

from google.cloud.datastore import Entity as DatastoreEntity

from lagniappe import CONFIG

from . import utility
from .core import DATA, KINDS
from .filter import Query
from .migration_steps import (
    MigrationChange,
    MigrationDataError,
    canonicalize_form_schema_record,
)


LEDGER_SCHEMA_VERSION = 1
MIGRATION_CHUNK_SIZE = 100
MIGRATION_LEASE_SECONDS = 600
MIGRATION_STATUS_PREFIX = "data-migration:"
MIGRATION_CONTROL_ID = "data-migrations-control"
MAX_RECORDED_ATTEMPTS = 5
MAX_RECORDED_ERRORS = 25
MAX_RECORDED_REPAIRS = 25


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
# @covered-by lagniappe/core/tools/database/migrations.py::_run_form_schema_migration
# @reason form and form-history references are exercised through migration audit details
def _form_record_reference(entity):
    key = getattr(entity, "key", None)
    if entity.get("type") == "form_history":
        key = entity.get("form") or getattr(key, "parent", None)
    if key is None:
        return None
    try:
        identifier = key.to_legacy_urlsafe().decode()
    except (AttributeError, TypeError, ValueError):
        identifier = key if isinstance(key, str) else None
    if not identifier:
        return None
    return {
        "url": f"/forms/{identifier}",
        "link_label": "Open form",
    }


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_registered_form_schema_migration_scans_forms_and_history
# @tests tests_unit/test_018b_database_migrations.py::test_form_schema_migration_links_unreadable_row_failure_to_form
# @pairs migrations:runner migrations:audit
# @pairs form-schema:canonicalization form-schema:history-snapshot form-schema:malformed-data
def _run_form_schema_migration(context):
    result = _result("FSM-001", "Canonical form schemas")

    # @testable false
    # @covered-by lagniappe/core/tools/database/migrations.py::_run_form_schema_migration
    # @reason runner-local adapter for attaching repair details to scan outcomes
    def transform(row, *, snapshot=False):
        repairs = []
        changed = canonicalize_form_schema_record(
            row,
            snapshot=snapshot,
            repairs=repairs,
        )
        return MigrationChange(changed, tuple(repairs))

    scan_kind(
        result,
        context,
        KINDS.models,
        lambda row: row.get("type") == "form",
        transform,
        reference=_form_record_reference,
    )
    scan_kind(
        result,
        context,
        KINDS.history,
        lambda row: row.get("type") == "form_history",
        lambda row: transform(row, snapshot=True),
        reference=_form_record_reference,
    )
    return result


MIGRATION_CATALOG = (
    MigrationDefinition(
        sequence=1,
        id="FSM-001",
        introduced_in="0.1",
        label="Canonical form schemas",
        runner=_run_form_schema_migration,
        legacy_audit_keys=("2026-07-form-schema-v1",),
    ),
)


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
# @covered-by lagniappe/core/tools/database/migrations.py::scan_kind
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
# @covered-by lagniappe/core/tools/database/migrations.py::scan_kind
# @reason bounded repair aggregation is exercised through form-schema migration tests
def _append_repair(result, identifier, message, *, reference=None):
    result["repaired"] = result.get("repaired", 0) + 1
    repairs = result.setdefault("repairs", [])
    if len(repairs) < MAX_RECORDED_REPAIRS:
        detail = {"key": identifier, "message": message}
        detail.update(reference or {})
        repairs.append(detail)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::scan_kind
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
# @covered-by lagniappe/core/tools/database/migrations.py::scan_kind
# @reason raw row identifiers are audit-owned infrastructure
def _entity_identifier(entity):
    key = getattr(entity, "key", None)
    if key is None:
        return "unknown"
    try:
        return key.to_legacy_urlsafe().decode()
    except (AttributeError, TypeError, ValueError):
        return str(key)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::scan_kind
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
# @covered-by lagniappe/core/tools/database/migrations.py::scan_kind
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
# @covered-by lagniappe/core/tools/database/migrations.py::scan_kind
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
# @features database migrations
# @dimensions raw-scan copy-on-write chunks failures inactive-rows heartbeat
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


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason timestamp normalization is exercised through public status behavior
def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason timestamp serialization is exercised through public status behavior
def _iso(value):
    return _utc(value).isoformat() if isinstance(value, datetime) else str(value)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason lease expiry parsing is exercised through stale lease tests
def _parse_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return _utc(value)
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason deterministic site key construction is exercised through ledger tests
def _migration_key(datastore, migration_id):
    return datastore.key("site", f"{MIGRATION_STATUS_PREFIX}{migration_id}")


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason deterministic control key construction is exercised through lease tests
def _control_key(datastore):
    return datastore.key("site", MIGRATION_CONTROL_ID)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @covered-by lagniappe/core/tools/database/migrations.py::initialize_fresh_install
# @reason provider transaction selection is exercised through public ledger writes
def _transaction(datastore):
    factory = getattr(datastore, "transaction", None)
    return factory() if factory else nullcontext(None)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @covered-by lagniappe/core/tools/database/migrations.py::initialize_fresh_install
# @reason transaction-aware reads are exercised through public ledger writes
def _transaction_get(datastore, key, transaction):
    if transaction is None:
        return datastore.get(key)
    return datastore.get(key, transaction=transaction)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @covered-by lagniappe/core/tools/database/migrations.py::initialize_fresh_install
# @reason transaction-aware writes are exercised through public ledger writes
def _transaction_put(datastore, transaction, entity):
    if transaction is None:
        datastore.put(entity)
    else:
        transaction.put(entity)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason batch loading behavior is exercised through catalog status tests
def _get_multi(datastore, keys):
    if not keys:
        return {}
    getter = getattr(datastore, "get_multi", None)
    if getter:
        try:
            records = getter(keys, missing=[])
        except TypeError:
            records = getter(keys)
    else:
        records = [datastore.get(key) for key in keys]
    return {record.key: record for record in records if record is not None}


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason bounded attempt decoding is exercised through malformed ledger tests
def _attempts(record):
    raw = record.get("attempts", "[]") if record else "[]"
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("migration attempts must be a list of objects")
    return deepcopy(value[-MAX_RECORDED_ATTEMPTS:])


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_catalog_rejects_identity_and_order_errors
# @features admin database-migrations
# @dimensions catalog identity order version runner
def validate_catalog(catalog=MIGRATION_CATALOG):
    """Reject mutable or ambiguous migration catalog definitions."""

    ids = set()
    sequences = set()
    previous = 0
    for definition in catalog:
        if not isinstance(definition, MigrationDefinition):
            raise ValueError("migration catalog entries must be MigrationDefinition values")
        if not definition.id or not definition.label or not definition.introduced_in:
            raise ValueError("migration identity, label, and introduced version are required")
        if definition.id in ids:
            raise ValueError(f"duplicate migration id {definition.id!r}")
        if definition.sequence in sequences:
            raise ValueError(f"duplicate migration sequence {definition.sequence}")
        if definition.sequence <= previous:
            raise ValueError("migration catalog sequence must be strictly increasing")
        if not callable(definition.runner):
            raise ValueError(f"migration {definition.id!r} requires a runner")
        ids.add(definition.id)
        sequences.add(definition.sequence)
        previous = definition.sequence
    return tuple(catalog)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason normalized audit errors are exercised through public status tests
def _audit_error_view(definition, message):
    return {
        "id": definition.id,
        "sequence": definition.sequence,
        "introduced_in": definition.introduced_in,
        "label": definition.label,
        "state": "audit-error",
        "source": None,
        "completed_at": None,
        "completed_version": None,
        "completed_build_id": None,
        "attempts": [],
        "latest_attempt": None,
        "audit_error": message,
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason durable record projection is exercised through catalog status tests
def _record_view(definition, record):
    if not record:
        return {
            "id": definition.id,
            "sequence": definition.sequence,
            "introduced_in": definition.introduced_in,
            "label": definition.label,
            "state": "pending",
            "source": None,
            "completed_at": None,
            "completed_version": None,
            "completed_build_id": None,
            "attempts": [],
            "latest_attempt": None,
            "audit_error": None,
        }
    expected = {
        "ledger_schema": LEDGER_SCHEMA_VERSION,
        "migration_id": definition.id,
        "sequence": definition.sequence,
        "introduced_in": definition.introduced_in,
    }
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            return _audit_error_view(
                definition,
                f"Stored {field} does not match the migration catalog",
            )
    state = record.get("state")
    if state not in {"running", "failed", "complete"}:
        return _audit_error_view(definition, f"Stored migration state {state!r} is invalid")
    try:
        attempts = _attempts(record)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return _audit_error_view(definition, str(error))
    return {
        "id": definition.id,
        "sequence": definition.sequence,
        "introduced_in": definition.introduced_in,
        "label": definition.label,
        "state": state,
        "source": record.get("completion_source"),
        "completed_at": record.get("completed_at"),
        "completed_version": record.get("completed_version"),
        "completed_build_id": record.get("completed_build_id"),
        "attempts": attempts,
        "latest_attempt": attempts[-1] if attempts else None,
        "audit_error": None,
        "active_run_id": record.get("active_run_id"),
        "active_started_at": record.get("active_started_at"),
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason legacy read-through is exercised through legacy audit adoption tests
def _legacy_view(definition, record):
    try:
        runs = _attempts({"attempts": record.get("runs", "[]")})
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return _audit_error_view(definition, f"Legacy audit is invalid: {error}")
    attempts = []
    for run in runs:
        result = next(
            (
                item
                for item in run.get("migrations", [])
                if item.get("id") == definition.id
            ),
            None,
        )
        if not result:
            continue
        totals = {
            key: result.get(key, 0)
            for key in ("examined", "changed", "repaired", "skipped", "failed")
        }
        attempts.append(
            {
                "run_id": run.get("run_id"),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "version": run.get("version"),
                "build_id": run.get("build_id"),
                "status": "complete" if totals["failed"] == 0 else "failed",
                "totals": totals,
                "repairs": deepcopy(result.get("repairs", [])),
                "errors": deepcopy(result.get("errors", [])),
            }
        )
    attempts = attempts[-MAX_RECORDED_ATTEMPTS:]
    completed = next(
        (attempt for attempt in reversed(attempts) if attempt["status"] == "complete"),
        None,
    )
    if not attempts:
        return None
    state = "complete" if completed else "failed"
    latest = attempts[-1]
    return {
        "id": definition.id,
        "sequence": definition.sequence,
        "introduced_in": definition.introduced_in,
        "label": definition.label,
        "state": state,
        "source": "legacy-audit",
        "completed_at": completed.get("finished_at") if completed else None,
        "completed_version": completed.get("version") if completed else None,
        "completed_build_id": completed.get("build_id") if completed else None,
        "attempts": attempts,
        "latest_attempt": latest,
        "audit_error": None,
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason catalog record composition is exercised through public status tests
def _load_views(datastore, catalog):
    status_keys = [_migration_key(datastore, definition.id) for definition in catalog]
    legacy_ids = tuple(
        dict.fromkeys(
            key
            for definition in catalog
            for key in definition.legacy_audit_keys
        )
    )
    legacy_keys = [datastore.key("site", key) for key in legacy_ids]
    records = _get_multi(datastore, [*status_keys, *legacy_keys, _control_key(datastore)])
    views = []
    for definition, key in zip(catalog, status_keys):
        record = records.get(key)
        view = _record_view(definition, record)
        if not record:
            for legacy_id in definition.legacy_audit_keys:
                legacy = records.get(datastore.key("site", legacy_id))
                if not legacy:
                    continue
                legacy_projection = _legacy_view(definition, legacy)
                if legacy_projection:
                    view = legacy_projection
                    break
        views.append(view)
    return views, records.get(_control_key(datastore))


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason lease state projection is exercised through running and stale lease tests
def _active_lease(control, now):
    if not control or not control.get("run_id"):
        return False
    expires_at = _parse_iso(control.get("lease_expires_at"))
    return bool(expires_at and expires_at > now)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::get_migration_status
# @reason aggregate counts are exercised through public status tests
def _status_counts(views):
    states = ("complete", "pending", "running", "failed", "interrupted", "blocked", "audit-error")
    counts = {state.replace("-", "_"): 0 for state in states}
    for view in views:
        counts[view["state"].replace("-", "_")] += 1
    counts["total"] = len(views)
    return counts


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_status_reads_completed_migrations_across_builds_and_blocks_after_failure
# @tests tests_unit/test_018b_database_migrations.py::test_legacy_audit_projects_as_completed
# @tests tests_unit/test_018b_database_migrations.py::test_migration_status_rejects_malformed_ledger
# @features admin database-migrations
# @dimensions catalog persistence build-history failure-order legacy-audit read-through invalid-storage audit identity sticky-completion
def get_migration_status(
    *,
    datastore=None,
    catalog=MIGRATION_CATALOG,
    now=None,
):
    """Return catalog-wide migration status from durable ``site`` records."""

    catalog = validate_catalog(catalog)
    datastore = datastore or DATA.datastore
    now_value = _utc((now or (lambda: datetime.now(timezone.utc)))())
    views, control = _load_views(datastore, catalog)
    lease_active = _active_lease(control, now_value)
    active_id = control.get("active_migration_id") if lease_active else None

    for view in views:
        if view["state"] == "running":
            owns_lease = lease_active and view.get("active_run_id") == control.get("run_id")
            if not owns_lease:
                view["state"] = "interrupted"
        if active_id == view["id"] and view["state"] == "pending":
            view["state"] = "running"

    blocker = None
    for view in views:
        if blocker and view["state"] == "pending":
            view["state"] = "blocked"
            view["blocked_by"] = blocker
        if view["state"] in {"failed", "interrupted", "audit-error"} and not blocker:
            blocker = view["id"]

    counts = _status_counts(views)
    if counts["audit_error"]:
        status = "audit-error"
    elif lease_active or counts["running"]:
        status = "running"
    elif counts["failed"] or counts["interrupted"]:
        status = "failed"
    elif counts["pending"] or counts["blocked"]:
        status = "pending"
    else:
        status = "current"
    return {
        "status": status,
        "current_version": getattr(CONFIG, "VERSION", None),
        "updates_available": status != "current",
        "cache_refresh_allowed": status == "current",
        "counts": counts,
        "active_run_id": control.get("run_id") if lease_active else None,
        "migrations": views,
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason transactional lease claims are exercised through concurrent runner tests
def _claim_lease(datastore, run_id, now):
    key = _control_key(datastore)
    with _transaction(datastore) as transaction:
        record = _transaction_get(datastore, key, transaction)
        if record and _active_lease(record, now) and record.get("run_id") != run_id:
            return False
        if not record:
            record = datastore.entity(key=key)
        record.update(
            {
                "ledger_schema": LEDGER_SCHEMA_VERSION,
                "run_id": run_id,
                "active_migration_id": None,
                "started_at": _iso(now),
                "heartbeat_at": _iso(now),
                "lease_expires_at": _iso(now + timedelta(seconds=MIGRATION_LEASE_SECONDS)),
            }
        )
        _transaction_put(datastore, transaction, record)
    return True


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason lease heartbeat behavior is exercised through runner recovery tests
def _renew_lease(datastore, run_id, migration_id, now):
    key = _control_key(datastore)
    with _transaction(datastore) as transaction:
        record = _transaction_get(datastore, key, transaction)
        if not record or record.get("run_id") != run_id:
            raise MigrationLeaseLost("migration execution lease was lost")
        record.update(
            {
                "active_migration_id": migration_id,
                "heartbeat_at": _iso(now),
                "lease_expires_at": _iso(now + timedelta(seconds=MIGRATION_LEASE_SECONDS)),
            }
        )
        _transaction_put(datastore, transaction, record)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason lease cleanup is exercised through successful and failed runner tests
def _release_lease(datastore, run_id, now):
    key = _control_key(datastore)
    with _transaction(datastore) as transaction:
        record = _transaction_get(datastore, key, transaction)
        if not record or record.get("run_id") != run_id:
            return
        record.update(
            {
                "run_id": None,
                "active_migration_id": None,
                "heartbeat_at": _iso(now),
                "lease_expires_at": None,
            }
        )
        _transaction_put(datastore, transaction, record)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @covered-by lagniappe/core/tools/database/migrations.py::initialize_fresh_install
# @reason status entity creation is exercised through public ledger writes
def _status_entity(datastore, definition, record=None):
    if record:
        return record
    return datastore.entity(
        key=_migration_key(datastore, definition.id),
        exclude_from_indexes=("attempts",),
    )


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @covered-by lagniappe/core/tools/database/migrations.py::initialize_fresh_install
# @reason immutable identity fields are exercised through persisted status tests
def _set_identity(record, definition):
    record.update(
        {
            "ledger_schema": LEDGER_SCHEMA_VERSION,
            "migration_id": definition.id,
            "sequence": definition.sequence,
            "introduced_in": definition.introduced_in,
            "label": definition.label,
        }
    )


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason interrupted attempt recovery is exercised through stale run tests
def _interrupted_attempt(record, finished_at):
    return {
        "run_id": record.get("active_run_id"),
        "started_at": record.get("active_started_at"),
        "finished_at": _iso(finished_at),
        "version": record.get("active_version"),
        "build_id": record.get("active_build_id"),
        "status": "interrupted",
        "totals": {key: 0 for key in ("examined", "changed", "repaired", "skipped", "failed")},
        "repairs": [],
        "errors": [{"key": "runner", "message": "Previous migration attempt was interrupted"}],
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason running checkpoints are exercised through runner recovery tests
def _start_migration(datastore, definition, run_id, started_at):
    key = _migration_key(datastore, definition.id)
    record = datastore.get(key)
    record = _status_entity(datastore, definition, record)
    attempts = _attempts(record)
    if record.get("state") == "running" and record.get("active_run_id") != run_id:
        attempts.append(_interrupted_attempt(record, started_at))
    _set_identity(record, definition)
    record.update(
        {
            "state": "running",
            "attempts": json.dumps(attempts[-MAX_RECORDED_ATTEMPTS:]),
            "active_run_id": run_id,
            "active_started_at": _iso(started_at),
            "active_version": getattr(CONFIG, "VERSION", None),
            "active_build_id": getattr(CONFIG, "BUILD_ID", None),
        }
    )
    datastore.put(record)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason attempt construction is exercised through durable runner tests
def _attempt(definition, result, run_id, started_at, finished_at):
    totals = _totals((result,))
    return {
        "run_id": run_id,
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
        "version": getattr(CONFIG, "VERSION", None),
        "build_id": getattr(CONFIG, "BUILD_ID", None),
        "status": "complete" if totals["failed"] == 0 else "failed",
        "totals": totals,
        "repairs": deepcopy(result.get("repairs", []))[:MAX_RECORDED_REPAIRS],
        "errors": deepcopy(result.get("errors", []))[:MAX_RECORDED_ERRORS],
    }


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason completed and failed checkpoints are exercised through durable runner tests
def _finish_migration(datastore, definition, attempt):
    key = _migration_key(datastore, definition.id)
    record = _status_entity(datastore, definition, datastore.get(key))
    attempts = _attempts(record)
    attempts.append(attempt)
    _set_identity(record, definition)
    complete = attempt["status"] == "complete"
    record.update(
        {
            "state": attempt["status"],
            "attempts": json.dumps(attempts[-MAX_RECORDED_ATTEMPTS:]),
            "active_run_id": None,
            "active_started_at": None,
            "active_version": None,
            "active_build_id": None,
        }
    )
    if complete:
        record.update(
            {
                "completion_source": "runner",
                "completed_at": attempt["finished_at"],
                "completed_version": attempt["version"],
                "completed_build_id": attempt["build_id"],
            }
        )
    datastore.put(record)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason legacy normalization is exercised through legacy audit adoption tests
def _persist_projected_view(datastore, definition, view):
    key = _migration_key(datastore, definition.id)
    if datastore.get(key):
        return
    record = _status_entity(datastore, definition)
    _set_identity(record, definition)
    record.update(
        {
            "state": view["state"],
            "attempts": json.dumps(view["attempts"][-MAX_RECORDED_ATTEMPTS:]),
            "completion_source": view.get("source"),
            "completed_at": view.get("completed_at"),
            "completed_version": view.get("completed_version"),
            "completed_build_id": view.get("completed_build_id"),
        }
    )
    datastore.put(record)


# @testable false
# @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
# @reason aggregate result counts are exercised through durable runner tests
def _totals(results):
    return {
        key: sum(result.get(key, 0) for result in results)
        for key in ("examined", "changed", "repaired", "skipped", "failed")
    }


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_ordered_runner_checkpoints_completion_and_resumes_after_failure
# @tests tests_unit/test_018b_database_migrations.py::test_runner_rejects_concurrent_lease_and_recovers_interrupted_attempt
# @tests tests_unit/test_018b_database_migrations.py::test_registered_form_schema_migration_scans_forms_and_history
# @tests tests_unit/test_018b_database_migrations.py::test_legacy_audit_projects_as_completed
# @tests tests_unit/test_018b_database_migrations.py::test_no_registered_migrations_is_a_noop_success
# @tests tests_unit/test_018b_database_migrations.py::test_attempt_history_retains_only_the_latest_five_runs
# @features admin database-migrations
# @dimensions ordered-run checkpoint failure resume lease lost-lease idempotence normalization catalog no-op concurrency interrupted-attempt stale-recovery bounded-history retries
def run_data_migrations(
    *,
    query_factory=None,
    writer=None,
    datastore=None,
    now=None,
    run_id_factory=None,
    catalog=MIGRATION_CATALOG,
):
    """Run incomplete catalog entries in order and checkpoint each result."""

    catalog = validate_catalog(catalog)
    datastore = datastore or DATA.datastore
    now = now or (lambda: datetime.now(timezone.utc))
    run_id_factory = run_id_factory or (lambda: str(uuid4()))
    initial = get_migration_status(datastore=datastore, catalog=catalog, now=now)
    if initial["status"] in {"current", "audit-error"}:
        return initial

    run_id = run_id_factory()
    claimed_at = _utc(now())
    if not _claim_lease(datastore, run_id, claimed_at):
        return get_migration_status(datastore=datastore, catalog=catalog, now=now)

    active_id = [None]

    # @testable false
    # @covered-by lagniappe/core/tools/database/migrations.py::run_data_migrations
    # @reason closure carries the current catalog id into chunk heartbeats
    def heartbeat():
        _renew_lease(datastore, run_id, active_id[0], _utc(now()))

    context = MigrationContext(
        query_factory or Query,
        writer or utility.save_raw,
        datastore,
        heartbeat,
    )
    try:
        initial_by_id = {item["id"]: item for item in initial["migrations"]}
        for definition in catalog:
            view = initial_by_id[definition.id]
            if view.get("source") == "legacy-audit" and view["state"] in {"complete", "failed"}:
                _persist_projected_view(datastore, definition, view)
            if view["state"] == "complete":
                continue

            active_id[0] = definition.id
            heartbeat()
            started_at = _utc(now())
            _start_migration(datastore, definition, run_id, started_at)
            try:
                result = definition.runner(context)
                if result.get("id") != definition.id:
                    raise ValueError(
                        f"migration runner returned {result.get('id')!r}; expected {definition.id!r}"
                    )
            except MigrationLeaseLost:
                raise
            except Exception as error:
                result = _result(definition.id, definition.label)
                _append_error(result, "runner", error)
            finished_at = _utc(now())
            attempt = _attempt(definition, result, run_id, started_at, finished_at)
            _finish_migration(datastore, definition, attempt)
            if attempt["status"] == "failed":
                break
        active_id[0] = None
    except MigrationLeaseLost:
        pass
    finally:
        _release_lease(datastore, run_id, _utc(now()))
    return get_migration_status(datastore=datastore, catalog=catalog, now=now)


# @testable true
# @tests tests_unit/test_018b_database_migrations.py::test_fresh_install_baselines_catalog_without_running_steps
# @features database-migrations setup
# @dimensions fresh-install baseline idempotence
def initialize_fresh_install(
    fresh_install,
    *,
    datastore=None,
    catalog=MIGRATION_CATALOG,
    now=None,
):
    """Baseline bundled migrations only when startup created a new database."""

    if not fresh_install:
        return False
    catalog = validate_catalog(catalog)
    datastore = datastore or DATA.datastore
    completed_at = _utc((now or (lambda: datetime.now(timezone.utc)))())
    for definition in catalog:
        key = _migration_key(datastore, definition.id)
        with _transaction(datastore) as transaction:
            record = _transaction_get(datastore, key, transaction)
            if record:
                continue
            record = _status_entity(datastore, definition)
            _set_identity(record, definition)
            record.update(
                {
                    "state": "complete",
                    "attempts": "[]",
                    "completion_source": "fresh-install",
                    "completed_at": _iso(completed_at),
                    "completed_version": getattr(CONFIG, "VERSION", None),
                    "completed_build_id": getattr(CONFIG, "BUILD_ID", None),
                }
            )
            _transaction_put(datastore, transaction, record)
    return True


__all__ = [
    "MIGRATION_CATALOG",
    "MigrationChange",
    "MigrationContext",
    "MigrationDataError",
    "MigrationDefinition",
    "canonicalize_form_schema_record",
    "get_migration_status",
    "initialize_fresh_install",
    "run_data_migrations",
    "scan_kind",
    "validate_catalog",
]
