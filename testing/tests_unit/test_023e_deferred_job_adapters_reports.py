"""Focused deferred-job behavior tests."""

from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import (
    AI,
    DeferredJobInspection,
)
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.deferred_jobs.adapters import reports as report_adapters
from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
)
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

pytestmark = pytest.mark.unit


# @matrix deferred-jobs : quota retry service-tier
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
        lambda prompt: (
            generated.append(("plan", prompt.service_tier))
            or {"summary": "Ready", "actions": []}
        ),
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "complete_organize_submissions",
        lambda proposal, *_args, **kwargs: (
            generated.append(("submissions", kwargs.get("service_tier"))) or proposal
        ),
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


# @matrix deferred-jobs : cancellation report-execution
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

        def begin_execution(self, result=None):
            self.report.status = "running"
            self.report.pending = True
            self.report.error = None
            if result is not None:
                self.report.result = result

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
            self.origin = "web"
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


# @matrix agent-api ai-report deferred-jobs : browser-review cas report-execution
def test_external_report_execution_start_rejects_stale_browser_snapshot(monkeypatch):
    adapter = report_adapters.ReportExecutionAdapter()

    class FakeProcess:
        def __init__(self, report):
            self.report = report

        def begin_execution(self):
            self.report.status = "running"
            self.report.pending = True

    class FakeReport:
        origin = "api"
        urlsafe_key = "external-report-key"

        def __init__(self):
            self.db = {
                "origin": "api",
                "proposal": "stale-browser-proposal",
                "status": "ready",
            }
            self.status = "ready"
            self.pending = False
            self.deferred_job = None
            self.properties = SimpleNamespace(process=FakeProcess(self))

    report = FakeReport()
    actor = SimpleNamespace()
    context = DeferredJobContext(
        job=SimpleNamespace(
            urlsafe_key="external-execution-job",
            idempotency_key="external-execution-operation",
            status_revision=3,
        ),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={},
        checkpoint={},
    )
    guarded_calls = []

    def reject_stale(current, expected_report):
        guarded_calls.append((current, expected_report))
        return report_adapters.agent_api_store.PLAN_OPERATION_STALE

    monkeypatch.setattr(
        report_adapters.external_operations,
        "save_plan_if_idle",
        reject_stale,
    )
    monkeypatch.setattr(
        report_adapters.Entities,
        "save",
        lambda *_args: pytest.fail(
            "A stale API-origin execution start used an ordinary report save"
        ),
    )

    with pytest.raises(
        report_adapters.exceptions.ValidationError,
        match="plan changed while execution was starting",
    ):
        adapter.started(context)

    assert guarded_calls == [
        (
            report,
            {
                "origin": "api",
                "proposal": "stale-browser-proposal",
                "status": "ready",
            },
        )
    ]
    assert report.db["proposal"] == "stale-browser-proposal"
    assert report.status == "running"
    assert report.deferred_job == {
        "key": "external-execution-job",
        "idempotency_key": "external-execution-operation",
        "previous_status": "ready",
        "revision": 3,
    }


# @matrix agent-api ai-report deferred-jobs : browser-review cas report-execution terminal-delivery
def test_external_report_duplicate_cleanup_cannot_overwrite_new_api_proposal(
    monkeypatch,
):
    adapter = report_adapters.ReportExecutionAdapter()

    class FakeReport:
        origin = "api"
        urlsafe_key = "external-report-key"

        def __init__(self):
            self.db = {
                "origin": "api",
                "proposal": "reviewed-proposal",
                "process": "active-execution",
            }
            self.proposal = "reviewed-proposal"
            self.deferred_job = {"key": "external-execution-job"}

    first_delivery = FakeReport()
    duplicate_delivery = FakeReport()
    actor = SimpleNamespace()
    context = DeferredJobContext(
        job=SimpleNamespace(urlsafe_key="external-execution-job"),
        actor=actor,
        notification=None,
        inputs={"report": first_delivery},
        parameters={},
        checkpoint={},
    )
    fetched = iter((first_delivery, duplicate_delivery))
    authoritative = dict(first_delivery.db)
    guarded_calls = []

    def save_if_idle(current, expected_report):
        guarded_calls.append((current, expected_report))
        if expected_report != authoritative:
            return report_adapters.agent_api_store.PLAN_OPERATION_STALE
        authoritative["process"] = "execution-cleaned-up"
        return report_adapters.agent_api_store.PLAN_OPERATION_COMMITTED

    monkeypatch.setattr(report_adapters.Entities, "REPORT", FakeReport)
    monkeypatch.setattr(
        report_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: next(fetched),
    )
    monkeypatch.setattr(
        report_adapters.Entities,
        "save",
        lambda *_args: pytest.fail(
            "API-origin execution cleanup used an ordinary report save"
        ),
    )
    monkeypatch.setattr(
        report_adapters.external_operations,
        "save_plan_if_idle",
        save_if_idle,
    )

    adapter.cleanup(context, terminal=True)
    authoritative["proposal"] = "replacement-api-proposal"
    adapter.cleanup(context, terminal=True)

    assert [call[0] for call in guarded_calls] == [
        first_delivery,
        duplicate_delivery,
    ]
    assert all(
        call[1]
        == {
            "origin": "api",
            "proposal": "reviewed-proposal",
            "process": "active-execution",
        }
        for call in guarded_calls
    )
    assert first_delivery.deferred_job is None
    assert duplicate_delivery.deferred_job is None
    assert authoritative["proposal"] == "replacement-api-proposal"
    assert authoritative["process"] == "execution-cleaned-up"


# @pairs ai-report:recovery deferred-jobs:report-execution
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
            self.properties = SimpleNamespace(process=SimpleNamespace(fail=self.fail))

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


# @matrix ai-report : active-operation failure-isolation
# @pair deferred-jobs:superseded
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


# @matrix ai-report : ask proposal-publication revision status
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
        lambda current_report, current_actor: (
            prompt_calls.append(("initial", current_report, current_actor))
            or "initial-prompt"
        ),
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "revise_ask_prompt",
        lambda current_report, current_actor, feedback: (
            prompt_calls.append(("revision", current_report, current_actor, feedback))
            or "revision-prompt"
        ),
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


# @matrix ai-report : plan-resume proposal-publication status submission-completion
# @pair deferred-jobs:checkpoint
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
        lambda value, report, actor, **kwargs: (
            calls.append((value, report, actor, kwargs)) or completed
        ),
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
    assert (
        adapter.checkpoint_ready(
            SimpleNamespace(
                checkpoint={
                    "schema_version": 1,
                    "stage": "ready_to_apply",
                    "proposal": completed,
                }
            )
        )
        is True
    )
    assert (
        adapter.checkpoint_ready(
            SimpleNamespace(
                checkpoint={
                    "schema_version": 2,
                    "stage": "ready_to_apply",
                    "proposal": completed,
                }
            )
        )
        is False
    )

    assert adapter.prepare(context) is None
    assert calls == [(proposal, report, actor, {"service_tier": "priority"})]
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
