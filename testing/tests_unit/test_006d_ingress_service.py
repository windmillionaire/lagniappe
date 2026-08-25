"""Durable ingress transitions, cursor commits, and progress contracts."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import (
    CONFIGURATION_STAGES,
    INGRESS_TRANSITIONS,
    IngressFormatError,
    IngressMutationPlan,
    IngressStage,
    IngressTransitionError,
)
from lagniappe.core.properties.file_ingress import Stage
from lagniappe.core.tools import ingress as ingress_tools
from lagniappe.core.tools.database import ingress as database_ingress
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit


def _ingress(*, stage="PROCESS_CSV", highest="PROCESS_CSV", rows=None):
    entity = TestEntities.get(
        "INGRESS",
        {"hash": "durable_ingress", "name": "Durable Import"},
    )
    rows = list(rows or [])
    entity.save_asset = lambda content, *_args, **_kwargs: SimpleNamespace(
        get=lambda: content
    )
    entity.properties.rows._asset = rows
    entity.get_process("workflow").update(
        {
            "current": stage,
            "highest_completed": highest,
            "configuration_revision": 3,
            "process_csv": {
                "columns": {"name": {"label": "Name", "type": "string"}},
                "row_count": len(rows),
                "column_count": 1,
                "delimiter": ",",
                "complete": True,
            },
        }
    )
    entity.get_process("execution").update(
        {
            "status": "idle",
            "cursor": 0,
            "total_rows": len(rows),
            "dispatch_sequence": 0,
        }
    )
    return entity


# @pair ingress:transition-contract
def test_transition_table_covers_every_ingress_stage():
    stages = set(CONFIGURATION_STAGES)
    stages.update(
        {
            INGRESS_TRANSITIONS["start"][1],
            INGRESS_TRANSITIONS["finish"][1],
        }
    )
    assert stages == set(IngressStage)
    assert INGRESS_TRANSITIONS["create"] == (None, IngressStage.PROCESS_CSV)


# @matrix ingress : presentation stage
def test_property_stage_facade_uses_durable_workflow():
    entity = _ingress(stage="CHOOSE_TYPE")
    assert isinstance(entity.stage, Stage)
    assert entity.stage.name == "CHOOSE_TYPE"
    entity.properties.stage.value = IngressStage.CHOOSE_PARENT
    assert entity.get_process("workflow")["current"] == "CHOOSE_PARENT"


# @matrix ingress : format-validation invalid-transition
def test_service_rejects_unversioned_records_and_future_navigation():
    entity = _ingress()
    entity.db.pop("ingress_format")
    with pytest.raises(IngressFormatError, match="upload the CSV file again"):
        ingress_tools.IngressService(entity).progress()

    entity.db["ingress_format"] = 1
    service = ingress_tools.IngressService(entity)
    with pytest.raises(IngressTransitionError, match="Cannot navigate"):
        service.navigate(IngressStage.CHOOSE_FORM)


# @matrix ingress : configuration-lock invalidation progress-actions
def test_configuration_change_invalidates_downstream_and_locks_after_start():
    entity = _ingress(
        stage="CHOOSE_TYPE", highest="VERIFY_IMPORT", rows=[{"name": "A"}]
    )
    for stage in CONFIGURATION_STAGES[1:]:
        entity.properties.get(stage.name.lower()).section = {"complete": True}
    service = ingress_tools.IngressService(entity)

    service.update_current({"entity-type": "page"}, save=False)

    assert service.workflow["configuration_revision"] == 4
    assert service.workflow["highest_completed"] == "PROCESS_CSV"
    assert entity.properties.choose_parent.section == {}
    assert entity.properties.completed.section == {}

    service.workflow["current"] = "VERIFY_IMPORT"
    service.workflow["highest_completed"] = "ASSIGN_COLUMNS"
    service.start()
    progress = service.progress().to_dict()
    assert progress["stage"] == "IMPORTING"
    assert progress["run_status"] == "queued"
    assert progress["actions"] == ["stop"]
    with pytest.raises(IngressTransitionError, match="cannot change"):
        service.update_stage(IngressStage.CHOOSE_TYPE, {"entity-type": "task"})


# @matrix ingress : batch cursor duplicate-delivery results terminal
def test_testing_batch_commits_ordered_results_and_finishes(monkeypatch):
    entity = _ingress(
        stage="IMPORTING",
        highest="VERIFY_IMPORT",
        rows=[{"name": "A"}, {"name": "B"}],
    )
    execution = entity.get_process("execution")
    execution.update({"status": "queued", "total_rows": 2})
    service = ingress_tools.IngressService(entity)

    def plan(planner, row):
        result = {
            "row": json.dumps(row),
            "idempotency_key": f"row:{planner.row_index}",
        }
        return IngressMutationPlan(
            planner.row_index,
            result["idempotency_key"],
            result,
        )

    monkeypatch.setattr(ingress_tools.IngressMutationPlanner, "plan", plan)

    first = service.run_batch(limit=1)
    assert first.state == "queued"
    assert first.processed == 1
    assert entity.results == [
        {"row": json.dumps({"name": "A"}), "idempotency_key": "row:0"}
    ]

    second = service.run_batch(limit=1)
    assert second.state == "completed"
    assert second.processed == 2
    assert service.stage == IngressStage.COMPLETED
    assert service.progress().to_dict()["actions"] == ["delete_imported"]

    duplicate = service.run_batch(limit=1)
    assert duplicate.state == "completed"
    assert duplicate.results == ()


# @matrix ingress : cursor-resume failure restart
def test_failed_batch_restarts_from_committed_cursor(monkeypatch):
    entity = _ingress(
        stage="IMPORTING",
        highest="VERIFY_IMPORT",
        rows=[{"name": "A"}, {"name": "B"}],
    )
    entity.get_process("execution").update(
        {"status": "queued", "cursor": 1, "total_rows": 2}
    )
    entity.properties.results._asset = [{"row": "A"}]
    service = ingress_tools.IngressService(entity)

    monkeypatch.setattr(
        ingress_tools.IngressMutationPlanner,
        "plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("storage down")),
    )
    monkeypatch.setattr(
        ingress_tools.exceptions, "capture", lambda *_args, **_kwargs: None
    )

    with pytest.raises(RuntimeError, match="storage down"):
        service.run_batch(limit=1)
    assert service.run_status == "failed"
    assert service.cursor == 1

    service.restart()
    assert service.run_status == "queued"
    assert service.cursor == 1


# @matrix ingress : deterministic-key idempotency row-task
def test_mutation_planner_preallocates_stable_entity_and_history_keys():
    created = []

    class Entity:
        entity_kind = None

        def __init__(self, key):
            self.key = key
            self.completed = None
            self.updated = None

        def update(self, data):
            self.updated = data

    class Factory:
        def __init__(self, kind):
            self.kind = kind

        def __call__(self, key):
            entity = Entity(key)
            entity.entity_kind = self.kind
            created.append(entity)
            return entity

    service = SimpleNamespace(
        entity_key=lambda kind, role: f"{kind}:{role}",
        idempotency_key=lambda role: f"ingress:{role}",
    )
    source = SimpleNamespace()
    first = ingress_tools.IngressMutationPlanner(source, row_index=4, service=service)
    first.Entities = SimpleNamespace(PAGE=Factory("page"), TASK=Factory("task"))
    page = first._new_page({"name": "Ada"})
    task = first._new_task({"name": "Follow Up"})
    history_key = first._history_key("completion")

    second = ingress_tools.IngressMutationPlanner(source, row_index=4, service=service)
    second.Entities = first.Entities
    next_row = ingress_tools.IngressMutationPlanner(
        source, row_index=5, service=service
    )
    next_row.Entities = first.Entities
    next_task = next_row._new_task({"name": "Follow Up"})

    assert page.key == second._deterministic_key("page", "entity")
    assert task.key == second._deterministic_key("task", "entity")
    assert task.key != next_task.key
    assert history_key == second._history_key("completion")
    assert page.updated == {"name": "Ada"}
    assert task.updated == {"name": "Follow Up"}


class FakeMutation:
    def __init__(self, entity):
        self.upsert = entity
        self._update = None
        self.property_mask = SimpleNamespace(paths=[])

    @property
    def update(self):
        return self._update

    @update.setter
    def update(self, entity):
        self._update = entity
        self.upsert = None


class FakeTransaction:
    def __init__(self, entity):
        self.entity = entity
        self.saved = []
        self.mutations = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def put(self, entity):
        self.saved.append(entity)
        self.mutations.append(FakeMutation(entity))
        if entity.get("type") == "ingress":
            self.entity = entity


class FakeDatastore:
    def __init__(self, entity):
        self.transaction_instance = FakeTransaction(entity)

    def transaction(self):
        return self.transaction_instance

    def get(self, _key, transaction=None):
        assert transaction is self.transaction_instance
        return self.transaction_instance.entity


def _database(monkeypatch, execution):
    entity = {
        "type": "ingress",
        "ingress_format": 1,
        "workflow": json.dumps({"current": "IMPORTING"}),
        "execution": json.dumps(execution),
    }
    datastore = FakeDatastore(entity)
    monkeypatch.setattr(
        database_ingress,
        "DATA",
        SimpleNamespace(datastore=datastore),
    )
    monkeypatch.setattr(database_ingress, "_ingress_key", lambda _value: "ingress")
    monkeypatch.setattr(
        database_ingress,
        "update_site_fingerprints",
        lambda *_entities: [],
    )
    return entity, datastore


# @matrix ingress : cursor duplicate-delivery
def test_ingress_row_commit_rejects_duplicate_cursor(monkeypatch):
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    entity, _datastore = _database(
        monkeypatch,
        {"status": "queued", "cursor": 0},
    )
    candidate = SimpleNamespace(key="ingress", db=dict(entity))
    committed = database_ingress.commit_ingress_row(
        "ingress", 0, candidate, ((candidate, None),), now
    )
    assert committed["committed"] is True
    assert committed["execution"]["cursor"] == 1

    duplicate = SimpleNamespace(key="ingress", db=dict(committed["entity"]))
    rejected = database_ingress.commit_ingress_row(
        "ingress", 0, duplicate, ((duplicate, None),), now
    )
    assert rejected["committed"] is False
    assert rejected["reason"] == "cursor"
    assert rejected["execution"]["cursor"] == 1


# @pair ingress:stop
def test_ingress_stop_is_durable_and_preserves_current_row_boundary(monkeypatch):
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    entity, _datastore = _database(
        monkeypatch,
        {
            "status": "running",
            "cursor": 0,
            "lease_token": "lease-one",
            "lease_expires": "legacy-lease",
        },
    )
    stopped = database_ingress.update_ingress_status("ingress", "stopped", now)
    assert stopped["execution"]["status"] == "stopped"
    assert "lease_token" not in stopped["execution"]
    assert "lease_expires" not in stopped["execution"]

    candidate = SimpleNamespace(key="ingress", db=dict(entity))
    committed = database_ingress.commit_ingress_row(
        "ingress", 0, candidate, ((candidate, None),), now
    )
    assert committed["committed"] is False
    assert committed["reason"] == "state"
    assert committed["execution"]["cursor"] == 0


# @matrix ingress : compare-and-set cursor durable-commit property-mask
def test_ingress_row_commit_requires_expected_cursor_and_applies_masks(monkeypatch):
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    entity, datastore = _database(
        monkeypatch,
        {"status": "queued", "cursor": 2},
    )
    candidate = SimpleNamespace(key="ingress", db=dict(entity))
    dependent = SimpleNamespace(
        key="category",
        db={"type": "category", "modified": now},
    )
    rejected = database_ingress.commit_ingress_row(
        "ingress", 1, candidate, ((candidate, None),), now
    )
    assert rejected["committed"] is False
    assert rejected["reason"] == "cursor"

    committed = database_ingress.commit_ingress_row(
        "ingress",
        2,
        candidate,
        ((candidate, None), (dependent, ("modified",))),
        now,
    )
    assert committed["committed"] is True
    assert committed["execution"]["cursor"] == 3
    mutation = datastore.transaction_instance.mutations[0]
    assert mutation.upsert is None
    assert mutation.update is dependent.db
    assert mutation.property_mask.paths == ["modified"]


# @matrix ingress : compare-and-set cursor failure status stop
def test_ingress_status_update_is_cursor_checked(monkeypatch):
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    _entity, _datastore = _database(
        monkeypatch,
        {"status": "queued", "cursor": 1},
    )
    stale = database_ingress.update_ingress_status(
        "ingress",
        "failed",
        now,
        expected_cursor=0,
        error="failed",
    )
    assert stale["updated"] is False
    assert stale["reason"] == "cursor"

    updated = database_ingress.update_ingress_status(
        "ingress",
        "failed",
        now,
        expected_cursor=1,
        error="failed",
    )
    assert updated["updated"] is True
    assert updated["execution"]["status"] == "failed"
    assert updated["execution"]["cursor"] == 1
    assert updated["execution"]["error"] == "failed"
