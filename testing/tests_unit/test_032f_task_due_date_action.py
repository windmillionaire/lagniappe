"""Reviewed due-date updates keep task state intact across retry and undo."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai.reporting.execution import runner, undo
from lagniappe.core.tools.ai.reporting.execution.actions import base
from lagniappe.core.tools.ai.reporting.execution.actions.task_dates import _due_date_state
from lagniappe.core.tools.ai.reporting.proposals.validation import validate_proposal
from lagniappe.core.tools.ai.reporting.schedules import apply_task_schedule, validate_task_due_date
from lagniappe.core.tools.dates import user_timezone
from testing.utility.ai_report_fakes import _patch_fake_keys, _recovery_store, _test_user
from testing.utility.test_entities import TestEntities


def _proposal(value):
    return {
        "summary": "Change the task due date", "confidence": 1,
        "actions": [{"id": "due", "type": "set_task_due_date",
                     "data": {"task": "calendar-task", "due_date": value}}],
    }


def _case(monkeypatch, value, recurring=False):
    _patch_fake_keys(monkeypatch)
    actor = _test_user("calendar-owner")
    actor.db["timezone"] = "America/Los_Angeles"
    task = TestEntities.get("TASK", {"name": "Calendar Task", "hash": "calendar-task"})
    task.page = actor.page
    task.description = "Keep the description"
    task.submission = {"textarea-notes": "Keep these notes"}
    task.assigned_to = actor
    task.due_date = datetime(2026, 9, 1, 15, tzinfo=timezone.utc)
    task.db["postponed_from"] = datetime(2026, 8, 30, 15, tzinfo=timezone.utc)
    if recurring:
        apply_task_schedule(task, {"kind": "recurring", "interval": 2, "unit": "week"})
    report = TestEntities.get("REPORT", {
        "name": "Due date review", "hash": "calendar-report", "parent": actor,
        "user": actor, "tool": "organize", "origin": "api", "status": "ready",
        "proposal": _proposal(value),
    })
    report.origin = "api"
    _stored, saves = _recovery_store(monkeypatch, task, actor.page)
    return actor, task, report, saves


# @source lagniappe/core/tools/ai/external_api.py::submission_validation_errors
# @source lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @matrix agent-api : schema field-path external-schema proposal-contract
# @matrix ai-report task-scheduling : due-date validation
@pytest.mark.unit
@pytest.mark.parametrize("value,valid", [
    (None, True), ("2026-09-12", True), ("2028-02-29", True),
    ("2026-02-29", False), ("2026-13-01", False), ("tomorrow", False),
    ("", False), (False, False), ("20260912", False), ("2026-9-12", False),
    ("2026-09-12T00:00:00Z", False),
])
def test_due_date_contract_validates_calendar_dates(value, valid):
    actor = _test_user("due-contract-owner")
    report = SimpleNamespace(tool="organize", origin="api", input_files=[])
    proposal = _proposal(value)
    errors = external_api.submission_validation_errors(
        {"contract_version": external_api.CONTRACT_VERSION, "proposal": proposal},
        report, actor,
    )
    if valid:
        assert errors == []
        assert validate_task_due_date(value) == value
        assert validate_proposal(proposal)["actions"][0]["data"]["due_date"] == value
    else:
        assert errors and errors[0]["path"] == "$.proposal.actions[0].data.due_date"
        with pytest.raises(exceptions.AIException, match="YYYY-MM-DD"):
            validate_proposal(proposal)


# @source lagniappe/core/tools/ai/external_api.py::submission_validation_errors
# @source lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @matrix agent-api : schema field-path
# @matrix ai-report : canonical-target validation
@pytest.mark.unit
@pytest.mark.parametrize("data", [
    {"task": "calendar-task"}, {"due_date": None},
    {"task_action": "create-task", "due_date": "2026-09-12"},
    {"task": "calendar-task", "due_date": None, "schedule": {}},
])
def test_due_date_action_requires_exact_task_and_explicit_value(data):
    actor = _test_user("due-shape-owner")
    proposal = _proposal(None)
    proposal["actions"][0]["data"] = data
    assert external_api.submission_validation_errors(
        {"contract_version": external_api.CONTRACT_VERSION, "proposal": proposal},
        SimpleNamespace(tool="organize", origin="api", input_files=[]), actor,
    )
    with pytest.raises(exceptions.AIException):
        validate_proposal(proposal)


# @source lagniappe/core/tools/ai/reporting/execution/actions/recovery.py::_inspect_action_applied
# @source lagniappe/core/tools/ai/reporting/execution/actions/checkpoints.py::_record_action_result
# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @matrix ai-report task-scheduling : due-date preservation recovery undo
@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "2026-09-20", "2026-09-01"])
@pytest.mark.parametrize("recurring", [False, True])
def test_due_date_action_sets_clears_retries_and_undoes(monkeypatch, value, recurring):
    actor, task, report, saves = _case(monkeypatch, value, recurring)
    before = _due_date_state(task)
    schedule = deepcopy(task.properties.schedule.value)
    original_execute = base._execute_action
    calls = []

    def execute(action, *args, **kwargs):
        calls.append(action["id"])
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(base, "_execute_action", execute)
    result = runner.run_report(report, actor)
    assert result["status"] == "complete", str(result)
    assert result["actions"][0]["status"] == "complete", str(result)
    assert result["actions"][0]["due_date_state"] == _due_date_state(task)
    assert (task.due_date.astimezone(user_timezone(actor)).date().isoformat()
            if task.due_date else None) == value
    assert task.due_date is None or task.due_date.tzinfo == timezone.utc
    if value == "2026-09-01":
        assert _due_date_state(task) == before
        assert not any(task in batch for batch in saves)
    assert task.properties.schedule.value == schedule
    assert task.submission == {"textarea-notes": "Keep these notes"}
    assert task.description == "Keep the description"
    assert task.assigned_to is actor.page
    assert task.postponed_from == datetime(2026, 8, 30, 15, tzinfo=timezone.utc)
    assert not task.completed
    changed = task.due_date
    assert runner.run_report(report, actor)["status"] == "complete"
    assert calls == ["due"] and task.due_date == changed
    assert undo.undo_report(report, actor)["status"] == "complete"
    assert _due_date_state(task) == before
    with pytest.raises(exceptions.ValidationError, match="already been undone"):
        undo.undo_report(report, actor)
    assert _due_date_state(task) == before


# @matrix ai-report task-scheduling : due-date preservation permissions
@pytest.mark.unit
@pytest.mark.parametrize("denied", [True, False])
def test_due_date_action_rejects_uneditable_or_completed_tasks(monkeypatch, denied):
    actor, task, report, _saves = _case(monkeypatch, "2026-09-20")
    if denied:
        task.allowed = lambda *_args, **_kwargs: False
    else:
        task.completed = True
    before = _due_date_state(task)
    result = runner.run_report(report, actor)
    assert result["actions"][0]["status"] != "complete"
    assert ("permission" if denied else "Reopen") in result["actions"][0]["error"]
    assert _due_date_state(task) == before


# @matrix ai-report task-scheduling : due-date preservation recovery undo drift
@pytest.mark.unit
@pytest.mark.parametrize("change", ["due_date", "schedule", "completed"])
def test_due_date_undo_rejects_newer_scheduling_changes(monkeypatch, change):
    actor, task, report, _saves = _case(monkeypatch, "2026-09-20")
    assert runner.run_report(report, actor)["status"] == "complete"
    if change == "due_date":
        task.due_date = datetime(2026, 9, 25, 15, tzinfo=timezone.utc)
    elif change == "schedule":
        apply_task_schedule(task, {"kind": "recurring", "interval": 1, "unit": "month"})
    else:
        task.completed = True
    before_undo = _due_date_state(task)
    assert undo.undo_report(report, actor)["status"] == "failed"
    assert _due_date_state(task) == before_undo


# @matrix ai-report : due-date proposal
@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "2026-09-20"])
def test_due_date_proposal_displays_setting_and_clearing(value):
    actor = _test_user("due-display-owner")
    proposal = _proposal(value)
    proposal["actions"][0]["data"]["task"] = {"name": "Calendar Task"}
    report = TestEntities.get("REPORT", {
        "name": "Due date display", "parent": actor, "user": actor, "proposal": proposal,
    })
    action = report.properties.proposal.display_actions[0]
    assert "Set Task Due Date" in action["display_label"]
    assert {"label": "Due Date", "value": value or "Clear due date", "kind": "default"} in action["details"]


# @source lagniappe/core/tools/ai/external_api.py::plan_contract
# @source lagniappe/core/tools/ai/external_api.py::submit_plan
# @source lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @matrix agent-api ai-report : proposal-contract proposal-validation ready-state
@pytest.mark.unit
def test_remote_due_date_plan_submits_without_changing_task(monkeypatch):
    actor, task, report, _saves = _case(monkeypatch, "2026-09-20")
    before = task.due_date
    task.db["hash"] = "datetask0001"
    report.status = "draft"
    monkeypatch.setattr(external_api.cache, "get_details_by_hash", lambda hashes: {
        "datetask0001": {"id": task.urlsafe_key, "name": task.name, "kind": "task"}
    })
    monkeypatch.setattr(external_api.Entities, "fetch", lambda *ids, request: [task])
    proposal = _proposal("2026-09-20")
    proposal["actions"][0]["data"]["task"] = "hash:datetask0001"
    contract = external_api.plan_contract(
        report, actor, submit_url="https://example.test/submit",
        actions=["set_task_due_date"], view="schema",
    )
    assert set(contract["proposal_schema"]["$defs"]) == {"set_task_due_date"}
    external_api.submit_plan(report, actor, proposal,
                             contract_version=contract["contract_version"])
    assert report.status == "ready"
    assert task.due_date == before
    assert report.proposal["actions"][0]["data"] == {
        "task": task.urlsafe_key, "due_date": "2026-09-20",
    }
