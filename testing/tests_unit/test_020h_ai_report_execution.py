"""Focused AI-report characterization coverage."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.entities import entity as entity_module
from lagniappe.core.tools.ai.reporting.contracts import actions as report_contracts
from lagniappe.core.tools.ai.reporting.execution import ledger as report_ledger
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from lagniappe.core.tools.ai.reporting.execution import undo as report_undo
from lagniappe.core.tools.ai.reporting.execution.actions import (
    base as report_action_lifecycle,
)
from lagniappe.core.tools.ai.reporting.execution.actions.registry import (
    REPORT_ACTION_ADAPTERS,
)
from testing.utility.ai_report_fakes import (
    _attach_report_process,
    _fetch_one_from,
    _patch_fake_keys,
    _recovery_store,
    _test_file,
    _test_user,
)
from testing.utility.test_entities import TestEntities

# @matrix ai-report : action-registry contract
@pytest.mark.unit
def test_report_action_registry_matches_proposal_contracts():
    adapters = REPORT_ACTION_ADAPTERS

    assert set(adapters) == set(report_contracts.REPORT_ACTION_DATA_CONTRACTS)
    assert set(adapters) == set(report_contracts.ALLOWED_ACTIONS)
    assert all(action_type == adapter.action_type for action_type, adapter in adapters.items())




# @matrix ai-report : cancellation deterministic-run
@pytest.mark.unit
def test_run_report_checks_deferred_execution_guard(monkeypatch):
    report = _attach_report_process(SimpleNamespace(
        urlsafe_key="guarded-report",
        proposal={"summary": "No changes", "actions": []},
        result=None,
        status="ready",
        pending=False,
        error=None,
    ))
    checks = []
    saved = []
    monkeypatch.setattr(
        report_runner,
        "validate_proposal",
        lambda proposal, **_kwargs: proposal,
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    result = report_runner.run_report(
        report,
        SimpleNamespace(),
        ensure_active=lambda: checks.append("active"),
    )

    assert result["status"] == "complete"
    assert report.status == "complete"
    assert len(checks) == 3
    assert saved == [(report,), (report,)]




# @matrix ai-report : cancellation deterministic-run
@pytest.mark.unit
def test_run_report_propagates_deferred_control_stop(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.errors import DeferredJobDeadlineError

    report = _attach_report_process(SimpleNamespace(
        urlsafe_key="interrupted-report",
        proposal={
            "summary": "One guarded change",
            "actions": [{"id": "guarded", "type": "skip"}],
        },
        result=None,
        status="ready",
        pending=False,
        error=None,
    ))
    saved = []
    checks = []
    adapter = SimpleNamespace(prepare=lambda *_args: None)
    monkeypatch.setattr(
        report_runner,
        "validate_proposal",
        lambda proposal, **_kwargs: proposal,
    )
    monkeypatch.setitem(REPORT_ACTION_ADAPTERS, "skip", adapter)
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )

    def ensure_active():
        checks.append("active")
        if len(checks) == 4:
            raise DeferredJobDeadlineError("execution attempt stopped")

    with pytest.raises(
        DeferredJobDeadlineError,
        match="execution attempt stopped",
    ):
        report_runner.run_report(
            report,
            SimpleNamespace(),
            ensure_active=ensure_active,
        )

    assert report.status == "running"
    assert report.result["status"] == "running"
    assert report.result["actions"][0]["status"] == "pending"
    assert saved == [(report,)]




# @matrix ai-report : completed-prefix create deterministic-run idempotency recovery
@pytest.mark.unit
def test_run_report_retry_resumes_after_completed_create_without_duplicate(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-create-recovery-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Create recovery report",
            "hash": "create-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Create two projects.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "first_project",
                        "type": "create_project",
                        "data": {"name": "First Project"},
                    },
                    {
                        "id": "second_project",
                        "type": "create_project",
                        "data": {"name": "Second Project"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch)
    original_execute = report_action_lifecycle._execute_action
    calls = []
    failed = {"value": False}

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "second_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("injected interruption")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)

    first = report_runner.run_report(report, user)

    assert first["status"] == "failed"
    assert [record["status"] for record in first["actions"]] == [
        "complete",
        "failed",
    ]
    assert all(record.get("idempotency_key") for record in first["actions"])
    first_key = first["actions"][0]["entity"]["id"]
    assert first_key in stored

    recovered = report_runner.run_report(report, user)

    assert recovered["status"] == "complete"
    assert [record["status"] for record in recovered["actions"]] == [
        "complete",
        "complete",
    ]
    assert calls == ["first_project", "second_project", "second_project"]
    assert recovered["actions"][0]["entity"]["id"] == first_key
    assert len(
        [entity for entity in stored.values() if entity.entity_kind == "project"]
    ) == 2




# @matrix ai-report : completed-prefix deterministic-run permissions recovery
@pytest.mark.unit
def test_run_report_retry_stops_when_completed_prefix_permission_is_revoked(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-recovery-permission-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Permission recovery report",
            "hash": "permission-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Create two projects.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "first_project",
                        "type": "create_project",
                        "data": {"name": "First Project"},
                    },
                    {
                        "id": "second_project",
                        "type": "create_project",
                        "data": {"name": "Second Project"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch)
    original_execute = report_action_lifecycle._execute_action
    calls = []

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "second_project":
            raise RuntimeError("injected interruption")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)
    first = report_runner.run_report(report, user)
    project = stored[first["actions"][0]["entity"]["id"]]
    monkeypatch.setattr(
        type(project),
        "allowed",
        lambda self, action, user=None: False,
    )

    recovered = report_runner.run_report(report, user)

    assert recovered["status"] == "failed"
    assert recovered["actions"][0]["status"] == "failed"
    assert "state has changed" in recovered["actions"][0]["error"]
    assert calls == ["first_project", "second_project"]




# @matrix ai-report : deterministic-run idempotency post-commit-checkpoint recovery
@pytest.mark.unit
def test_run_report_reconciles_applying_create_when_output_already_exists(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-applying-recovery-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Applying recovery report",
            "hash": "applying-recovery-report",
            "parent": user,
            "user": user,
            "status": "failed",
            "proposal": {
                "summary": "Create one project.",
                "confidence": 1,
                "issues": [],
                "actions": [
                    {
                        "id": "project",
                        "type": "create_project",
                        "data": {"name": "Recovered Project"},
                    }
                ],
            },
        },
    )
    fingerprint = report_ledger.proposal_fingerprint(report.proposal)
    ledger = report_ledger._new_report_ledger(report, report.proposal, fingerprint)
    output_key = entity_module.database_utility.create_key("project", None)
    output_id = entity_module.database_get.urlsafe_key(output_key)
    project = TestEntities.get(
        "PROJECT", {"name": "Recovered Project", "hash": "recovered-project"}
    )
    project.db["hash"] = output_id
    ledger["status"] = "failed"
    ledger["actions"][0].update(
        {
            "prepared": True,
            "status": "applying",
            "attempts": 1,
            "output_key": output_id,
        }
    )
    report.result = ledger
    stored, _saves = _recovery_store(monkeypatch, project)
    monkeypatch.setattr(
        report_action_lifecycle,
        "_execute_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reconciled action should not execute again")
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "complete"
    assert result["actions"][0]["entity"]["id"] == output_id
    assert list(stored) == [output_id]




# @matrix ai-report : batch-field-patch completed-prefix deterministic-run moves recovery
@pytest.mark.parametrize("first_action", ["move", "update"])
@pytest.mark.unit
def test_run_report_retry_validates_completed_move_and_update_prefix(
    monkeypatch,
    first_action,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user(f"report-{first_action}-recovery-owner")
    old_category = TestEntities.get(
        "CATEGORY", {"name": "Old", "hash": f"{first_action}-old-category"}
    )
    new_category = TestEntities.get(
        "CATEGORY", {"name": "New", "hash": f"{first_action}-new-category"}
    )
    page = TestEntities.get(
        "PAGE", {"name": "Recovery Page", "hash": f"{first_action}-page"}
    )
    page.model = old_category
    form = TestEntities.get(
        "FORM", {"name": "Recovery Form", "hash": f"{first_action}-form"}
    )
    form.form_type = "page"
    form.schema = [
        {
            "id": "input-state",
            "type": "input",
            "input": "text",
            "title": "State",
        }
    ]
    page.form = form
    page.properties.submission.value = {"input-state": "old"}
    action = (
        {
            "id": "move_page",
            "type": "move_page",
            "data": {
                "page": page.urlsafe_key,
                "category": new_category.urlsafe_key,
            },
        }
        if first_action == "move"
        else {
            "id": "update_page",
            "type": "update_submission_fields",
            "data": {
                "updates": [
                    {
                        "page": page.urlsafe_key,
                        "schema_id": "input-state",
                        "new_value": "new",
                    }
                ]
            },
        }
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": f"{first_action.title()} recovery report",
            "hash": f"{first_action}-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Apply one mutation, then create a project.",
                "confidence": 1,
                "actions": [
                    action,
                    {
                        "id": "finish_project",
                        "type": "create_project",
                        "data": {"name": "Finish Recovery"},
                    },
                ],
            },
        },
    )
    _stored, _saves = _recovery_store(
        monkeypatch,
        old_category,
        new_category,
        page,
        form,
    )
    original_execute = report_action_lifecycle._execute_action
    calls = []
    failed = {"value": False}

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "finish_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("injected second-action failure")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)

    assert report_runner.run_report(report, user)["status"] == "failed"
    assert report_runner.run_report(report, user)["status"] == "complete"

    assert calls == [action["id"], "finish_project", "finish_project"]
    if first_action == "move":
        assert page.model is None
        assert page.categories == [new_category]
    else:
        assert page.submission == {"input-state": "new"}




# @matrix ai-report : compensation deterministic-run failed-prefix idempotency
@pytest.mark.unit
def test_undo_report_compensates_completed_prefix_of_failed_report(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-prefix-undo-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Prefix undo report",
            "hash": "prefix-undo-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Create projects with an interruption.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "kept_project",
                        "type": "create_project",
                        "data": {"name": "Temporary Project"},
                    },
                    {
                        "id": "failed_project",
                        "type": "create_project",
                        "data": {"name": "Never Created"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch)
    original_execute = report_action_lifecycle._execute_action

    def interrupted(action, *args, **kwargs):
        if action["id"] == "failed_project":
            raise RuntimeError("stop after prefix")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)
    deleted = []

    def delete(*entities):
        for entity in entities:
            deleted.append(entity)
            stored.pop(entity.urlsafe_key, None)

    monkeypatch.setattr(report_runner.Entities, "delete", delete)

    result = report_runner.run_report(report, user)
    created_id = result["actions"][0]["entity"]["id"]
    assert result["status"] == "failed"
    assert created_id in stored

    undo = report_undo.undo_report(report, user)

    assert undo["status"] == "complete"
    assert created_id not in stored
    assert len(deleted) == 1
    assert report.result["status"] == "undone"
    with pytest.raises(exceptions.ValidationError, match="already been undone"):
        report_undo.undo_report(report, user)


# @matrix agent-api ai-report : browser-review cas compensation delete undo
@pytest.mark.unit
def test_undo_report_stops_before_compensation_when_initial_save_is_rejected(
    monkeypatch,
):
    report = SimpleNamespace(
        status="complete",
        pending=False,
        error=None,
        result={
            "ledger_version": report_ledger.REPORT_LEDGER_VERSION,
            "status": "complete",
            "actions": [
                {
                    "id": "deleted-report-action",
                    "type": "skip",
                    "status": "complete",
                }
            ],
        },
    )

    class Process:
        def begin_undo(self, result):
            report.status = "undoing"
            report.pending = True
            report.error = None
            report.result = result

    report.properties = SimpleNamespace(process=Process())
    compensation_calls = []
    monkeypatch.setitem(
        REPORT_ACTION_ADAPTERS,
        "skip",
        SimpleNamespace(
            compensate=lambda *_args: compensation_calls.append(_args),
        ),
    )
    monkeypatch.setattr(
        report_undo.Entities,
        "save",
        lambda *_args: pytest.fail(
            "A rejected guarded undo fell back to an ordinary report upsert"
        ),
    )
    save_calls = []

    def reject_deleted_report(current):
        save_calls.append(current)
        raise exceptions.ValidationError(
            "This plan changed while undo was in progress."
        )

    with pytest.raises(
        exceptions.ValidationError,
        match="plan changed while undo was in progress",
    ):
        report_undo.undo_report(
            report,
            SimpleNamespace(),
            save=reject_deleted_report,
        )

    assert save_calls == [report]
    assert compensation_calls == []
    assert report.status == "undoing"
    assert report.result["undo"]["actions"][0]["status"] == "pending"




# @matrix ai-report : compensation completed-task deterministic-run recovery reuse
@pytest.mark.unit
def test_completed_task_retry_and_undo_restore_reused_task(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("report-completed-task-recovery-owner")
    page = TestEntities.get(
        "PAGE", {"name": "Vehicle", "hash": "completed-task-recovery-page"}
    )
    task = TestEntities.get(
        "TASK",
        {
            "name": "Registration",
            "description": "Before report",
            "hash": "completed-task-recovery-task",
        },
    )
    task.page = page
    task.description = "Before report"
    task.completed = False
    task.submission = {"status": "pending"}
    page._tasks = [task]
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Completed task recovery report",
            "hash": "completed-task-recovery-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "proposal": {
                "summary": "Record completion, then create a project.",
                "confidence": 1,
                "actions": [
                    {
                        "id": "registration_completion",
                        "type": "create_task",
                        "data": {
                            "page": page.urlsafe_key,
                            "task": task.urlsafe_key,
                            "name": "Registration",
                            "description": "After report",
                            "completed_on": "2026-05-01",
                            "submission": {"status": "complete"},
                        },
                    },
                    {
                        "id": "finish_project",
                        "type": "create_project",
                        "data": {"name": "Recovery Finished"},
                    },
                ],
            },
        },
    )
    stored, _saves = _recovery_store(monkeypatch, page, task)
    original_execute = report_action_lifecycle._execute_action
    calls = []
    failed = {"value": False}

    def interrupted(action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "finish_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("stop after task mutation")
        return original_execute(action, *args, **kwargs)

    monkeypatch.setattr(report_action_lifecycle, "_execute_action", interrupted)

    first = report_runner.run_report(report, user)

    assert first["status"] == "failed"
    assert first["actions"][0]["created"] is False
    assert task.completed is True
    assert task.description == "After report"

    recovered = report_runner.run_report(report, user)

    assert recovered["status"] == "complete"
    assert calls == [
        "registration_completion",
        "finish_project",
        "finish_project",
    ]

    def delete(*entities):
        for entity in entities:
            stored.pop(entity.urlsafe_key, None)

    monkeypatch.setattr(report_runner.Entities, "delete", delete)
    report_undo.undo_report(report, user)

    assert task.completed is False
    assert task.description == "Before report"
    assert task.submission == {"status": "pending"}
    assert report.result["status"] == "undone"




# @matrix ai-report : completed-task-history grouping result
@pytest.mark.unit
def test_grouped_result_actions_groups_page_files_tasks_and_summaries():
    user = _test_user("page-result-owner")
    page = {
        "id": "page-utilities",
        "kind": "page",
        "name": "Utilities",
        "url": "/pages/page-utilities",
    }
    task = {
        "id": "task-backflow",
        "kind": "task",
        "name": "Backflow Inspection",
        "url": "/tasks/task-backflow",
    }
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Page grouped result report",
            "hash": "page-grouped-result-report",
            "parent": user,
            "user": user,
            "result": {
                "status": "complete",
                "actions": [
                    {
                        "id": "attach_plan",
                        "type": "attach_file_to_page",
                        "status": "complete",
                        "entity": {
                            "id": "file-plan",
                            "kind": "file",
                            "name": "Utility Plan",
                        },
                        "target": page,
                        "file_summary": {"present": False, "complete": False},
                    },
                    {
                        "id": "task",
                        "type": "create_task",
                        "status": "complete",
                        "created": True,
                        "entity": task,
                        "page": page,
                        "project": {
                            "id": "project-home",
                            "kind": "project",
                            "name": "Home Remodeling",
                        },
                        "model": {
                            "id": "model-plumbing",
                            "kind": "model",
                            "name": "Plumbing Work",
                        },
                        "form": {
                            "id": "form-plumbing",
                            "kind": "form",
                            "name": "Plumbing Work",
                        },
                        "submission": {"created": True, "field_count": 2},
                        "attachments": [
                            {
                                "entity": {
                                    "id": "file-water",
                                    "kind": "file",
                                    "name": "Water Photo",
                                },
                                "summary": {"present": True, "complete": False},
                            }
                        ],
                    },
                    {
                        "id": "attach_invoice",
                        "type": "attach_file_to_task",
                        "status": "complete",
                        "entity": {
                            "id": "file-invoice",
                            "kind": "file",
                            "name": "Plumbing Invoice",
                        },
                        "target": task,
                        "file_summary": {"present": False, "complete": False},
                    },
                    {
                        "id": "summary_invoice",
                        "type": "summarize_file",
                        "status": "complete",
                        "entity": {
                            "id": "file-invoice",
                            "kind": "file",
                            "name": "Plumbing Invoice",
                        },
                        "file_summary": {"present": True, "complete": True},
                    },
                    {
                        "id": "summary_orphan",
                        "type": "summarize_file",
                        "status": "complete",
                        "entity": {
                            "id": "file-not-attached",
                            "kind": "file",
                            "name": "Loose Summary",
                        },
                        "file_summary": {"present": True, "complete": True},
                    },
                ],
            },
        },
    )

    grouped = report.properties.result.grouped_actions

    assert [action["type"] for action in grouped] == ["page_group", "summarize_file"]
    page_group = grouped[0]
    assert page_group["created"] is False
    assert page_group["entity"]["name"] == "Utilities"
    assert page_group["attachments"][0]["entity"]["name"] == "Utility Plan"
    assert page_group["tasks"][0]["entity"]["name"] == "Backflow Inspection"
    assert page_group["tasks"][0]["submission"] == {"created": True, "field_count": 2}
    assert page_group["tasks"][0]["attachments"][0]["entity"]["name"] == "Water Photo"
    assert page_group["tasks"][0]["attachments"][1]["entity"]["name"] == (
        "Plumbing Invoice"
    )
    assert page_group["tasks"][0]["attachments"][1]["file_summary"] == {
        "present": True,
        "complete": True,
    }
    assert grouped[1]["entity"]["name"] == "Loose Summary"




# @matrix ai-report : completed-task-history grouping result
@pytest.mark.unit
def test_grouped_result_actions_groups_completed_task_history_under_created_task():
    user = _test_user("history-result-owner")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "History result report",
            "hash": "history-result-report",
            "parent": user,
            "user": user,
            "result": {
                "status": "complete",
                "actions": [
                    {
                        "id": "task",
                        "type": "create_task",
                        "status": "complete",
                        "entity": {
                            "id": "task-new",
                            "kind": "task",
                            "name": "Registration",
                        },
                    },
                    {
                        "id": "history",
                        "type": "create_task",
                        "status": "complete",
                        "entity": {
                            "id": "history-new",
                            "kind": "task_history",
                            "name": "Task history",
                        },
                        "target": {
                            "id": "task-new",
                            "kind": "task",
                            "name": "Registration",
                        },
                        "attachments": [
                            {
                                "entity": {
                                    "id": "file-one",
                                    "kind": "file",
                                    "name": "Registration receipt",
                                }
                            }
                        ],
                    },
                ],
            },
        },
    )

    grouped = report.properties.result.grouped_actions

    assert len(grouped) == 1
    assert grouped[0]["type"] == "create_task"
    assert grouped[0]["histories"][0]["type"] == "create_task"
    assert grouped[0]["histories"][0]["attachments"][0]["entity"]["name"] == (
        "Registration receipt"
    )




# @matrix ai-report : created-entities delete-links deterministic-run file-links report-files undo
@pytest.mark.unit
def test_undo_report_deletes_created_entities_and_unlinks_files(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("undo-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    task = TestEntities.get(
        "TASK",
        {"name": "Registration", "hash": "registration-task"},
        page=page,
    )
    file = _test_file("registration.pdf", "application/pdf")
    file.db["pages"] = [page.key]
    history = task.create_history_entry(
        completed_on=datetime(2023, 6, 24, tzinfo=timezone.utc),
        files=[file],
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Undo report",
            "hash": "undo-report",
            "parent": user,
            "user": user,
            "status": "complete",
            "pending": False,
            "input_files": [file],
            "result": {
                "ledger_version": report_ledger.REPORT_LEDGER_VERSION,
                "proposal_fingerprint": "test-ledger",
                "status": "complete",
                "actions": [
                    {
                        "id": "page",
                        "type": "create_page",
                        "status": "complete",
                        "created": True,
                        "entity": {
                            "id": page.urlsafe_key,
                            "kind": "page",
                            "name": "Jeep",
                        },
                    },
                    {
                        "id": "attachment",
                        "type": "attach_file_to_page",
                        "status": "complete",
                        "entity": {
                            "id": file.urlsafe_key,
                            "kind": "file",
                            "name": file.name,
                        },
                        "target": {
                            "id": page.urlsafe_key,
                            "kind": "page",
                            "name": "Jeep",
                        },
                    },
                    {
                        "id": "task",
                        "type": "create_task",
                        "status": "complete",
                        "created": True,
                        "entity": {
                            "id": task.urlsafe_key,
                            "kind": "task",
                            "name": "Registration",
                        },
                    },
                    {
                        "id": "history",
                        "type": "create_task",
                        "status": "complete",
                        "created": True,
                        "entity": {
                            "id": history.urlsafe_key,
                            "kind": "task_history",
                            "name": "Task history",
                        },
                        "target": {
                            "id": task.urlsafe_key,
                            "kind": "task",
                            "name": "Registration",
                        },
                        "attachments": [
                            {
                                "entity": {
                                    "id": file.urlsafe_key,
                                    "kind": "file",
                                    "name": file.name,
                                }
                            }
                        ],
                    },
                ],
            },
        },
    )
    entities = {
        page.urlsafe_key: page,
        task.urlsafe_key: task,
        history.urlsafe_key: history,
        file.urlsafe_key: file,
    }
    saved = []
    deleted = []

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "delete",
        lambda *entities: deleted.extend(entities),
    )

    undo = report_undo.undo_report(report, user)

    assert undo["status"] == "complete"
    assert report.status == "ready"
    assert report.pending is False
    assert report.result["status"] == "undone"
    assert report.result["undone"] is True
    assert report.error is None
    assert report.summary is None
    assert history in deleted
    assert task in deleted
    assert page in deleted
    assert file not in deleted
    assert file.db.get("pages") is None
    assert history.key not in file.db.get("tasks", [])
    assert task.key not in file.db.get("tasks", [])
    assert all(action["status"] == "complete" for action in undo["actions"])
