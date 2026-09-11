"""Executable MCP field patches agree with the report validator and runner."""

from copy import deepcopy
from itertools import combinations
import json
from types import SimpleNamespace

import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai.function_definitions import get_guidelines
from lagniappe.core.tools.ai.reporting.contracts import schema
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from lagniappe.core.tools.ai.reporting.proposals.validation import validate_proposal
from testing.utility.ai_report_fakes import _patch_fake_keys, _test_user
from testing.utility.test_entities import TestEntities


TARGETS = ("page", "task", "page_action", "task_action")


def _proposal(data):
    return {
        "summary": "Update reproduction details",
        "confidence": 1,
        "actions": [
            {"id": "new-page", "type": "create_page", "data": {"name": "Page"}},
            {
                "id": "new-task", "type": "create_task",
                "data": {"name": "Task", "page_action": "new-page"},
            },
            {"id": "fields", "type": "update_form_values", "data": data},
        ],
    }


# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @source lagniappe/core/tools/ai/external_api.py::submission_validation_errors
# @source lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @matrix agent-api : external-schema proposal-contract schema field-path
# @matrix ai-report : canonical-target validation
@pytest.mark.unit
@pytest.mark.parametrize(
    "targets",
    [(), *((target,) for target in TARGETS), *combinations(TARGETS, 2)],
)
def test_update_rows_require_one_target_in_contract_and_runtime(targets):
    actor = _test_user("field-contract-owner")
    report = SimpleNamespace(tool="organize", origin="web", input_files=[])
    row = {"schema_id": "textarea-notes", "new_value": "Updated notes"}
    row.update({target: "new-page" if target.startswith("page") else "new-task"
                for target in targets})
    proposal = _proposal({"updates": [row]})
    envelope = {"contract_version": external_api.CONTRACT_VERSION, "proposal": proposal}

    contract = schema.external_report_proposal_response_schema(
        allowed_actions=("update_form_values",),
    )
    data_schema = contract["$defs"]["update_form_values"]["properties"]["data"]
    assert set(data_schema["properties"]) == {"updates"}
    assert data_schema["properties"]["updates"]["items"]["oneOf"] == [
        {"required": [target]} for target in TARGETS
    ]
    errors = external_api.submission_validation_errors(envelope, report, actor)
    if len(targets) == 1:
        assert errors == []
        assert validate_proposal(deepcopy(proposal))["actions"][-1]["data"] == {
            "updates": [row]
        }
    else:
        assert errors
        assert all(error["path"].startswith(
            "$.proposal.actions[2].data.updates[0]"
        ) for error in errors)
        if targets:
            assert errors[0]["code"] == "one_of"
        with pytest.raises(exceptions.AIException, match="requires exactly one page or task"):
            validate_proposal(deepcopy(proposal))


# @source lagniappe/core/tools/ai/external_api.py::submission_validation_errors
# @source lagniappe/core/tools/ai/reporting/proposals/validation.py::validate_proposal
# @matrix agent-api : schema field-path
# @matrix ai-report : canonical-target validation
@pytest.mark.unit
def test_top_level_update_target_is_only_valid_for_internal_pending_planning():
    actor = _test_user("pending-contract-owner")
    report = SimpleNamespace(tool="organize", origin="web", input_files=[])
    pending = _proposal({"task": "new-task"})
    assert validate_proposal(
        deepcopy(pending), allow_empty_submission_updates=True,
        require_pending_submission_target=True,
    )["actions"][-1]["data"] == {"task": "new-task"}

    # The failed live MCP payload: target on the action, final values on rows.
    rejected = deepcopy(pending)
    rejected["actions"][-1]["data"]["updates"] = [
        {"schema_id": "textarea-notes", "new_value": "Updated notes"}
    ]
    with pytest.raises(exceptions.AIException, match="top-level targets do not apply"):
        validate_proposal(deepcopy(rejected))
    for proposal in (pending, rejected):
        errors = external_api.submission_validation_errors(
            {"contract_version": external_api.CONTRACT_VERSION, "proposal": proposal},
            report, actor,
        )
        assert any(error["path"] == "$.proposal.actions[2].data.task"
                   and error["code"] == "additional_property" for error in errors)
        assert any(".data.updates" in error["path"] for error in errors)


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @source lagniappe/core/tools/ai/external_api.py::submission_validation_errors
# @matrix ai agent-api : guidelines tool-dispatch
# @matrix agent-api : schema field-path
@pytest.mark.unit
def test_selected_update_guidance_example_satisfies_external_contract():
    actor = _test_user("example-contract-owner")
    guidance = get_guidelines.execute_external_get_guidelines(
        {"task": "report_actions", "actions": ["update_form_values"]}, actor,
    )["guidelines"]
    example, _remainder = json.JSONDecoder().raw_decode(guidance.split("Example data: ")[1])
    assert external_api.submission_validation_errors(
        {"contract_version": external_api.CONTRACT_VERSION, "proposal": _proposal(example)},
        SimpleNamespace(tool="organize", origin="web", input_files=[]), actor,
    ) == []
    assert "Put the target inside every data.updates row" in guidance
    assert "internal pending planning only" in guidance
    patches = get_guidelines.execute_external_get_guidelines(
        {"task": "form_autofill", "actions": ["update_form_values"],
         "field_types": ["table", "textarea"]}, actor,
    )["guidelines"]
    assert "Every data.updates row must include its own" in patches
    assert "top-level target does not apply" in patches


# @source lagniappe/core/tools/ai/external_api.py::submission_validation_errors
# @source lagniappe/core/tools/ai/external_api.py::submit_plan
# @source lagniappe/core/tools/ai/reporting/execution/actions/forms.py::_update_form_values
# @matrix agent-api : schema field-path ready-state
# @matrix ai-report submission : batch-field-patch persistence
@pytest.mark.unit
def test_mcp_reproduction_batch_submits_then_updates_three_tasks(monkeypatch):
    _patch_fake_keys(monkeypatch)
    actor = _test_user("reproduction-owner")
    saved = []
    monkeypatch.setattr(external_api.Entities, "save", lambda *items: saved.extend(items))
    form = TestEntities.get("FORM", {"name": "Bug", "hash": "form00000001"})
    form.form_type = "task"
    form.schema = [
        {
            "id": "table-reproduce", "title": "To Reproduce", "type": "table",
            "columns": [
                {"id": f"column-{title.lower()}", "title": title, "type": "input", "input": "text"}
                for title in ("Action", "Expected", "Actual")
            ],
        },
        {"id": "textarea-notes", "title": "Notes", "type": "textarea"},
        {"id": "textarea-keep", "title": "Other", "type": "textarea"},
    ]
    tasks = [TestEntities.get("TASK", {"name": f"Bug {i}", "hash": f"bug{i:09d}"})
             for i in range(3)]
    for task in tasks:
        task.page = actor.page
        task.form = form
        task.properties.submission.value = {
            "textarea-notes": "Original report", "textarea-keep": "Keep this",
        }
    entities = {entity.urlsafe_key: entity for entity in [actor.page, form, *tasks]}
    monkeypatch.setattr(external_api.Entities, "fetch",
                        lambda *ids, request: [entities.get(identifier) for identifier in ids])
    monkeypatch.setattr(report_runner.Entities, "fetch_one",
                        lambda identifier, request: identifier if hasattr(identifier, "db")
                        else entities.get(identifier))
    monkeypatch.setattr(external_api.cache, "get_details_by_hash", lambda hashes: {
        task.hash: {"id": task.urlsafe_key, "name": task.name, "kind": "task"}
        for task in tasks if task.hash in hashes
    })
    report = external_api.create_plan(actor, instructions="Restructure the three bugs")
    rows = {"rows": [{"column-action": "Open Home", "column-expected": "Hidden",
                      "column-actual": "Visible"}]}
    proposal = {
        "summary": "Restructure three bugs", "confidence": 1,
        "actions": [
            {
                "id": f"bug-{i}", "type": "update_form_values",
                "data": {"updates": [
                    {"task": f"hash:{task.hash}", "schema_id": "table-reproduce",
                     "new_value": deepcopy(rows)},
                    {"task": f"hash:{task.hash}", "schema_id": "textarea-notes",
                     "new_value": f"Context for Bug {i}"},
                ]},
            } for i, task in enumerate(tasks)
        ],
    }
    assert external_api.submission_validation_errors(
        {"contract_version": external_api.CONTRACT_VERSION, "proposal": proposal},
        report, actor,
    ) == []
    external_api.submit_plan(report, actor, proposal,
                             contract_version=external_api.CONTRACT_VERSION)
    assert report.status == "ready"
    assert all(task.submission["textarea-notes"] == "Original report" for task in tasks)

    result = report_runner.run_report(report, actor)

    assert result["status"] == "complete"
    for action in result["actions"]:
        assert action["status"] == "complete", json.dumps(action)
    assert [len(action["updates"]["applied"]) for action in result["actions"]] == [2, 2, 2]
    assert all(action["updates"]["skipped"] == [] for action in result["actions"])
    for i, task in enumerate(tasks):
        assert task in saved
        assert task.submission == {
            "table-reproduce": rows, "textarea-notes": f"Context for Bug {i}",
            "textarea-keep": "Keep this",
        }
        assert not task.completed
