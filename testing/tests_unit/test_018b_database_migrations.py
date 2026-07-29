from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from google.cloud.datastore import Entity, Key
import pytest

from lagniappe.core.tools.database import migrations, utility


pytestmark = pytest.mark.unit


def _key(kind, identifier):
    return Key(kind, identifier, project="migration-test")


def _entity(kind, identifier, data):
    entity = Entity(key=_key(kind, identifier))
    entity.update(data)
    return entity


class _Clock:
    def __init__(self):
        self.value = datetime(2026, 7, 14, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds=1):
        self.value += timedelta(seconds=seconds)
        return self.value


class _Transaction:
    def __init__(self, datastore):
        self.datastore = datastore

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def put(self, entity):
        self.datastore.put(entity)


class _Datastore:
    def __init__(self, rows=()):
        self.rows = {row.key: row for row in rows}
        self.records = {}
        self.write_sizes = []

    def key(self, kind, identifier):
        return _key(kind, identifier)

    def get(self, key, transaction=None):
        return self.records.get(key) or self.rows.get(key)

    def get_multi(self, keys, missing=None):
        records = [self.get(key) for key in keys]
        if missing is not None:
            missing.extend(key for key, record in zip(keys, records) if record is None)
        return [record for record in records if record is not None]

    def entity(self, *, key, exclude_from_indexes=()):
        return Entity(key=key, exclude_from_indexes=exclude_from_indexes)

    def put(self, entity):
        self.records[entity.key] = entity

    def transaction(self):
        return _Transaction(self)

    def write(self, *entities):
        self.write_sizes.append(len(entities))
        for entity in entities:
            self.rows[entity.key] = entity

    def query_factory(self, kind):
        datastore = self
        kind_name = getattr(kind, "value", kind)

        class _Query:
            def fetch_iter(self):
                return iter(
                    row
                    for row in datastore.rows.values()
                    if row.key.kind == kind_name
                )

        return _Query()


class _ContendedTransaction:
    def __init__(self, datastore):
        self.datastore = datastore
        self.pending = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.datastore.attempts += 1
        if self.datastore.attempts <= self.datastore.aborted_attempts:
            raise migrations.google_exceptions.Aborted("transaction contention")
        if self.pending is not None:
            self.datastore.put(self.pending)
        return False

    def put(self, entity):
        self.pending = entity


class _ContendedDatastore(_Datastore):
    def __init__(self, *, aborted_attempts):
        super().__init__()
        self.aborted_attempts = aborted_attempts
        self.attempts = 0

    def transaction(self):
        return _ContendedTransaction(self)


def _result(definition, *, changed=0, repaired=0, skipped=0, failed=0):
    errors = []
    if failed:
        errors.append({"key": "row", "message": "repair required"})
    return {
        "id": definition.id,
        "label": definition.label,
        "examined": changed + skipped + failed,
        "changed": changed,
        "repaired": repaired,
        "skipped": skipped,
        "failed": failed,
        "repairs": [],
        "errors": errors,
    }


def _definition(sequence, migration_id, runner, *, version="1.0", legacy=()):
    return migrations.MigrationDefinition(
        sequence=sequence,
        id=migration_id,
        introduced_in=version,
        label=f"Migration {migration_id}",
        runner=runner,
        legacy_audit_keys=legacy,
    )


# @features database-migrations setup
# @dimensions fresh-install detection reserved-seeding
def test_database_initialize_only_marks_new_content_stores_as_fresh(monkeypatch):
    scenario = {"reserved": False, "content_kind": None}
    initialized = []
    seeded = []

    class StartupDatastore:
        def key(self, kind):
            return _key(kind, "partial")

        def allocate_ids(self, _partial, count):
            return [_key(migrations.KINDS.models.value, f"seed-{index}") for index in range(count)]

        def put_multi(self, entities):
            seeded.append(tuple(entities))

    class StartupQuery:
        def __init__(self, kind):
            self.kind = kind

        def filter(self, _filter):
            return self

        def fetch_all(self):
            return [object()] if scenario["reserved"] else []

        def fetch_one(self):
            return object() if self.kind is scenario["content_kind"] else None

    monkeypatch.setattr(
        utility,
        "DATA",
        SimpleNamespace(
            initialize=lambda: initialized.append(True),
            datastore=StartupDatastore(),
        ),
    )
    monkeypatch.setattr(utility, "Query", StartupQuery)

    assert utility.initialize() is True
    assert len(seeded) == 1

    scenario["content_kind"] = migrations.KINDS.instances
    assert utility.initialize() is False
    assert len(seeded) == 2

    scenario.update(reserved=True, content_kind=None)
    assert utility.initialize() is False
    assert len(seeded) == 2
    assert initialized == [True, True, True]


# @features database migrations
# @dimensions raw-scan copy-on-write chunks failures inactive-rows heartbeat
def test_scan_kind_is_copy_on_write_chunked_and_failure_isolated():
    rows = [
        _entity(
            "instances",
            f"row-{index}",
            {
                "type": "example",
                "active": False,
                "canonical": index == 0,
            },
        )
        for index in range(205)
    ]
    datastore = _Datastore(rows)
    heartbeats = []
    context = migrations.MigrationContext(
        datastore.query_factory,
        datastore.write,
        datastore,
        lambda: heartbeats.append(True),
    )
    result = {
        "id": "TEST-001",
        "label": "Canonical test rows",
        "examined": 0,
        "changed": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    def transform(candidate):
        if candidate.key.name == "row-1":
            candidate["canonical"] = "partial"
            raise migrations.MigrationDataError("repair required")
        if candidate.get("canonical") is True:
            return False
        candidate["canonical"] = True
        return True

    migrations.scan_kind(
        result,
        context,
        "instances",
        lambda row: row.get("type") == "example",
        transform,
    )

    assert result["examined"] == 205
    assert result["changed"] == 203
    assert result["skipped"] == 1
    assert result["failed"] == 1
    assert datastore.rows[_key("instances", "row-1")]["canonical"] is False
    assert datastore.write_sizes == [98, 100, 5]
    assert len(heartbeats) == 3


# @features admin database-migrations
# @dimensions catalog no-op
def test_no_registered_migrations_is_a_noop_success():
    datastore = _Datastore()

    status = migrations.run_data_migrations(datastore=datastore, catalog=())

    assert status == {
        "status": "current",
        "current_version": migrations.CONFIG.VERSION,
        "updates_available": False,
        "cache_refresh_allowed": True,
        "counts": {
            "complete": 0,
            "pending": 0,
            "running": 0,
            "failed": 0,
            "interrupted": 0,
            "blocked": 0,
            "audit_error": 0,
            "total": 0,
        },
        "active_run_id": None,
        "migrations": [],
    }
    assert datastore.records == {}


# @pairs form-schema:canonicalization form-schema:idempotence
# @pair form-schema:history-snapshot
def test_form_schema_transform_is_idempotent_and_preserves_history_membership():
    form = _entity(
        migrations.KINDS.models.value,
        "form-1",
        {
            "type": "form",
            "form_type": "page",
            "schema": json.dumps([{"id": "notes", "type": "textarea"}]),
        },
    )
    history = _entity(
        migrations.KINDS.history.value,
        "history-1",
        {
            "type": "form_history",
            "schema": json.dumps([{"id": "notes", "type": "textarea"}]),
        },
    )

    assert migrations.canonicalize_form_schema_record(form) is True
    assert migrations.canonicalize_form_schema_record(history, snapshot=True) is True
    assert [field["id"] for field in json.loads(form["schema"])] == ["notes"]
    assert [field["id"] for field in json.loads(history["schema"])] == ["notes"]
    assert form["schema_format"] == history["schema_format"] == 1
    assert migrations.canonicalize_form_schema_record(form) is False
    assert migrations.canonicalize_form_schema_record(history, snapshot=True) is False


# @pairs form-schema:legacy-repair form-schema:copy-on-write
def test_form_schema_transform_repairs_invalid_legacy_fields():
    row = _entity(
        migrations.KINDS.models.value,
        "form-legacy",
        {
            "type": "form",
            "schema": json.dumps(
                [
                    {
                        "id": "items",
                        "type": "table",
                        "columns": [
                            {"id": "legacy-notes", "type": "textarea"},
                            {"id": "quantity", "type": "number"},
                        ],
                    }
                ]
            ),
        },
    )
    repairs = []

    assert migrations.canonicalize_form_schema_record(row, repairs=repairs) is True

    columns = json.loads(row["schema"])[0]["columns"]
    assert [column["id"] for column in columns] == ["quantity"]
    assert repairs == [
        "Removed invalid schema data: Schema field 'legacy-notes' has "
        "unsupported type 'textarea'"
    ]


# @pairs form-schema:malformed-data form-schema:copy-on-write
def test_form_schema_transform_rejects_unreadable_rows_without_mutation():
    row = _entity(
        migrations.KINDS.models.value,
        "form-bad",
        {"type": "form", "schema": "not-json"},
    )
    before = dict(row)

    with pytest.raises(migrations.MigrationDataError, match="not valid JSON"):
        migrations.canonicalize_form_schema_record(row)

    assert dict(row) == before


# @pairs migrations:runner migrations:audit
# @pairs form-schema:canonicalization form-schema:history-snapshot
def test_registered_form_schema_migration_scans_forms_and_history():
    rows = [
        _entity(
            migrations.KINDS.models.value,
            "form-1",
            {
                "type": "form",
                "form_type": "task",
                "schema": json.dumps([{"id": "task-notes", "type": "textarea"}]),
            },
        ),
        _entity(
            migrations.KINDS.history.value,
            "history-1",
            {
                "type": "form_history",
                "schema": json.dumps([{"id": "old-notes", "type": "textarea"}]),
            },
        ),
        _entity(
            migrations.KINDS.models.value,
            "legacy-form",
            {
                "type": "form",
                "schema": json.dumps(
                    [
                        {
                            "id": "items",
                            "type": "table",
                            "columns": [
                                {"id": "legacy-notes", "type": "textarea"}
                            ],
                        }
                    ]
                ),
            },
        ),
        _entity(
            migrations.KINDS.models.value,
            "category-1",
            {"type": "category", "name": "Not a form"},
        ),
    ]
    datastore = _Datastore(rows)
    clock = _Clock()

    status = migrations.run_data_migrations(
        query_factory=datastore.query_factory,
        writer=datastore.write,
        datastore=datastore,
        now=clock,
        run_id_factory=lambda: "form-schema-run",
    )

    migration = status["migrations"][0]
    assert status["status"] == "current"
    assert migration["state"] == "complete"
    assert migration["latest_attempt"]["totals"] == {
        "examined": 3,
        "changed": 3,
        "repaired": 1,
        "skipped": 0,
        "failed": 0,
    }
    assert migration["latest_attempt"]["repairs"] == [
        {
            "key": rows[2].key.to_legacy_urlsafe().decode(),
            "message": (
                "Removed invalid schema data: Schema field 'legacy-notes' has "
                "unsupported type 'textarea'"
            ),
            "url": f"/forms/{rows[2].key.to_legacy_urlsafe().decode()}",
            "link_label": "Open form",
        }
    ]


# @pairs migrations:audit form-schema:malformed-data
def test_form_schema_migration_links_unreadable_row_failure_to_form():
    row = _entity(
        migrations.KINDS.models.value,
        "unreadable-form",
        {"type": "form", "schema": "not-json"},
    )
    datastore = _Datastore([row])
    status = migrations.run_data_migrations(
        query_factory=datastore.query_factory,
        writer=datastore.write,
        datastore=datastore,
        now=_Clock(),
        run_id_factory=lambda: "form-schema-failed-run",
    )

    migration = status["migrations"][0]
    assert status["status"] == "failed"
    assert migration["state"] == "failed"
    assert migration["latest_attempt"]["errors"] == [
        {
            "key": row.key.to_legacy_urlsafe().decode(),
            "message": "schema is not valid JSON",
            "url": f"/forms/{row.key.to_legacy_urlsafe().decode()}",
            "link_label": "Open form",
        }
    ]


# @features admin database-migrations
# @dimensions catalog identity order version runner
def test_catalog_rejects_identity_and_order_errors():
    def runner(_context):
        return {}

    valid = _definition(1, "ONE", runner)

    with pytest.raises(ValueError, match="duplicate migration id"):
        migrations.validate_catalog((valid, _definition(2, "ONE", runner)))
    with pytest.raises(ValueError, match="strictly increasing"):
        migrations.validate_catalog((valid, _definition(0, "TWO", runner)))
    with pytest.raises(ValueError, match="introduced version"):
        migrations.validate_catalog(
            (
                migrations.MigrationDefinition(
                    sequence=1,
                    id="BAD",
                    introduced_in="",
                    label="Bad",
                    runner=runner,
                ),
            )
        )


# @features admin database-migrations
# @dimensions ordered-run checkpoint failure resume idempotence
def test_ordered_runner_checkpoints_completion_and_resumes_after_failure():
    datastore = _Datastore()
    clock = _Clock()
    calls = []
    fail_second = [True]

    def runner(migration_id, *, fail=False):
        def run(_context):
            calls.append(migration_id)
            definition = next(item for item in catalog if item.id == migration_id)
            should_fail = fail and fail_second[0]
            return _result(definition, changed=0 if should_fail else 1, failed=int(should_fail))

        return run

    catalog = (
        _definition(1, "ONE", runner("ONE"), version="1.0"),
        _definition(2, "TWO", runner("TWO", fail=True), version="1.1"),
        _definition(3, "THREE", runner("THREE"), version="1.2"),
    )

    first = migrations.run_data_migrations(
        datastore=datastore,
        catalog=catalog,
        now=clock,
        run_id_factory=lambda: "run-1",
    )

    assert first["status"] == "failed"
    assert calls == ["ONE", "TWO"]
    assert [item["state"] for item in first["migrations"]] == [
        "complete",
        "failed",
        "blocked",
    ]

    fail_second[0] = False
    clock.advance()
    second = migrations.run_data_migrations(
        datastore=datastore,
        catalog=catalog,
        now=clock,
        run_id_factory=lambda: "run-2",
    )

    assert second["status"] == "current"
    assert calls == ["ONE", "TWO", "TWO", "THREE"]
    assert [len(item["attempts"]) for item in second["migrations"]] == [1, 2, 1]


# @features admin database-migrations
# @dimensions catalog persistence build-history sticky-completion failure-order
def test_status_reads_completed_migrations_across_builds_and_blocks_after_failure(monkeypatch):
    datastore = _Datastore()
    clock = _Clock()
    calls = []
    definition = None

    def runner(_context):
        calls.append(True)
        return _result(definition, changed=1)

    definition = _definition(1, "PINNED", runner, version="1.5")
    monkeypatch.setattr(migrations.CONFIG, "VERSION", "1.5")
    monkeypatch.setattr(migrations.CONFIG, "BUILD_ID", "build-old")
    migrations.run_data_migrations(
        datastore=datastore,
        catalog=(definition,),
        now=clock,
        run_id_factory=lambda: "old-run",
    )

    monkeypatch.setattr(migrations.CONFIG, "VERSION", "2.0")
    monkeypatch.setattr(migrations.CONFIG, "BUILD_ID", "build-new")
    status = migrations.get_migration_status(
        datastore=datastore,
        catalog=(definition,),
        now=clock,
    )

    assert status["status"] == "current"
    assert status["current_version"] == "2.0"
    assert status["migrations"][0]["completed_version"] == "1.5"
    assert status["migrations"][0]["completed_build_id"] == "build-old"
    migrations.run_data_migrations(datastore=datastore, catalog=(definition,), now=clock)
    assert len(calls) == 1


# @features admin database-migrations
# @dimensions lease lost-lease concurrency stale-recovery interrupted-attempt
def test_runner_rejects_concurrent_lease_and_recovers_interrupted_attempt():
    datastore = _Datastore()
    clock = _Clock()
    calls = []
    definition = None

    def runner(_context):
        calls.append(True)
        return _result(definition, changed=1)

    definition = _definition(1, "LEASED", runner)
    status_key = datastore.key("site", "data-migration:LEASED")
    status_record = datastore.entity(key=status_key, exclude_from_indexes=("attempts",))
    status_record.update(
        {
            "ledger_schema": 1,
            "migration_id": "LEASED",
            "sequence": 1,
            "introduced_in": "1.0",
            "label": definition.label,
            "state": "running",
            "attempts": "[]",
            "active_run_id": "old-run",
            "active_started_at": clock().isoformat(),
            "active_version": "0.9",
            "active_build_id": "old-build",
        }
    )
    datastore.put(status_record)
    control = datastore.entity(key=datastore.key("site", "data-migrations-control"))
    control.update(
        {
            "run_id": "old-run",
            "active_migration_id": "LEASED",
            "lease_expires_at": (clock() + timedelta(seconds=600)).isoformat(),
        }
    )
    datastore.put(control)

    concurrent = migrations.run_data_migrations(
        datastore=datastore,
        catalog=(definition,),
        now=clock,
        run_id_factory=lambda: "new-run",
    )
    assert concurrent["status"] == "running"
    assert calls == []

    clock.advance(601)
    recovered = migrations.run_data_migrations(
        datastore=datastore,
        catalog=(definition,),
        now=clock,
        run_id_factory=lambda: "new-run",
    )
    assert recovered["status"] == "current"
    assert [attempt["status"] for attempt in recovered["migrations"][0]["attempts"]] == [
        "interrupted",
        "complete",
    ]
    assert calls == [True]

    def lose_lease(_context):
        raise migrations.MigrationLeaseLost("lease replaced")

    lost_datastore = _Datastore()
    lost_definition = _definition(1, "LOST", lose_lease)
    lost = migrations.run_data_migrations(
        datastore=lost_datastore,
        catalog=(lost_definition,),
        now=clock,
        run_id_factory=lambda: "lost-run",
    )
    assert lost["status"] == "failed"
    assert lost["migrations"][0]["state"] == "interrupted"


# @features admin database-migrations
# @dimensions legacy-audit read-through normalization
def test_legacy_audit_projects_as_completed():
    datastore = _Datastore()
    clock = _Clock()
    legacy_key = datastore.key("site", "legacy-set")
    legacy = datastore.entity(key=legacy_key, exclude_from_indexes=("runs",))
    legacy["runs"] = json.dumps(
        [
            {
                "run_id": "legacy-run",
                "started_at": clock().isoformat(),
                "finished_at": clock().isoformat(),
                "version": "0.5",
                "build_id": "legacy-build",
                "status": "complete",
                "migrations": [
                    {
                        "id": "LEGACY",
                        "label": "Legacy",
                        "examined": 2,
                        "changed": 1,
                        "skipped": 1,
                        "failed": 0,
                        "errors": [],
                    }
                ],
            }
        ]
    )
    datastore.put(legacy)
    calls = []
    first = None
    second = None

    def first_runner(_context):
        calls.append("legacy")
        return _result(first)

    def second_runner(_context):
        calls.append("new")
        return _result(second, changed=1)

    first = _definition(1, "LEGACY", first_runner, version="0.5", legacy=("legacy-set",))
    second = _definition(2, "NEW", second_runner, version="1.0")
    catalog = (first, second)

    projected = migrations.get_migration_status(
        datastore=datastore,
        catalog=catalog,
        now=clock,
    )
    assert projected["migrations"][0]["state"] == "complete"
    assert projected["migrations"][0]["source"] == "legacy-audit"

    completed = migrations.run_data_migrations(
        datastore=datastore,
        catalog=catalog,
        now=clock,
        run_id_factory=lambda: "new-run",
    )
    assert completed["status"] == "current"
    assert calls == ["new"]
    assert datastore.get(datastore.key("site", "data-migration:LEGACY"))[
        "completion_source"
    ] == "legacy-audit"


# @features admin database-migrations
# @dimensions audit invalid-storage identity
def test_migration_status_rejects_malformed_ledger():
    datastore = _Datastore()
    definition = _definition(1, "BROKEN", lambda _context: None)
    key = datastore.key("site", "data-migration:BROKEN")
    record = datastore.entity(key=key, exclude_from_indexes=("attempts",))
    record.update(
        {
            "ledger_schema": 1,
            "migration_id": "BROKEN",
            "sequence": 99,
            "introduced_in": "1.0",
            "state": "complete",
            "attempts": json.dumps({"not": "a list"}),
        }
    )
    datastore.put(record)

    status = migrations.get_migration_status(
        datastore=datastore,
        catalog=(definition,),
        now=_Clock(),
    )

    assert status["status"] == "audit-error"
    assert status["migrations"][0]["state"] == "audit-error"
    assert "sequence" in status["migrations"][0]["audit_error"]


# @features database-migrations setup
# @dimensions fresh-install baseline idempotence
def test_fresh_install_baselines_catalog_without_running_steps():
    datastore = _Datastore()
    calls = []
    definition = _definition(1, "BASELINE", lambda _context: calls.append(True))
    clock = _Clock()

    assert migrations.initialize_fresh_install(
        False,
        datastore=datastore,
        catalog=(definition,),
        now=clock,
    ) is False
    assert migrations.get_migration_status(
        datastore=datastore,
        catalog=(definition,),
        now=clock,
    )["status"] == "pending"
    assert migrations.initialize_fresh_install(
        True,
        datastore=datastore,
        catalog=(definition,),
        now=clock,
    )
    assert migrations.initialize_fresh_install(
        True,
        datastore=datastore,
        catalog=(definition,),
        now=clock,
    )

    status = migrations.get_migration_status(
        datastore=datastore,
        catalog=(definition,),
        now=clock,
    )
    assert status["status"] == "current"
    assert status["migrations"][0]["source"] == "fresh-install"
    assert status["migrations"][0]["attempts"] == []
    assert calls == []


# @features database-migrations setup
# @dimensions fresh-install transaction-contention retry
def test_fresh_install_retries_transaction_contention(monkeypatch):
    datastore = _ContendedDatastore(aborted_attempts=2)
    definition = _definition(1, "BASELINE", lambda _context: None)
    sleeps = []
    monkeypatch.setattr(migrations.time, "sleep", sleeps.append)

    assert migrations.initialize_fresh_install(
        True,
        datastore=datastore,
        catalog=(definition,),
        now=_Clock(),
    )

    assert datastore.attempts == 3
    assert sleeps == [0.05, 0.1]
    assert migrations.get_migration_status(
        datastore=datastore,
        catalog=(definition,),
        now=_Clock(),
    )["status"] == "current"


# @features admin database-migrations
# @dimensions bounded-history retries
def test_attempt_history_retains_only_the_latest_five_runs():
    datastore = _Datastore()
    clock = _Clock()
    definition = None

    def runner(_context):
        return _result(definition, failed=1)

    definition = _definition(1, "RETRY", runner)
    for index in range(7):
        migrations.run_data_migrations(
            datastore=datastore,
            catalog=(definition,),
            now=clock,
            run_id_factory=lambda index=index: f"run-{index}",
        )
        clock.advance()

    status = migrations.get_migration_status(
        datastore=datastore,
        catalog=(definition,),
        now=clock,
    )
    assert [attempt["run_id"] for attempt in status["migrations"][0]["attempts"]] == [
        "run-2",
        "run-3",
        "run-4",
        "run-5",
        "run-6",
    ]
