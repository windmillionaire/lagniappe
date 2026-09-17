"""Focused deferred-job behavior tests."""

from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import (
    AI,
    DeferredJobInspection,
)
from lagniappe.core.tools.deferred_jobs.adapters import reports as report_adapters
from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
)
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs

pytestmark = pytest.mark.unit


# @matrix ai-report : input-files no-extra-read fresh-read
@pytest.mark.parametrize(
    "phase",
    [
        "input",
        "started",
        "inspect",
        "failure",
        "cleanup",
        "execution-inspect",
        "execution-failure",
        "execution-cleanup",
    ],
)
def test_report_phases_reuse_current_report_without_loading_input_files(
    monkeypatch, phase
):
    from lagniappe.core.definitions import FetchDepth
    from lagniappe.core.tools.deferred_jobs import common

    class Report:
        entity_kind = "report"
        urlsafe_key = "report-key"
        origin = "web"
        proposal = None
        result = None
        status = "running"

        def __init__(self, file):
            self.db = {}
            self.upload_manifest = None
            self.available = True
            self.input_files = [file]
            self.deferred_job = {"key": "job"}
            self.properties = SimpleNamespace(
                process=SimpleNamespace(
                    fail=lambda *_args, **_kwargs: None,
                    restore_after_execution_failure=lambda *_args, **_kwargs: None,
                )
            )

    stale = Report(SimpleNamespace(name="old-file"))
    current = Report(SimpleNamespace(name="current-file"))
    events = []
    monkeypatch.setattr(report_adapters.Entities, "REPORT", Report)

    def fetch_one(_report, *, request):
        assert request.depth is FetchDepth.DIRECT
        events.append("report-read")
        return current

    def save(*entities):
        assert events == ["report-read"]
        assert entities[0] is current
        assert current.input_files[0] not in entities
        events.append("saved")

    monkeypatch.setattr(report_adapters.Entities, "fetch_one", fetch_one)
    monkeypatch.setattr(
        report_adapters.Entities,
        "fetch",
        lambda *_args, **_kwargs: pytest.fail(
            "Report status needs no input file reads"
        ),
    )
    monkeypatch.setattr(report_adapters.Entities, "save", save)
    monkeypatch.setattr(report_adapters.external_operations, "save_plan_if_idle", lambda report, snapshot, **kwargs: save(report) or "committed")
    context = DeferredJobContext(
        job=SimpleNamespace(
            urlsafe_key="job", idempotency_key="job-input", status_revision=1, status="succeeded"
        ),
        actor=SimpleNamespace(),
        notification=None,
        inputs={"report": stale},
        parameters={},
        checkpoint={},
    )
    if phase == "input":
        assert common._load_reference({"kind": "report", "id": "report-key"}) is current
    else:
        adapter = (
            report_adapters.ReportExecutionAdapter()
            if phase.startswith("execution-")
            else report_adapters.ReportAdapter()
        )
        adapter.validate_apply = lambda _context: None
        method = phase.removeprefix("execution-")
        if method == "failure":
            adapter.failure(context, ValueError("failed"))
        elif method == "cleanup":
            adapter.cleanup(context, terminal=True)
        else:
            getattr(adapter, method)(context)
        assert context.input("report") is current
    assert events.count("report-read") == 1


# @source lagniappe/core/tools/deferred_jobs/adapters/reports.py::AIReportAdapter
# @pair deferred-jobs:cancellation
def test_organize_prepare_stops_before_report_save_after_cancellation(monkeypatch):
    adapter = report_adapters.AIReportAdapter()
    report = SimpleNamespace(summary=None, instructions="Question", input_files=[])
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
        actor=SimpleNamespace(access=lambda _required: True),
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
        db = {}
        key = "report-key"
        available = True
        input_files = ()
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
        db = {}
        key = "report-key"
        available = True
        input_files = ()
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
        db = {}
        key = "report-key"
        available = True
        input_files = ()
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
        db = {}
        key = "report-key"
        available = True
        input_files = ()
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
    adapter = report_adapters.AIReportAdapter()
    events = []

    class FakeReport:
        db = {}
        key = "report-key"
        available = True
        input_files = ()

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


# @matrix ai-report : plan-resume proposal-publication status
# @matrix deferred-jobs : quota retry service-tier
@pytest.mark.parametrize("changes", [False, True])
@pytest.mark.parametrize("revision", [False, True])
def test_ai_report_resumes_prepared_proposal(monkeypatch, changes, revision):
    from testing.utility.ai_report_fakes import _test_user

    actor = _test_user("report-owner")
    report = SimpleNamespace(
        urlsafe_key="report",
        db={},
        available=True,
        instructions="Review tasks",
        input_files=[],
        upload_manifest=[],
        deferred_job={"key": "job"},
        proposal={"summary": "Old answer", "actions": []},
        file_usage=[],
        result=None,
    )
    calls, summaries, saved = [], [], []
    proposal = {
        "summary": "Ready",
        "confidence": 1,
        "actions": [
            {"id": "review", "type": "needs_review", "data": {"reason": "Review"}}
        ]
        if changes
        else [],
    }

    def generate(prompt):
        assert {"create_task", "move_file", "create_page"} <= set(
            prompt.allowed_actions
        )
        calls.append(prompt)
        return {"proposal": proposal, "file_usage": []}

    def set_proposal(value, **kwargs):
        report.proposal = value
        report.status = "ready" if value["actions"] else "complete"

    report.properties = SimpleNamespace(
        process=SimpleNamespace(set_proposal=set_proposal)
    )
    monkeypatch.setattr(
        report_adapters.ai, "finalize_report_upload_manifest", lambda *a, **k: None
    )
    monkeypatch.setattr(
        report_adapters.ai,
        "summarize_report_input_files",
        lambda *a, **k: summaries.append(k),
    )
    monkeypatch.setattr(report_adapters.ai, "generate_report", generate)
    monkeypatch.setattr(
        report_adapters.Entities, "save", lambda *entities: saved.append(entities)
    )
    def guarded_save(report, snapshot, *, active_job):
        assert snapshot == {}
        assert active_job == ("job", "lease")
        saved.append((report, actor))
        return "committed"

    monkeypatch.setattr(report_adapters.external_operations, "save_plan_if_idle", guarded_save)
    context = DeferredJobContext(
        job=SimpleNamespace(attempt=2, urlsafe_key="job", key="job", lease_token="lease"),
        actor=actor,
        notification=None,
        inputs={"report": report},
        parameters={"mode": "revise", "feedback": "Also make changes"}
        if revision
        else {},
        checkpoint={},
    )
    adapter = report_adapters.AIReportAdapter()
    adapter.prepare(context)
    assert calls[0].service_tier == "priority"
    assert summaries[0]["service_tier"] == "priority"
    assert context.checkpoint["stage"] == "ready_to_apply"
    assert adapter.checkpoint_ready(context)
    adapter.prepare(context)
    assert len(calls) == len(summaries) == 1
    result = adapter.apply(context)
    assert result["status"] == ("ready" if changes else "complete")
    assert report.file_usage == []
    assert report.proposal == proposal
    assert saved == [(report, actor)]
    if changes:
        actor.access = lambda _required: False
        with pytest.raises(Exception, match="Creating proposals requires"):
            adapter.apply(context)
