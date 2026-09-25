"""Autofill proposals, compact context, and concurrent-answer safety."""

import pytest
from types import SimpleNamespace
from copy import deepcopy
import json

from lagniappe.core.tools.ai.guidelines.field_types import (
    schema_guidance,
    schema_type_guidance,
)

pytestmark = pytest.mark.unit


# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.committed_result
# @source lagniappe/core/tools/deferred_jobs/runner.py::DeferredJobRunner.run
# @matrix deferred-jobs : recovery checkpoint
# @pair ai:autofill
@pytest.mark.parametrize("age,committed", [(121, True), (10801, True), (121, False)])
def test_committed_autofill_recovers_after_deadline_without_input_or_generation(monkeypatch, age, committed):
    from datetime import datetime, timedelta, timezone
    from lagniappe.core import exceptions
    from lagniappe.core.tools.deferred_jobs.adapters.autofill import AutofillAdapter
    from testing.utility.deferred_job_fakes import RecordingAdapter, RunnerJob, runner

    now = datetime.now(timezone.utc)
    job = RunnerJob(attempt=2, checkpoint={"prepared": True})
    job.created = now - timedelta(seconds=age)
    saved_result = {"target_key": "deleted-task", "applied_fields": ["title"]}
    job.db = {"autofill_receipt": json.dumps(saved_result)} if committed else {}
    adapter = RecordingAdapter()
    adapter.max_lifetime_seconds = 120
    adapter.cancellable_provider = True
    adapter.committed_result = AutofillAdapter().committed_result
    service = runner(monkeypatch, job, adapter)
    monkeypatch.setattr(exceptions, "capture", lambda *args, **kwargs: None)
    deliveries = []
    monkeypatch.setattr(service, "_finish_terminal_delivery", lambda *args, **kwargs: deliveries.append(kwargs))

    result = service.run(job.urlsafe_key, now=now)

    if committed:
        assert result.success
        assert job.status == "succeeded"
        assert job.result == saved_result
        assert adapter.calls == [], "Committed writes must not reload inputs or reapply answers"
        assert deliveries == [{"context": None}], "Delivery must reload any surviving inputs independently"
    else:
        assert not result.success
        assert job.status == "failed"
        assert "prepare" not in adapter.calls and "apply" not in adapter.calls


# @source lagniappe/core/tools/ai/guidelines/field_types.py::schema_guidance
# @source lagniappe/core/tools/ai/guidelines/field_types.py::schema_type_guidance
# @pair ai:autofill
def test_guidance_includes_nested_types_only():
    guidance = schema_guidance([
        {"id": "table-books", "type": "table", "columns": [
            {"id": "row-name", "type": "input", "input": "text"},
            {"id": "row-source", "type": "link", "location": "out"},
        ]},
        {"id": "todo-reading", "type": "todo"},
    ])
    for field_type in ("table", "input", "link", "todo"):
        assert f"#### `{field_type}`" in guidance
    for field_type in ("checkbox", "textarea", "location", "radio", "select"):
        assert f"#### `{field_type}`" not in guidance
    assert "#### `radio`/`select`" in schema_type_guidance(["select"])
    assert "#### `radio`/`select`" in schema_type_guidance(["radio"])
    assert "####" not in schema_guidance([])


# @source lagniappe/core/tools/forms/review.py::merge_proposal
# @pair ai:autofill
def test_merge_preserves_concurrent_answers_and_supports_collections():
    from lagniappe.core.tools.forms.review import merge_proposal

    baseline = {"title": "Book", "table": {"rows": [{"name": "One"}]}, "todo": {"items": [{"text": "Read", "checked": True}]}, "false": False, "zero": 0}
    proposed = {"title": "Corrected title", "author": "Author", "table": {"rows": [{"name": "One"}, {"name": "Two"}]}, "todo": {"items": [{"text": "Read", "checked": True}, {"text": "Review", "checked": False}]}}
    current = {**deepcopy(baseline), "author": "Human answer"}
    merged, conflicts, applied = merge_proposal(baseline, current, proposed)
    assert merged["table"] == proposed["table"]
    assert merged["todo"] == proposed["todo"]
    assert merged["author"] == "Human answer"
    assert conflicts == {"author": "Author"}
    assert set(applied) == {"title", "table", "todo"}
    assert merged["false"] is False and merged["zero"] == 0
    current["table"]["rows"].append({"name": "Human row"})
    merged, conflicts, _ = merge_proposal(baseline, current, proposed)
    assert merged["table"] == current["table"]
    assert conflicts["table"] == proposed["table"]
    merged, conflicts, applied = merge_proposal(baseline, current, proposed, review_only=True)
    assert merged == current and applied == []
    assert conflicts["title"] == "Corrected title"


# @source lagniappe/core/tools/forms/review.py::stage_submission_guard
# @pair ai:autofill
def test_answer_revision_guard_is_tied_to_loaded_baseline():
    from lagniappe.core.tools.forms.review import stage_submission_guard

    target = SimpleNamespace(key="task", db={"submission": '{"a":1}'}, autofill_revision="r1")
    assert not stage_submission_guard(target, {})
    assert not stage_submission_guard(target, {"form-revision": "old"})
    assert not hasattr(target, "_form_additional_guards")
    assert stage_submission_guard(target, {"form-revision": "r1"})
    target.db["submission"] = '{"a":2}'
    assert target._form_additional_guards[0][1]["submission"] == '{"a":1}'


# @source lagniappe/core/tools/forms/review.py::acknowledge_reviews
# @pair ai:autofill
def test_review_acknowledgement_does_not_clear_another_users_draft():
    from lagniappe.core.tools.forms.review import acknowledge_reviews

    target = SimpleNamespace(db={"autofill_reviews": json.dumps({"shared": "s", "me": "m", "other": "o"})})
    acknowledge_reviews(target, SimpleNamespace(urlsafe_key="me"), ["s", "m", "o"])
    assert json.loads(target.db["autofill_reviews"]) == {"other": "o"}


# @source lagniappe/core/tools/forms/review.py::launch_snapshot
# @pair ai:autofill
def test_snapshot_captures_current_answers_and_is_detached(monkeypatch):
    from lagniappe.core.tools.forms import review

    answers = {"title": "Edited in the open form", "table": {"rows": [{"name": "One"}]}}
    schema = [{"id": "title", "type": "input", "input": "text"}]
    actor = object()
    target = SimpleNamespace(form=SimpleNamespace(urlsafe_key="form"), generation=3,
        autofill_revision="edited", properties=SimpleNamespace(submission=SimpleNamespace(value=answers, form_value=answers)))
    monkeypatch.setattr(review.autofill, "autofill_prompt_data", lambda *_args, **kwargs: {
        "schema": schema, "submission": deepcopy(answers), "user": actor, "file": None,
        "user_context": kwargs["user_context"], "attached_files": [{"hash": "hash:evidence"}],
    })
    snapshot = review.launch_snapshot(target, actor, instructions="Add rows")
    answers["title"] = "Another user's later save"
    schema.append({"id": "later", "type": "textarea"})
    assert snapshot["answers"]["title"] == "Edited in the open form"
    assert snapshot["prompt"]["submission"]["title"] == "Edited in the open form"
    assert len(snapshot["prompt"]["schema"]) == 1
    assert snapshot["prompt"]["user_context"] == "Add rows"
    assert "user" not in snapshot["prompt"] and "file" not in snapshot["prompt"]
    assert snapshot["revision"] == "edited" and snapshot["generation"] == 3


# @source lagniappe/core/tools/forms/review.py::prepare_proposal
# @pair ai:autofill
def test_proposal_validates_populated_tables_and_todos():
    from lagniappe.core.tools.forms.review import prepare_proposal

    schema = [
        {"id": "table-books", "type": "table", "columns": [{"id": "input-title", "type": "input", "input": "text"}]},
        {"id": "todo-reading", "type": "todo"},
    ]
    values = {"table-books": {"rows": [{"input-title": "One"}, {"input-title": "Two"}]},
              "todo-reading": {"items": [{"text": "Read", "checked": True}, {"text": "Review", "checked": False}]}}
    target = SimpleNamespace(entity_kind="task", properties=SimpleNamespace(submission=SimpleNamespace(value={"table-books": {"rows": [{"input-title": "One"}]}})))
    proposal = prepare_proposal(schema, values, target, None)
    assert proposal["answers"] == values
    assert proposal["values"] == values
    assert target.properties.submission.value == {"table-books": {"rows": [{"input-title": "One"}]}}


# @source lagniappe/core/tools/forms/review.py::review_projection
# @pair ai:autofill
def test_review_projection_is_actor_scoped(monkeypatch):
    from lagniappe.core.tools.forms import review

    class Job(SimpleNamespace):
        pass
    me = SimpleNamespace(key="me", urlsafe_key="me")
    refs = {"shared": "shared-job", "me": "my-job", "other": "other-job"}
    target = SimpleNamespace(urlsafe_key="task", form=None, generation=0, submission_schema=[],
        db={"autofill_reviews": json.dumps(refs)}, allowed=lambda *args, **kwargs: True)
    jobs = [Job(urlsafe_key="shared-job", job_type="autofill", actor=me, inputs={"target": {"id": "task"}},
        parameters={"snapshot": {"generation": 0, "form": None, "prompt": {"schema": []}, "values": {"title": "Base"}}},
        checkpoint={"proposal": {"values": {"title": "AI"}}}, db={"autofill_receipt": "{}"}),
        Job(urlsafe_key="my-job", job_type="autofill", actor=me, inputs={"target": {"id": "task"}},
        parameters={"mode": "revise", "snapshot": {"generation": 0, "form": None, "prompt": {"schema": []}, "values": {}}},
        checkpoint={"proposal": {"values": {"title": "Private"}}}, db={"autofill_receipt": "{}"})]
    reads = []
    monkeypatch.setattr(review.Entities, "DEFERRED_JOB", Job)
    monkeypatch.setattr(review.Entities, "fetch", lambda *keys, **kwargs: (reads.append(keys) or jobs))
    result = review.review_projection(target, me)
    assert reads == [("shared-job", "my-job")]
    assert [candidate["submission"]["title"] for candidate in result] == ["AI", "Private"]
    assert result[0]["fields"] == ["title"]
    jobs[1].actor = SimpleNamespace(key="other")
    assert len(review.review_projection(target, me)) == 1
    target.submission_schema = [{"id": "new", "type": "textarea"}]
    assert review.review_projection(target, me) == [], "Completed candidates expire even for same-generation schema edits"
    target.allowed = lambda *args, **kwargs: False
    assert review.review_projection(target, me) == []


# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.prepare_snapshot
# @pair ai:autofill
def test_autofill_preparation_uses_snapshot_and_original_file(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.adapters import autofill as adapter

    class File(SimpleNamespace):
        pass
    file = File(allowed=lambda *args, **kwargs: True)
    snapshot = {"prompt": {"schema": [], "submission": {"title": "Launch answer"}, "user_context": "Launch instruction"}}
    prompt_inputs = []
    phases = []
    monkeypatch.setattr(adapter.Entities, "FILE", File)
    monkeypatch.setattr(adapter.Entities, "fetch_one", lambda *args, **kwargs: file)
    monkeypatch.setattr(adapter.ai_autofill, "form_autofill_prompt", lambda **kwargs: prompt_inputs.append(kwargs) or kwargs)
    monkeypatch.setattr(adapter.ai_autofill, "generate_autofilled_submission", lambda *args, **kwargs: {})
    monkeypatch.setattr(adapter.ai_autofill, "autofill_summary_dependencies", lambda *args: pytest.fail("Autofill waited for a summary"))
    context = SimpleNamespace(actor="actor", parameters={"snapshot": snapshot, "file_key": "file"}, input=lambda name: SimpleNamespace(name="Later saved name"), set_phase=lambda phase: phases.append(phase))
    result = adapter.AutofillAdapter().prepare(context)
    assert prompt_inputs[0]["submission"] == {"title": "Launch answer"}
    assert prompt_inputs[0]["original_files"] == [file]
    assert prompt_inputs[0]["user"] == "actor"
    assert result == {"submission": {}, "proposal": {"answers": {}, "values": {}}}
    assert "user" not in snapshot["prompt"]


# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.start_writes
# @pair ai:autofill
def test_autofill_start_writes_only_operation_reference_with_answer_guard(monkeypatch):
    from lagniappe.core.tools.deferred_jobs.adapters import autofill as adapter

    target = SimpleNamespace(_form_additional_guards=[("task", {"submission": "old"})], submission={"title": "Human"})
    monkeypatch.setattr(adapter, "plan_root", lambda entity, property_mask: SimpleNamespace(effects=[SimpleNamespace(entity=entity, property_mask=property_mask)]))
    monkeypatch.setattr(adapter, "prepare_durable_writes", lambda plan: plan.effects)
    writes, guards = adapter.AutofillAdapter().start_writes(
        SimpleNamespace(inputs={"target": target}, parameters={"snapshot": {"version": 1}}),
        SimpleNamespace(urlsafe_key="job", idempotency_key="request", status_revision=1))
    assert writes == [(target, ("deferred_job",))]
    assert target.deferred_job == {"key": "job", "idempotency_key": "request", "revision": 1}
    assert target.submission == {"title": "Human"}
    assert guards == [("task", {"submission": "old"})]


# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.apply_proposal
# @pair ai:autofill
@pytest.mark.parametrize("with_form", [False, True])
def test_autofill_apply_is_guarded_and_retains_conflicts(monkeypatch, with_form):
    from lagniappe.core.tools.deferred_jobs.adapters import autofill as adapter

    target = SimpleNamespace(key="task", urlsafe_key="task", entity_kind="task", completed=False, form=None, generation=0,
        submission_schema=[{"id": "title", "type": "input", "input": "text"}],
        db={"submission": '{"title":"Human"}'}, properties=SimpleNamespace(submission=SimpleNamespace(value={"title": "Human"})),
        allowed=lambda *args, **kwargs: True)
    job = SimpleNamespace(key="job", urlsafe_key="job", lease_token="lease", db={}, actor=SimpleNamespace(urlsafe_key="actor"))
    if with_form:
        target.form = SimpleNamespace(key="form", urlsafe_key="form", db={"schema": "original definition"})
    snapshot = {"generation": 0, "form": "form" if with_form else None, "revision": "launch", "values": {}, "prompt": {"schema": target.submission_schema}}
    context = SimpleNamespace(parameters={"snapshot": snapshot}, job=job, actor="actor", inputs={"target": target},
        input=lambda name: target, ensure_active=lambda: None, checkpoint={"proposal": {"values": {"title": "AI"}}})
    monkeypatch.setattr(adapter.Entities, "fetch_one", lambda *args, **kwargs: target)
    monkeypatch.setattr(adapter, "deferred_job_lock_key", lambda entity: "lock")
    monkeypatch.setattr(adapter, "plan_root", lambda *args, **kwargs: SimpleNamespace(effects=[]))
    saved = []
    monkeypatch.setattr(adapter, "execute_mutation", lambda plan, **kwargs: saved.append(kwargs["guards"]))
    result = adapter.AutofillAdapter().apply(context)
    assert result["conflicting_fields"] == ["title"] and result["applied_fields"] == []
    assert target.properties.submission.value == {"title": "Human"}
    assert json.loads(target.db["autofill_reviews"]) == {"shared": "job"}
    assert json.loads(job.db["autofill_receipt"])["snapshot_revision"] == "launch"
    assert saved[0][1] == ("job", {"status": "running", "lease_token": "lease", "autofill_receipt": None})
    assert saved[0][-1] == ("lock", {"operation": "job"})
    if with_form:
        assert saved[0][2] == ("form", {"schema": "original definition"})
        assert isinstance(saved[0][2][1], adapter.database_utility.ExactEntityState)


# @source lagniappe/core/tools/deferred_jobs/adapters/autofill.py::AutofillAdapter.apply_proposal
# @source lagniappe/core/tools/forms/review.py::snapshot_matches_form
# @pair ai:autofill
@pytest.mark.parametrize("drift", ["answers", "schema", "definition", "form", "metadata", "private"])
def test_autofill_context_or_schema_drift_keeps_suggestions_for_review(monkeypatch, drift):
    from lagniappe.core.tools.deferred_jobs.adapters import autofill as adapter

    schema = [{"id": "title", "type": "input", "input": "text"}, {"id": "author", "type": "input", "input": "text"}]
    target = SimpleNamespace(key="task", urlsafe_key="task", entity_kind="task", completed=False, form=None, generation=0,
        name="Book A", submission_schema=schema, db={}, properties=SimpleNamespace(submission=SimpleNamespace(value={"title": "Book A"})),
        allowed=lambda *args, **kwargs: True)
    snapshot = {"generation": 0, "form": None, "revision": "launch", "values": {"title": "Book A"}, "prompt": {"schema": schema, "target": {"name": "Book A"}}}
    if drift == "answers":
        target.properties.submission.value["title"] = "Book B"
    elif drift == "schema":
        target.generation = 1
    elif drift == "definition":
        target.submission_schema = [*schema, {"id": "new", "type": "textarea"}]
    elif drift == "form":
        target.form = SimpleNamespace(urlsafe_key="other-form")
    elif drift == "metadata":
        target.name = "Book B"
    original = deepcopy(target.properties.submission.value)
    job = SimpleNamespace(key="job", urlsafe_key="job", lease_token="lease", db={}, actor=SimpleNamespace(urlsafe_key="actor"))
    context = SimpleNamespace(parameters={"snapshot": snapshot, "mode": "revise" if drift == "private" else "fill"},
        job=job, actor="actor", inputs={"target": target}, input=lambda name: target, ensure_active=lambda: None,
        checkpoint={"proposal": {"values": {"author": "Author of Book A"}}})
    monkeypatch.setattr(adapter.Entities, "fetch_one", lambda *args, **kwargs: target)
    monkeypatch.setattr(adapter, "deferred_job_lock_key", lambda entity: "lock")
    monkeypatch.setattr(adapter, "plan_root", lambda *args, **kwargs: SimpleNamespace(effects=[]))
    monkeypatch.setattr(adapter, "execute_mutation", lambda *args, **kwargs: None)
    if drift in {"schema", "definition", "form"}:
        with pytest.raises(adapter.DeferredJobDriftError, match="form changed.*Run autofill again"):
            adapter.AutofillAdapter().apply(context)
        assert not target.db and not job.db, "Obsolete proposals must not publish or change answers"
        return
    result = adapter.AutofillAdapter().apply(context)
    assert result["review_only"] is True
    assert result["applied_fields"] == []
    assert result["conflicting_fields"] == ["author"]
    assert target.properties.submission.value == original
    assert json.loads(target.db["autofill_reviews"]) == {"actor" if drift == "private" else "shared": "job"}
