"""Focused AI-report characterization coverage."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from lagniappe.core.entities import entity as entity_module
from lagniappe.core.tools.ai.reporting.contracts import actions as report_contracts
from lagniappe.core.tools.ai.reporting.execution import ledger as report_ledger
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from lagniappe.core.tools.ai.reporting.execution.actions.base import ReportActionAdapter
from lagniappe.core.tools.ai.reporting.execution.actions.registry import (
    REPORT_ACTION_ADAPTERS,
)
from testing.utility.ai_report_fakes import (
    _attach_report_process,
    _patch_fake_keys,
    _recovery_store,
    _test_file,
    _test_user,
)
from testing.utility.test_entities import TestEntities


def _completion_case(monkeypatch, *, completed=False, recurring=False):
    _patch_fake_keys(monkeypatch)
    user = _test_user("remote-completion-owner")
    task = TestEntities.get(
        "TASK", {"name": "Review CLI", "hash": "remote-completion-task"}
    )
    task.page = user.page
    task.description = "Keep this description"
    task.form = TestEntities.get("FORM", {
        "name": "Completion notes", "hash": "remote-completion-form", "form_type": "task",
    })
    task.form.schema = [{"id": "notes", "type": "input", "title": "Notes"}]
    task.submission = {"notes": "Keep these values"}
    task.files = [_test_file("kept.pdf")]
    task.assigned_to = user
    task.due_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
    if recurring:
        from lagniappe.core.tools.tasks import scheduling
        from lagniappe.core.tools.ai.reporting.schedules import apply_task_schedule

        monkeypatch.setattr(scheduling, "CONFIG", SimpleNamespace(production=True))
        apply_task_schedule(
            task,
            {
                "kind": "recurring",
                "interval": 1 if recurring == "near" else 30,
                "unit": "day",
            },
        )
    if completed:
        task.complete(user=user)
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Review completion",
            "hash": "remote-completion-report",
            "parent": user,
            "user": user,
            "tool": "organize",
            "origin": "api",
            "status": "ready",
            "proposal": {
                "summary": "Propose completing the CLI task",
                "confidence": 1,
                "actions": [
                    {
                        "id": "complete",
                        "type": "complete_task",
                        "data": {"task": task.urlsafe_key},
                    },
                    {
                        "id": "finish",
                        "type": "needs_review",
                        "data": {
                            "note": "Review follow-up",
                            "questions": ["Anything else?"],
                        },
                    },
                ],
            },
        },
    )
    stored, _ = _recovery_store(monkeypatch, task, user.page, *task.files)
    save = report_runner.Entities.save

    def save_with_histories(*entities):
        save(*entities)
        for entity in entities:
            if isinstance(entity, report_runner.Entities.TASK):
                save(*entity.new_history_created)

    monkeypatch.setattr(report_runner.Entities, "save", save_with_histories)
    monkeypatch.setattr(
        report_runner.Entities,
        "delete",
        lambda *entities: [stored.pop(entity.urlsafe_key, None) for entity in entities],
    )
    return user, task, report


# @matrix ai-report task-completion : complete preservation recovery
@pytest.mark.unit
@pytest.mark.parametrize(
    "completed,recurring",
    [(False, False), (False, "later"), (False, "near"), (True, False)],
)
def test_complete_task_action_preserves_details_and_retries(
    monkeypatch, completed, recurring
):
    from lagniappe.core.tools.ai.reporting.execution import batch
    monkeypatch.setattr(batch, "MAX_BATCH_ACTIONS", 1)
    user, task, report = _completion_case(
        monkeypatch, completed=completed, recurring=recurring
    )
    old_files = list(task.files)
    original = ReportActionAdapter.apply
    calls = []

    def interrupted(adapter, action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "finish" and calls.count("finish") == 1:
            raise RuntimeError("Interrupt after completion")
        return original(adapter, action, *args, **kwargs)

    monkeypatch.setattr(ReportActionAdapter, "apply", interrupted)
    assert report_runner.run_report(report, user)["status"] == "failed"
    assert task.completed is (recurring != "near"), str(report.result)
    completion = task.completed_on
    if recurring == "near":
        histories = task.new_history_created
        assert len(histories) == 1
        assert (
            histories[0].urlsafe_key
            == report.result["actions"][0]["history_output_key"]
        )
        assert histories[0].submission == {"notes": "Keep these values"}
        assert histories[0].files == old_files
        assert not task.submission and not task.files
    else:
        assert task.completed_by is user.page
        assert task.submission == {"notes": "Keep these values"}
        assert task.files == old_files
    assert task.description == "Keep this description"
    assert task.assigned_to is user.page
    if recurring == "later":
        assert task.scheduled_uncomplete_token
        assert task.scheduled_uncomplete_at < task.due_date
    assert report_runner.run_report(report, user)["status"] == "complete"
    assert calls.count("complete") == 1
    assert task.completed_on == completion


# @matrix ai-report task-completion : complete permissions required-fields
@pytest.mark.unit
@pytest.mark.parametrize("denied", [True, False])
def test_complete_task_action_requires_permission_and_required_fields(
    monkeypatch, denied
):
    user, task, report = _completion_case(monkeypatch)
    if denied:
        task.allowed = lambda *_args, **_kwargs: False
    else:
        task.form = TestEntities.get(
            "FORM", {"name": "Required", "hash": "complete-required-form"}
        )
        task.form.form_type = "task"
        task.form.schema = [
            {
                "id": "input-required",
                "type": "input",
                "input": "text",
                "title": "Required detail",
                "required": True,
            }
        ]
        task.submission = {}
    result = report_runner.run_report(report, user)
    assert not task.completed
    assert result["actions"][0]["status"] != "complete"
    assert (
        "permission" in result["actions"][0]["error"]
        if denied
        else "Required" in result["actions"][0]["error"]
    )


# @matrix ai-report : action-registry contract
@pytest.mark.unit
@pytest.mark.parametrize("uses_context", [False, True])
@pytest.mark.parametrize("with_metadata", [False, True])
def test_report_action_registry_matches_proposal_contracts(uses_context, with_metadata):
    adapters = REPORT_ACTION_ADAPTERS

    assert set(adapters) == set(report_contracts.REPORT_ACTION_DATA_CONTRACTS)
    assert set(adapters) == set(report_contracts.ALLOWED_ACTIONS)
    assert all(
        action_type == adapter.action_type for action_type, adapter in adapters.items()
    )

    action = {"type": "local-action"}
    report, user, entity = object(), object(), object()
    created, writes = {}, [entity]
    metadata = {"created": True} if with_metadata else {}
    result = (entity, writes, metadata) if with_metadata else (entity, writes)
    calls = []

    def handler(*args):
        calls.append(args)
        return result

    adapter = ReportActionAdapter(action["type"], handler, uses_context=uses_context)
    assert action["type"] not in adapters
    for context in (None, {"output_key": "local-output"}):
        assert adapter.apply(action, report, user, created, context) == (
            entity, writes, metadata
        )
        arguments = (action, report, user, created)
        assert calls[-1] == (
            (*arguments, context or {}) if uses_context else arguments
        )
    assert len(calls) == 2


# @matrix ai-report : cancellation deterministic-run
@pytest.mark.unit
def test_run_report_checks_deferred_execution_guard(monkeypatch):
    report = _attach_report_process(
        SimpleNamespace(
            urlsafe_key="guarded-report",
            proposal={"summary": "No changes", "actions": []},
            result=None,
            status="ready",
            pending=False,
            error=None,
        )
    )
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
    assert len(checks) == 4
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
    from lagniappe.core.tools.ai.reporting.execution import batch
    monkeypatch.setattr(batch, "MAX_BATCH_ACTIONS", 1)
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
    original_execute = ReportActionAdapter.apply
    calls = []
    failed = {"value": False}

    def interrupted(adapter, action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "second_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("injected interruption")
        return original_execute(adapter, action, *args, **kwargs)

    monkeypatch.setattr(ReportActionAdapter, "apply", interrupted)

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
def test_run_report_retry_continues_independent_work_after_completed_entity_changes(
    monkeypatch,
):
    from lagniappe.core.tools.ai.reporting.execution import batch
    monkeypatch.setattr(batch, "MAX_BATCH_ACTIONS", 1)
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
    original_execute = ReportActionAdapter.apply
    calls = []

    def interrupted(adapter, action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "second_project":
            raise RuntimeError("injected interruption")
        return original_execute(adapter, action, *args, **kwargs)

    monkeypatch.setattr(ReportActionAdapter, "apply", interrupted)
    first = report_runner.run_report(report, user)
    project = stored[first["actions"][0]["entity"]["id"]]
    monkeypatch.setattr(
        type(project),
        "allowed",
        lambda self, action, user=None: False,
    )

    recovered = report_runner.run_report(report, user)

    monkeypatch.setattr(ReportActionAdapter, "apply", original_execute)
    recovered = report_runner.run_report(report, user)
    assert recovered["status"] == "complete"
    assert recovered["actions"][0]["status"] == "complete"
    assert len([entity for entity in stored.values() if entity.entity_kind == "project"]) == 2




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
        ReportActionAdapter,
        "apply",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reconciled action should not execute again")
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "complete"
    assert result["actions"][0]["entity"]["id"] == output_id
    assert list(stored) == [output_id]




# @matrix ai-report : completed-task deterministic-run recovery reuse
@pytest.mark.unit
def test_completed_task_retry_preserves_reused_completion(monkeypatch):
    from lagniappe.core.tools.ai.reporting.execution import batch
    monkeypatch.setattr(batch, "MAX_BATCH_ACTIONS", 1)
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
    task.form = TestEntities.get("FORM", {
        "name": "Registration status", "hash": "completed-task-recovery-form", "form_type": "task",
    })
    task.form.schema = [{"id": "status", "type": "input", "title": "Status"}]
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
    _recovery_store(monkeypatch, page, task)
    original_execute = ReportActionAdapter.apply
    calls = []
    failed = {"value": False}

    def interrupted(adapter, action, *args, **kwargs):
        calls.append(action["id"])
        if action["id"] == "finish_project" and not failed["value"]:
            failed["value"] = True
            raise RuntimeError("stop after task mutation")
        return original_execute(adapter, action, *args, **kwargs)

    monkeypatch.setattr(ReportActionAdapter, "apply", interrupted)

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
                        "type": "attach_file",
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
                        "type": "attach_file",
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
