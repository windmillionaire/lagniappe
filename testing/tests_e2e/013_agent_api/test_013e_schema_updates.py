"""Schema preview, external review and mixed migrations through real HTTP/domain paths."""

from copy import deepcopy
import re
from uuid import uuid4

import pytest
from flask_login import login_user

from lagniappe.core.definitions import Fetch, FetchReason
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
# @source lagniappe/core/tools/ai/external_api.py::validate_external_proposal
# @source lagniappe/core/tools/ai/function_definitions/get_task_history.py::execute_get_task_history
# @matrix form-migration : preview external-provider-free publication completed-task review
# @matrix ai-report : schema-update deterministic-run continue
# @pairs agent-api:proposal-validation
# @matrix ai tasks : original-completion schema-version
@pytest.mark.parametrize("origin", ["api", "web", "web-without-id"])
def test_reviewed_schema_migration_waits_for_publication_and_preserves_completion(get_user, monkeypatch, origin):
    user = get_user(Users.OWNER)
    actor = user.entity
    parent = Pages.test_create_page_task.get(user)
    form = Form(user=user, definition=FormDefinition(
        name=f"AI conversion {uuid4().hex[:8]}", form_type="task",
        schema=(SchemaFields.TEXTAREA.get(_id="notes", title="Notes"), SchemaFields.TEXT_INPUT.get(_id="count", title="Count")),
    )).create()
    tasks = []
    notes = ["- [ ] Keep 0\n- [x] Done 0", "Keep 1", "No identifiable checklist items were recorded."]
    for index in range(3):
        task = Entities.TASK.create({"name": f"Conversion target {index}", "page": parent.entity, "form": form.entity, "submission": {"notes": notes[index], "count": "0"}})
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
    created = client.post("/api/v1/plans", json={"instructions": "Convert Notes to a todo list and Count to a number."}, headers=headers)
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
    for instance in first["instances"] + second.json["result"]["instances"]:
        scalar = next(field for field in instance["fields"] if field["schema_id"] == "count")
        assert (scalar["before"], scalar["after"], scalar["clears"]) == ("0", 0, False)
    expected = {
        tasks[0].urlsafe_key: {"items": [{"text": "Keep 0", "checked": False}, {"text": "Done 0", "checked": True}]},
        tasks[1].urlsafe_key: {"items": [{"text": "Keep 1", "checked": False}]},
    }
    task_keys = {f"hash:{task.hash}": task.urlsafe_key for task in tasks}
    unresolved_reason = "The source reports an absence of identifiable checklist items."
    candidates = [
        {
            "entity": item["entity"], "schema_id": field["schema_id"],
            "source_fingerprint": field["source_fingerprint"],
            **({"value": expected[task_keys[item["entity"]]]} if task_keys[item["entity"]] in expected else {"unresolved_reason": unresolved_reason}),
        }
        for item in first["instances"] + second.json["result"]["instances"]
        for field in item["fields"] if field["rule"] == "ai"
    ]
    proposal = {"summary": "Convert saved Notes and Count. Unconvertible values clear; migration cannot be undone.", "confidence": 1, "issues": [], "actions": [
        {"id": "schema", "type": "update_form_schema", "data": {"form": f"hash:{form.entity.hash}", "operations": operations, "baseline": first["baseline"], "scope_fingerprint": first["scope_fingerprint"], "conversions": candidates}},
        {"id": "published", "type": "create_project", "depends_on": ["schema"], "data": {"name": "Published migration"}},
    ]}
    if origin == "api":
        incomplete = deepcopy(proposal)
        incomplete["actions"][0]["data"]["conversions"].pop()
        refused = client.post(f"/api/v1/plans/{plan_id}/submit", headers=headers, json={"file_usage": [], "contract_version": external_api.CONTRACT_VERSION, "proposal": incomplete})
        assert refused.status_code == 422, refused.text
        submitted = client.post(f"/api/v1/plans/{plan_id}/submit", headers=headers, json={"file_usage": [], "contract_version": external_api.CONTRACT_VERSION, "proposal": proposal})
        assert submitted.status_code == 200, submitted.text
        assert submitted.json["action_summary"] == {"total": 2, "by_type": {"update_form_schema": 1, "create_project": 1}, "maximum": 100}
    else:
        from lagniappe.core.tools.ai.reporting.proposals.validation import validate_proposal
        report = Entities.fetch_one(plan_id, request=Fetch.direct())
        report.origin = "web"
        report.proposal = schema_updates.prepare_schema_updates(validate_proposal(proposal), actor)
        if origin == "web-without-id":
            # Reproduce a saved proposal accepted before schema actions were
            # assigned IDs; approval must bind it without another model call.
            report.proposal["actions"][0].pop("id")
            report.proposal["actions"][1].pop("depends_on")
        report.status = "ready"
        Entities.save(report)
    # Both report origins apply reviewed values even without provider entitlement.
    monkeypatch.setattr(Entities.USER, "access", lambda *args: False)
    monkeypatch.setattr(form_conversion, "generate_conversions", lambda *args: pytest.fail("Reviewed report execution invoked a provider"))
    monkeypatch.setattr(app.login_manager, "_user_callback", lambda identifier: actor)
    with client.session_transaction() as session:
        session["_user_id"] = actor.get_id()
        session["_fresh"] = True
    review = client.get(f"/tools/reports/{plan_id}")
    assert review.status_code == 200, review.text
    assert 'data-role="schema-impact-item"' in review.text and "cannot be undone" in review.text
    assert 'data-role="proposal-action-summary"' in review.text and "2 proposed actions" in review.text
    assert ("100 maximum" in review.text) is (origin == "api")
    assert all(task.urlsafe_key in review.text for task in tasks)
    assert unresolved_reason in review.text
    assert "Done 0" in review.text
    reviewed = Entities.fetch_one(plan_id, request=Fetch.direct()).proposal
    assert reviewed["actions"][0]["data"]["conversions"] == [
        {**candidate, "entity": task_keys[candidate["entity"]]} for candidate in candidates
    ]
    for task, source in zip(tasks, notes):
        assert Entities.fetch_one(task.key, request=Fetch.direct()).submission["notes"] == source
    # Hold all dispatches to observe the real parent/child scheduling boundary.
    monkeypatch.setattr(DeferredJobs, "dispatch", lambda *args, **kwargs: "held")
    csrf = re.search(r'<input id="token" type="hidden" value="([^"]+)"', review.text).group(1)
    browser_headers = {"X-CSRFToken": csrf}
    approved = client.post(f"/tools/reports/{plan_id}/run", headers=browser_headers)
    assert approved.status_code in {200, 302}, approved.text
    report = Entities.fetch_one(plan_id, request=Fetch.direct())
    if origin == "web-without-id":
        assert report.proposal["actions"][0]["id"] == "schema_change_1"
        assert "depends_on" not in report.proposal["actions"][1]
        assert report.proposal["actions"][0]["data"] == reviewed["actions"][0]["data"]
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
    assert Entities.fetch_one(final.result["actions"][1]["entity"]["id"], request=Fetch.direct()).name == "Published migration"
    for task in tasks:
        saved = Entities.fetch_one(task.key, request=Fetch.direct())
        assert saved.generation == 1
        assert saved.submission["count"] == 0
        if task.urlsafe_key in expected:
            assert saved.submission["notes"] == expected[task.urlsafe_key]
        else:
            assert "notes" not in saved.submission
            notice = form_changes.json_value(saved.db, form_changes.NOTICE)
            assert notice["notes"]["value"] == notes[2]
    assert Entities.fetch_one(tasks[1].key, request=Fetch.direct()).db["completed_submission"] == completion
    arguments = {"id": f"hash:{tasks[1].hash}", "include_original": True}
    if origin == "api":
        rejected_read = client.post(f"/api/v1/plans/{plan_id}/tools/get_task_history", json={"arguments": arguments}, headers=headers)
        assert rejected_read.status_code == 409, rejected_read.text
        assert "omit plan_id" in rejected_read.json["error"]["message"]
    original_read = client.post("/api/v1/tools/get_task_history", json={"arguments": arguments}, headers=headers)
    assert original_read.status_code == 200, original_read.text
    answers = original_read.json["result"]
    assert answers["task"]["Count"] == 0
    assert answers["original_completion"]["generation"] == 0
    assert answers["original_completion"]["schema_available"] is True
    assert answers["original_completion"]["values"] == {"notes": "Keep 1", "count": "0"}
