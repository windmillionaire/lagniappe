"""Focused deferred-job behavior tests."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
from types import SimpleNamespace

from google.api_core import exceptions as google_exceptions
from google.genai import errors as genai_errors
import httpx
import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobRunState,
    DeferredJobSpec,
    DeferredJobStatus,
    DeferredJobType,
    FetchReason,
)
from lagniappe.core.entities import Entities
from lagniappe.core.mixins.submitter import SubmitterMixin
from lagniappe.core.properties.deferred_job_dispatch import TaskIdentity
from lagniappe.core.properties.deferred_job_request import RequestFingerprint
from lagniappe.core.properties import deferred_job_lifecycle
from lagniappe.core.tools import database, notification_service, task_queue
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.database import deferred_jobs as deferred_database
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.deferred_jobs import common as deferred_common
from lagniappe.core.tools.deferred_jobs import retry as deferred_retry
from lagniappe.core.tools.deferred_jobs.adapters.base import DeferredJobAdapter
from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext
from lagniappe.core.tools.deferred_jobs.control import (
    DeferredExecutionControl,
    _DeferredLeaseGuard,
)
from lagniappe.core.tools.deferred_jobs.dispatch import DeferredJobDispatch
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
    DeferredJobDriftError,
    DeferredJobInfrastructureError,
    DeferredJobLockedError,
)
from lagniappe.core.tools.deferred_jobs.locks import (
    AUTOFILL_FORM_LOCK_SCOPE,
    active_deferred_job_lock,
    deferred_job_lock_descriptor,
    deferred_job_lock_descriptors,
    deferred_job_lock_key,
)
from lagniappe.core.tools.deferred_jobs.retry import MODEL_BUSY_MESSAGE
from lagniappe.core.tools.deferred_jobs.runner import MISSING_INPUT_MESSAGE
from lagniappe.core.tools.deferred_jobs.service import DeferredJobService, DeferredJobs
from lagniappe.core.tools.files import extract as file_extract
from testing.utility.deferred_job_fakes import (
    ContendedDatastore,
    FakeDatastore,
    FakeTasksClient,
    KeyedDatastore,
    KeyedEntity,
    RecordingAdapter,
    RunnerJob,
    fake_start_entities,
    operation_projection,
    runner,
    terminal_delivery_runner,
)
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit
from lagniappe.core.tools.deferred_jobs.adapters import reports as report_adapters



# @features deferred-jobs
# @dimensions service-tier quota retry
def test_organize_retry_uses_priority_for_every_generation_stage(monkeypatch):
    adapter = report_adapters.OrganizeReportAdapter()
    report = SimpleNamespace(summary=None)
    actor = SimpleNamespace()
    summary_calls = []
    retrieval_calls = []
    generated = []

    monkeypatch.setattr(
        report_adapters.ai,
        "finalize_report_upload_manifest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "summarize_report_input_files",
        lambda _report, **kwargs: summary_calls.append(kwargs) or [],
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "prepare_organize_retrieval_context",
        lambda _report, _actor: retrieval_calls.append((_report, _actor)) or {},
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "organize_prompt",
        lambda *_args: Prompt("Organize", type="organize report"),
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "generate_organize_plan",
        lambda prompt: generated.append(("plan", prompt.service_tier))
        or {"summary": "Ready", "actions": []},
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "complete_organize_submissions",
        lambda proposal, *_args, **kwargs: generated.append(
            ("submissions", kwargs.get("service_tier"))
        )
        or proposal,
    )

    for attempt in (1, 2):
        context = DeferredJobContext(
            job=SimpleNamespace(attempt=attempt),
            actor=actor,
            notification=None,
            inputs={"report": report},
            parameters={},
            checkpoint={},
        )
        adapter.prepare(context)

    assert "service_tier" not in summary_calls[0]
    assert summary_calls[1]["service_tier"] == "priority"
    assert retrieval_calls == [(report, actor), (report, actor)]
    assert generated == [
        ("plan", None),
        ("submissions", None),
        ("plan", "priority"),
        ("submissions", "priority"),
    ]




# @pair deferred-jobs:cancellation
def test_organize_prepare_stops_before_report_save_after_cancellation(monkeypatch):
    adapter = report_adapters.OrganizeReportAdapter()
    report = SimpleNamespace(summary=None)
    saved = []
    monkeypatch.setattr(
        report_adapters.ai,
        "finalize_report_upload_manifest",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "summarize_report_input_files",
        lambda *_args, **_kwargs: [SimpleNamespace()],
    )
    monkeypatch.setattr(
        report_adapters.Entities,
        "save",
        lambda *_args: saved.append(_args),
    )
    context = DeferredJobContext(
        job=SimpleNamespace(attempt=1),
        actor=SimpleNamespace(),
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
        active_check=lambda: False,
    )

    with pytest.raises(
        DeferredJobClaimLostError,
        match="cancelled or superseded",
    ):
        adapter.prepare(context)

    assert saved == []




# @pair deferred-jobs:report-execution
# @pair deferred-jobs:cancellation
# @pair ai-report:deterministic-run
def test_report_execution_adapter_runs_the_reviewed_proposal(monkeypatch):
    adapter = report_adapters.ReportExecutionAdapter()
    assert adapter.notification_policy == "none"

    class FakeUser:
        entity_kind = "user"
        urlsafe_key = "actor-key"

        def __init__(self):
            self.properties = SimpleNamespace()

        def access(self, required):
            return AI.CREATE.implies(required)

    class FakeProcess:
        def __init__(self, report):
            self.report = report

        def fail(self, message, result=None):
            self.report.status = "failed"
            self.report.pending = None
            self.report.error = message
            if result is not None:
                self.report.result = result

    class FakeReport:
        entity_kind = "report"
        urlsafe_key = "report-key"

        def __init__(self):
            self.status = "ready"
            self.pending = False
            self.error = None
            self.deferred_job = None
            self.result = None
            self.proposal = {
                "summary": "Reviewed proposal",
                "actions": [{"id": "save-one", "type": "skip"}],
            }
            self.properties = SimpleNamespace(process=FakeProcess(self))

        def allowed(self, *_args, **_kwargs):
            return True

    actor = FakeUser()
    report = FakeReport()
    job = SimpleNamespace(
        urlsafe_key="execution-job",
        idempotency_key="execution-operation",
        client={},
        authorization={},
    )
    context = DeferredJobContext(
        job=job,
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
        active_check=lambda: True,
    )
    saved = []
    calls = []
    monkeypatch.setattr(report_adapters.Entities, "USER", FakeUser)
    monkeypatch.setattr(report_adapters.Entities, "REPORT", FakeReport)
    monkeypatch.setattr(
        report_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: report,
    )

    spec = SimpleNamespace(actor=actor, inputs={"report": report})
    job.authorization = adapter.authorization(spec)
    adapter.started(context)
    adapter.authorize(context)
    adapter.validate_apply(context)

    def run_report(current, user, *, ensure_active):
        calls.append((current, user))
        ensure_active()
        current.status = "complete"
        current.pending = False
        current.result = {
            "ledger_version": 1,
            "status": "complete",
            "actions": [{"status": "skipped"}],
        }
        return current.result

    monkeypatch.setattr(report_adapters.ai, "run_report", run_report)

    result = adapter.apply(context)

    assert result == {
        "report_key": "report-key",
        "status": "complete",
        "action_count": 1,
    }
    assert calls == [(report, actor)]
    assert adapter.inspect(context) is DeferredJobInspection.APPLIED
    assert report.deferred_job == {
        "key": "execution-job",
        "idempotency_key": "execution-operation",
        "previous_status": "ready",
        "revision": 0,
    }

    adapter.cleanup(context, terminal=True)

    assert report.deferred_job is None
    assert saved




# @pair deferred-jobs:report-execution
# @pair ai-report:recovery
def test_report_execution_failure_preserves_a_retryable_ledger(monkeypatch):
    adapter = report_adapters.ReportExecutionAdapter()

    class FakeReport:
        entity_kind = "report"
        urlsafe_key = "report-key"

        def __init__(self):
            self.status = "running"
            self.pending = True
            self.error = None
            self.deferred_job = {
                "key": "execution-job",
                "idempotency_key": "execution-operation",
                "previous_status": "ready",
            }
            self.result = {
                "ledger_version": 1,
                "status": "running",
                "actions": [
                    {"status": "complete"},
                    {"status": "applying"},
                ],
            }
            self.properties = SimpleNamespace(
                process=SimpleNamespace(fail=self.fail)
            )

        def fail(self, message, result=None):
            self.status = "failed"
            self.pending = None
            self.error = message
            if result is not None:
                self.result = result

    report = FakeReport()
    actor = SimpleNamespace()
    context = DeferredJobContext(
        job=SimpleNamespace(urlsafe_key="execution-job"),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
    )
    monkeypatch.setattr(report_adapters.Entities, "REPORT", FakeReport)
    monkeypatch.setattr(
        report_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: report,
    )
    monkeypatch.setattr(report_adapters.Entities, "save", lambda *_args: None)

    adapter.failure(context, ValueError("save worker stopped"))

    assert report.status == "failed"
    assert report.pending is None
    assert report.error == "save worker stopped"
    assert report.result["status"] == "failed"
    assert report.result["failed_at"] == 2




# @pair deferred-jobs:superseded
# @pair ai-report:active-operation
# @pair ai-report:failure-isolation
def test_report_replacement_supersedes_old_job_and_ignores_old_failure(monkeypatch):
    adapter = report_adapters.OrganizeReportAdapter()
    events = []

    class FakeReport:
        def __init__(self):
            self.urlsafe_key = "report-key"
            self.deferred_job = {"key": "old-operation"}

    report = FakeReport()
    actor = SimpleNamespace()
    context = DeferredJobContext(
        job=SimpleNamespace(
            urlsafe_key="new-operation",
            idempotency_key="new-idempotency-key",
        ),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
    )
    monkeypatch.setattr(
        DeferredJobs,
        "supersede",
        lambda previous: events.append(("supersede", previous.copy())) or True,
    )
    monkeypatch.setattr(
        report_adapters.Entities,
        "save",
        lambda *entities: events.append(("save", entities)),
    )

    adapter.started(context)

    assert events[0] == ("supersede", {"key": "old-operation"})
    assert events[1] == ("save", (report, actor))
    assert report.deferred_job == {
        "key": "new-operation",
        "idempotency_key": "new-idempotency-key",
        "revision": 0,
    }

    monkeypatch.setattr(report_adapters.Entities, "REPORT", FakeReport)
    stale_report = FakeReport()
    current_report = FakeReport()
    current_report.deferred_job = {"key": "new-operation"}
    context.inputs["report"] = stale_report
    monkeypatch.setattr(
        report_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: current_report,
    )
    context.job.urlsafe_key = "old-operation"
    adapter.failure(context, ValueError("old worker failed"))
    assert events == [
        ("supersede", {"key": "old-operation"}),
        ("save", (report, actor)),
    ]




# @pair ai-report:ask
# @pair ai-report:revision
# @pair ai-report:status
# @pair ai-report:proposal-publication
# @pair deferred-jobs:checkpoint
@pytest.mark.parametrize(
    ("parameters", "response", "expected_prompt", "expected_status"),
    [
        (
            {},
            {
                "summary": "No follow-up work is needed.",
                "confidence": 0.9,
                "actions": [],
            },
            "initial-prompt",
            "complete",
        ),
        (
            {"mode": "revise", "feedback": "Call out the ambiguity."},
            {
                "summary": "A human should confirm the ambiguous match.",
                "confidence": 0.5,
                "actions": [
                    {
                        "id": "review",
                        "type": "needs_review",
                        "data": {"note": "Confirm the matching record."},
                    }
                ],
            },
            "revision-prompt",
            "ready",
        ),
    ],
    ids=("answer", "revision-with-actions"),
)
def test_ask_report_adapter_prepares_and_applies_checkpointed_response(
    monkeypatch,
    parameters,
    response,
    expected_prompt,
    expected_status,
):
    adapter = report_adapters.AskReportAdapter()
    actor = SimpleNamespace()
    saved = []
    phases = []
    prompt_calls = []

    class Process:
        def set_proposal(self, proposal, status="ready"):
            report.proposal = proposal
            report.summary = proposal.get("summary")
            report.status = status
            report.pending = None
            report.error = None
            report.result = None

    report = SimpleNamespace(
        urlsafe_key="ask-report",
        deferred_job={"key": "ask-job"},
        proposal={"summary": "Previous answer", "actions": []},
        result={"stale": True},
        properties=SimpleNamespace(process=Process()),
    )
    job = SimpleNamespace(
        urlsafe_key="ask-job",
        idempotency_key="ask-operation",
    )

    class Control:
        def ensure_active(self):
            return None

        def set_phase(self, phase, **_details):
            phases.append(str(getattr(phase, "value", phase)))

    monkeypatch.setattr(
        report_adapters.ai,
        "ask_prompt",
        lambda current_report, current_actor: prompt_calls.append(
            ("initial", current_report, current_actor)
        )
        or "initial-prompt",
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "revise_ask_prompt",
        lambda current_report, current_actor, feedback: prompt_calls.append(
            ("revision", current_report, current_actor, feedback)
        )
        or "revision-prompt",
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "generate_ask_report",
        lambda prompt: prompt_calls.append(("generate", prompt)) or response,
    )
    monkeypatch.setattr(
        report_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    context = DeferredJobContext(
        job=job,
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters=parameters,
        checkpoint={},
        execution_control=Control(),
    )

    checkpoint = adapter.prepare(context)

    assert checkpoint == {"proposal": response, "status": expected_status}
    assert phases == ["generating", "validating"]
    assert prompt_calls[-1] == ("generate", expected_prompt)
    if parameters:
        assert prompt_calls[0] == (
            "revision",
            report,
            actor,
            parameters["feedback"],
        )
    else:
        assert prompt_calls[0] == ("initial", report, actor)
    assert report.result == {"stale": True}

    context.checkpoint = checkpoint
    result = adapter.apply(context)

    assert result == {
        "report_key": "ask-report",
        "status": expected_status,
        "action_count": len(response["actions"]),
    }
    assert report.proposal == response
    assert report.proposal is not response
    assert report.status == expected_status
    assert report.result is None
    assert saved == [(report, actor)]




# @pair deferred-jobs:checkpoint
# @pair ai-report:plan-resume
# @pair ai-report:submission-completion
# @pair ai-report:status
# @pair ai-report:proposal-publication
def test_organize_resumes_plan_checkpoint_without_second_planning_call(monkeypatch):
    adapter = report_adapters.OrganizeReportAdapter()
    proposal = {"summary": "Planned", "actions": []}
    completed = {"summary": "Completed", "actions": []}
    calls = []
    checkpoints = []
    monkeypatch.setattr(
        report_adapters.ai,
        "generate_organize_plan",
        lambda _prompt: pytest.fail("planning should not run again"),
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "complete_organize_submissions",
        lambda value, report, actor, **kwargs: calls.append(
            (value, report, actor, kwargs)
        )
        or completed,
    )
    saved = []

    class Process:
        def set_proposal(self, value, status="ready"):
            report.proposal = value
            report.status = status

    report = SimpleNamespace(
        urlsafe_key="organize-report",
        deferred_job={"key": "organize-job"},
        properties=SimpleNamespace(process=Process()),
    )
    actor = SimpleNamespace()
    monkeypatch.setattr(
        report_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    context = DeferredJobContext(
        job=SimpleNamespace(
            attempt=2,
            urlsafe_key="organize-job",
            idempotency_key="organize-operation",
        ),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={
            "schema_version": 1,
            "stage": "plan_ready",
            "proposal": proposal,
        },
        active_check=lambda: True,
        checkpoint_callback=lambda checkpoint, *, progress=None: checkpoints.append(
            (checkpoint, progress)
        ),
    )

    assert adapter.checkpoint_ready(context) is False
    assert adapter.checkpoint_ready(
        SimpleNamespace(
            checkpoint={
                "schema_version": 1,
                "stage": "ready_to_apply",
                "proposal": completed,
            }
        )
    ) is True
    assert adapter.checkpoint_ready(
        SimpleNamespace(
            checkpoint={
                "schema_version": 2,
                "stage": "ready_to_apply",
                "proposal": completed,
            }
        )
    ) is False

    assert adapter.prepare(context) is None
    assert calls == [
        (proposal, report, actor, {"service_tier": "priority"})
    ]
    assert checkpoints == [
        (
            {
                "schema_version": 1,
                "stage": "ready_to_apply",
                "proposal": completed,
                "status": "ready",
            },
            {"phase": "prepared"},
        )
    ]

    result = adapter.apply(context)

    assert result == {
        "report_key": "organize-report",
        "status": "ready",
        "action_count": 0,
    }
    assert report.proposal == completed
    assert report.proposal is not completed
    assert report.status == "ready"
    assert saved == [(report, actor)]
