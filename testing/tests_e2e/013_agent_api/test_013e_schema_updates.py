"""Schema preview, external review and mixed migrations through real HTTP/domain paths."""

from copy import deepcopy
import json
import re
from uuid import uuid4

import pytest
from flask_login import login_user

from lagniappe.core.definitions import Fetch, FetchReason, DeferredJobType
from lagniappe.core.entities import Entities
from lagniappe.core.tools import form_changes
from lagniappe.core.tools.ai import external_api, form_conversion
from lagniappe.core.tools.ai.reporting import schema_updates
from lagniappe.core.tools.auth import agent_api as agent_auth
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.web import app
from testing.definitions import Pages, Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.schema_fields import SchemaFields
from testing.resources.form import Form

pytestmark = pytest.mark.e2e


# @source lagniappe/core/tools/ai/function_definitions/preview_form_schema_update.py::execute_preview_form_schema_update
# @source lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_form_schema
# @source lagniappe/core/tools/deferred_jobs/adapters/form_change.py::FormChangeAdapter
# @source lagniappe/core/tools/deferred_jobs/adapters/form_change.py::FormChangeAdapter.prepare_ai_target
# @source lagniappe/core/tools/form_changes.py::prepare_target
# @source lagniappe/core/tools/ai/reporting/schema_updates.py::report_impact
# @source lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @source lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @source lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @matrix form-migration : preview external-provider-free publication completed-task review
# @matrix ai-report : schema-update deterministic-run continue
# @pairs agent-api:proposal-validation
@pytest.mark.parametrize("origin", ["api", "web"])
def test_reviewed_schema_migration_waits_for_publication_and_preserves_completion(get_user, monkeypatch, origin):
    user = get_user(Users.OWNER)
    actor = user.entity
    parent = Pages.test_create_page_task.get(user)
    form = Form(user=user, definition=FormDefinition(
        name=f"AI conversion {uuid4().hex[:8]}", form_type="task",
        schema=(SchemaFields.TEXTAREA.get(_id="notes", title="Notes"), SchemaFields.TEXT_INPUT.get(_id="count", title="Count")),
    )).create()
    tasks = []
    for index in range(3):
        task = Entities.TASK.create({"name": f"Conversion target {index}", "page": parent.entity, "form": form.entity, "submission": {"notes": f"Keep {index}", "count": "0"}})
        task = Entities.fetch_one(task, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
        task.save_submission()
        if index == 1:
            task.complete(user=actor)
        task.save()
        tasks.append(task)
    completion = tasks[1].db["completed_submission"]
    operations = [{"op": "update_field", "schema_id": "notes", "patch": {"type": "todo"}}, {"op": "update_field", "schema_id": "count", "patch": {"input": "number"}}]
    monkeypatch.setattr(agent_auth, "authenticate_credential", lambda token: (actor, {"active": True, "generation": 1}))
    client = app.test_client()
    headers = {"Authorization": "Bearer test-schema-conversion"}
    created = client.post("/api/v1/plans", json={"tool": "organize", "instructions": "Convert Notes to a todo list and Count to a number."}, headers=headers)
    assert created.status_code == 201, created.text
    plan_id = created.json["id"]
    preview_args = {"id": f"hash:{form.entity.hash}", "operations": operations, "include_values": True, "limit": 2}
    preview = client.post("/api/v1/tools/preview_form_schema_update", json={"arguments": preview_args}, headers=headers)
    assert preview.status_code == 200, preview.text
    first = preview.json["result"]
    assert first["affected"] == 3 and first["has_more"]
    second = client.post("/api/v1/tools/preview_form_schema_update", json={"arguments": {**preview_args, "cursor": first["next_cursor"]}}, headers=headers)
    assert second.status_code == 200, second.text
    assert not second.json["result"]["has_more"]
    candidates = [{"entity": item["entity"], "schema_id": field["schema_id"], "source_fingerprint": field["source_fingerprint"], "value": {"items": [{"text": field["value"], "checked": False}]}} for item in first["instances"] + second.json["result"]["instances"] for field in item["fields"] if field["rule"] == "ai"]
    proposal = {"summary": "Convert saved Notes and Count. Unconvertible values clear; migration cannot be undone.", "confidence": 1, "issues": [], "actions": [
        {"id": "schema", "type": "update_form_schema", "data": {"form": f"hash:{form.entity.hash}", "operations": operations, "baseline": first["baseline"], "scope_fingerprint": first["scope_fingerprint"], "conversions": candidates}},
        {"id": "rename", "type": "rename_entity", "depends_on": ["schema"], "data": {"entity": f"hash:{tasks[0].hash}", "name": "Published migration"}},
    ]}
    if origin == "api":
        incomplete = deepcopy(proposal)
        incomplete["actions"][0]["data"]["conversions"].pop()
        refused = client.post(f"/api/v1/plans/{plan_id}/submit", headers=headers, json={"contract_version": external_api.CONTRACT_VERSION, "proposal": incomplete})
        assert refused.status_code == 422, refused.text
        submitted = client.post(f"/api/v1/plans/{plan_id}/submit", headers=headers, json={"contract_version": external_api.CONTRACT_VERSION, "proposal": proposal})
        assert submitted.status_code == 200, submitted.text
        monkeypatch.setattr(Entities.USER, "access", lambda *args: False)
    else:
        from lagniappe.core.tools.ai.reporting.proposals.validation import validate_proposal
        report = Entities.fetch_one(plan_id, request=Fetch.direct())
        proposal["actions"][0]["data"].pop("conversions")
        proposal["actions"][0]["data"]["conversion_instructions"] = {"notes": "Preserve item order and unchecked state."}
        report.origin = "web"
        report.proposal = schema_updates.prepare_schema_updates(validate_proposal(proposal), actor)
        report.status = "ready"
        Entities.save(report)
    calls = []
    def convert(requests, user):
        assert origin == "web", "External execution must not invoke a provider"
        calls.append(requests)
        return {item["id"]: {"value": {"items": [{"text": item["value"], "checked": False}]}} for item in requests}
    monkeypatch.setattr(form_conversion, "generate_conversions", convert)
    monkeypatch.setattr(app.login_manager, "_user_callback", lambda identifier: actor)
    with client.session_transaction() as session:
        session["_user_id"] = actor.get_id()
        session["_fresh"] = True
    review = client.get(f"/tools/reports/{plan_id}")
    assert review.status_code == 200, review.text
    assert 'data-role="schema-impact-item"' in review.text and "cannot be undone" in review.text
    assert all(task.urlsafe_key in review.text for task in tasks)
    assert not calls
    # Hold all dispatches to observe the real parent/child scheduling boundary.
    monkeypatch.setattr(DeferredJobs, "dispatch", lambda *args, **kwargs: "held")
    csrf = re.search(r'<input id="token" type="hidden" value="([^"]+)"', review.text).group(1)
    browser_headers = {"X-CSRFToken": csrf}
    approved = client.post(f"/tools/reports/{plan_id}/run", headers=browser_headers)
    assert approved.status_code in {200, 302}, approved.text
    report = Entities.fetch_one(plan_id, request=Fetch.direct())
    operation = report.deferred_job["key"]
    with app.test_request_context("/"):
        login_user(actor)
        waiting = DeferredJobs.run(operation)
        assert waiting.state.value == "retry-scheduled"
        report = Entities.fetch_one(plan_id, request=Fetch.direct())
        assert report.status == "running" and report.result["status"] == "waiting"
        assert report.result["actions"][0]["status"] == "waiting"
        assert Entities.fetch_one(tasks[0].key, request=Fetch.direct()).name != "Published migration"
        child_form = Entities.fetch_one(form.key, request=Fetch.direct())
        child = form_changes.json_value(child_form.db, form_changes.PENDING)["job"]
        child_result = DeferredJobs.run(child)
        assert child_result.state.value == "complete", child_result
        parent_job = Entities.fetch_one(operation, request=Fetch.direct())
        resumed = DeferredJobs.run(operation, now=parent_job.next_attempt_at)
        assert resumed.state.value == "complete", resumed
    final = Entities.fetch_one(plan_id, request=Fetch.direct())
    assert final.status == "complete"
    assert Entities.fetch_one(tasks[0].key, request=Fetch.direct()).name == "Published migration"
    for task in tasks:
        saved = Entities.fetch_one(task.key, request=Fetch.direct())
        assert saved.generation == 1
        assert saved.submission["count"] == 0
        assert saved.submission["notes"]["items"][0]["checked"] is False
    assert Entities.fetch_one(tasks[1].key, request=Fetch.direct()).db["completed_submission"] == completion
    assert len(calls) == (3 if origin == "web" else 0)
    rejected_undo = client.post(f"/tools/reports/{plan_id}/undo", headers=browser_headers)
    assert "cannot be undone" in rejected_undo.text
