"""Trusted external guidance and schedule contracts without provider drift."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

from google.genai import types as genai_types
import pytest

from lagniappe.core import exceptions
from lagniappe.core.tools.ai import external_api
from lagniappe.core.tools.ai import functions
from lagniappe.core.tools.ai.function_definitions import get_guidelines, search
from lagniappe.core.tools.ai.guidelines import REPORT_TASK_SCHEDULING_GUIDELINES
from lagniappe.core.tools.ai.reporting.contracts import schema
from lagniappe.core.tools.ai.reporting.schedules import validate_task_schedule


# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
def test_guidance_dispatch_keeps_external_completion_out_of_provider_workflow():
    actor = SimpleNamespace()
    provider_parts, media = functions.execute_function_calls(
        [
            SimpleNamespace(
                name="get_guidelines", args={"task": "organize", "external": True}
            )
        ],
        actor,
    )
    internal = json.loads(provider_parts[0].function_response.response["result"])
    external, external_media = functions.execute_registered_tool(
        "get_guidelines", {"task": "organize", "external": False}, actor, external=True
    )

    assert media == external_media == []
    assert internal == get_guidelines.execute_get_guidelines(
        {"task": "organize"}, actor
    )
    assert "server performs focused form completion afterward" in internal["guidelines"]
    assert "No action contains submission-generation fields" in internal["guidelines"]
    assert "/submit" not in internal["guidelines"]
    assert "submit_plan" not in internal["guidelines"]
    assert "server will not call a model" not in internal["guidelines"]
    assert "exactly one summarize_file action per file" in external["guidelines"]
    assert (
        "author the final summaries and form submissions or updates yourself"
        in external["guidelines"]
    )
    assert (
        "No action contains submission-generation fields" not in external["guidelines"]
    )
    assert "leave data.updates to the completion stage" not in external["guidelines"]
    assert "summarize_file" not in functions.DECLARATIONS
    for result in (internal, external):
        assert result["content_bytes"] == len(result["guidelines"].encode("utf-8"))
    inputs = functions.tool_catalog(names=["get_guidelines"], transport="rest")[0][
        "input_schema"
    ]
    assert set(inputs["properties"]) == {"task", "field_types", "actions"}

    internal_form, _ = functions.execute_registered_tool(
        "get_guidelines", {"task": "form_autofill"}, actor
    )
    external_form, _ = functions.execute_registered_tool(
        "get_guidelines", {"task": "form_autofill"}, actor, external=True
    )
    assert "Preserve every non-empty value" in internal_form["guidelines"]
    assert "partial submission (if provided) unaltered" in internal_form["guidelines"]
    assert "Preserve every non-empty value" not in external_form["guidelines"]
    assert (
        "partial submission (if provided) unaltered" not in external_form["guidelines"]
    )
    assert "preserve unresolved conflicts for review" in external_form["guidelines"]
    assert "assigned evidence clearly supersedes it" in external_form["guidelines"]
    assert (
        "do not copy unrelated existing values into data.updates"
        in external_form["guidelines"]
    )
    assert "exact schema field ids" in external_form["guidelines"]


# @matrix ai guidelines : action-selection field-type-selection payload-size
@pytest.mark.unit
def test_submission_patch_guidance_is_shared_and_omits_autofill_workflow():
    args = {
        "task": "form_autofill",
        "actions": ["update_form_values"],
        "field_types": ["input", "textarea"],
    }
    actor = SimpleNamespace()
    internal = get_guidelines.execute_get_guidelines(args, actor)
    external = get_guidelines.execute_external_get_guidelines(args, actor)
    full = get_guidelines.execute_external_get_guidelines(
        {"task": "form_autofill"}, actor
    )
    assert internal == external
    assert external["content_bytes"] < full["content_bytes"] / 2
    text = external["guidelines"]
    assert "omitted fields remain unchanged" in text
    assert "get_schema(include_values=true)" in text
    assert "keep longer detail" in text
    assert "Data Source Priority" not in text
    assert "Attached Files" not in text
    assert "`table` Submission Value Guidelines" not in text
    assert external["filters"] == {key: args[key] for key in ("actions", "field_types")}


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
@pytest.mark.parametrize("task", ["project", "task_form"])
def test_task_form_guidance_preserves_negative_answers_for_both_workflows(task):
    actor = SimpleNamespace()
    internal = get_guidelines.execute_get_guidelines({"task": task}, actor)
    external = get_guidelines.execute_external_get_guidelines({"task": task}, actor)

    assert internal == external
    guidance = internal["guidelines"]
    assert "A required checkbox must be checked to complete the task" in guidance
    assert "mandatory affirmative acknowledgements" in guidance
    assert "not questions where No is valid" in guidance
    assert "required Yes/No answer" in guidance
    assert "distinct non-empty string option values" in guidance
    assert "An optional checkbox may remain unchecked" in guidance
    assert "submit_plan" not in guidance
    assert "/submit" not in guidance


# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_get_guidelines
# @source lagniappe/core/tools/ai/function_definitions/get_guidelines.py::execute_external_get_guidelines
# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
def test_external_duplicate_check_reuses_evidence_without_a_filename_search_ritual():
    actor = SimpleNamespace()
    external = get_guidelines.execute_external_get_guidelines(
        {"task": "organize"}, actor
    )["guidelines"]
    internal = get_guidelines.execute_get_guidelines({"task": "organize"}, actor)[
        "guidelines"
    ]

    assert "Check each file for duplicate records or occurrences" in external
    assert "already-read destination/task evidence" in external
    assert "One comparison can cover related" in external
    assert "does not require a separate filename search per file" in external
    assert "unresolved identity or occurrence" in external
    assert "similar filename or topic alone as proof of a match" in external
    assert "duplicate_check" not in internal
    assert "server performs focused form completion afterward" in internal


# @matrix ai agent-api : guidelines tool-dispatch
@pytest.mark.unit
def test_external_search_dispatch_selects_candidates_without_changing_provider_default(
    monkeypatch,
):
    calls = []
    actor = SimpleNamespace()

    def lookup(arguments, user, *, candidate_search=False):
        calls.append((arguments, user, candidate_search))
        return [{"name": "Garden", "hash": "hash:abcdefghijkl", "kind": "page"}]

    monkeypatch.setattr(search, "execute_search", lookup)
    monkeypatch.setitem(functions.HANDLERS, "search_entities", lookup)
    arguments = {"query": "garden care", "external": True}
    native, _ = functions.execute_registered_tool("search_entities", arguments, actor)
    public, _ = functions.execute_registered_tool(
        "search_entities", arguments, actor, external=True
    )
    assert native == public
    assert calls == [(arguments, actor, False), (arguments, actor, True)]

    native_definition = deepcopy(functions.tool_catalog(names=["search_entities"])[0])
    external_definition = functions.tool_catalog(
        names=["search_entities"], transport="rest"
    )[0]
    assert external_definition["description"] == search.CANDIDATE_SEARCH_DESCRIPTION
    assert (
        "keyword candidates"
        in external_definition["input_schema"]["properties"]["parent_id"]["description"]
    )
    assert functions.tool_catalog(names=["search_entities"])[0] == native_definition
    assert set(external_definition["input_schema"]["properties"]) == set(
        native_definition["input_schema"]["properties"]
    )


# @matrix agent-api task-scheduling : periodic recurring scheduled structured-output validation
# @source lagniappe/core/tools/ai/external_api.py::submission_validation_errors
# @matrix agent-api : schema field-path
@pytest.mark.unit
@pytest.mark.parametrize(
    "schedule,valid",
    [
        ({"kind": "scheduled"}, False),
        ({"kind": "scheduled", "mode": "daily"}, True),
        ({"kind": "recurring", "interval": 2, "unit": "week"}, True),
        ({"kind": "recurring", "interval": 0, "unit": "week"}, False),
        ({"kind": "recurring", "interval": 2}, False),
        ({"kind": "periodic", "interval": 3, "unit": "month"}, False),
        (
            {
                "kind": "periodic",
                "interval": 3,
                "unit": "month",
                "description": "Quarterly",
            },
            True,
        ),
        ({"kind": "scheduled", "mode": "weekly", "days": []}, False),
        ({"kind": "scheduled", "mode": "weekly", "days": [0, 0, 2]}, True),
        ({"kind": "scheduled", "mode": "weekly", "days": [7]}, False),
        ({"kind": "scheduled", "mode": "weekly", "days": [True]}, False),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "first_day",
                "description": "Month start",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "specific_day",
                "description": "Monthly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "specific_day",
                "day": 31,
                "description": "Monthly",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "specific_day",
                "day": 32,
                "description": "Monthly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "ordinal_weekday",
                "ordinal": 0,
                "weekday": 1,
                "description": "Monthly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "ordinal_weekday",
                "ordinal": -1,
                "weekday": 1,
                "description": "Monthly",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "yearly",
                "pattern_type": "last_day",
                "description": "Yearly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "yearly",
                "pattern_type": "last_day",
                "month": 12,
                "description": "Yearly",
            },
            True,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "yearly",
                "pattern_type": "last_day",
                "month": 13,
                "description": "Yearly",
            },
            False,
        ),
        (
            {
                "kind": "scheduled",
                "mode": "monthly",
                "pattern_type": "first_day",
                "description": "",
            },
            False,
        ),
    ],
)
def test_external_schedule_schema_matches_repeating_schedule_requirements(
    schedule, valid, monkeypatch
):
    monkeypatch.setattr(
        external_api, "allowed_report_actions", lambda user: ("create_task",)
    )
    errors = external_api.submission_validation_errors(
        {
            "contract_version": external_api.CONTRACT_VERSION,
            "proposal": {
                "summary": "Repeat this work.",
                "confidence": 0.9,
                "actions": [
                    {
                        "type": "create_task",
                        "data": {
                            "name": "Water garden",
                            "page": "hash:abcdefghijkl",
                            "schedule": schedule,
                        },
                    },
                ],
            },
        },
        SimpleNamespace(tool="create"),
        SimpleNamespace(),
    )
    assert (not errors) is valid
    assert all(
        error["path"].startswith("$.proposal.actions[0].data.schedule")
        for error in errors
    )
    if valid:
        assert validate_task_schedule(schedule)["kind"] == schedule["kind"]
    else:
        with pytest.raises(exceptions.AIException):
            validate_task_schedule(schedule)


# @source lagniappe/core/tools/ai/reporting/contracts/schema.py::external_report_proposal_response_schema
# @matrix agent-api ai-report : external-schema proposal-contract structured-output
@pytest.mark.unit
def test_external_task_contract_explains_references_without_changing_provider_schema():
    provider = schema.report_proposal_response_schema(("create_task", "create_page"))
    original = deepcopy(provider)
    external = schema.external_report_proposal_response_schema(
        ("create_task", "create_page")
    )
    data = external["$defs"]["create_task"]["properties"]["data"]
    proposal = {
        "summary": "Propose a reminder.",
        "confidence": 0.9,
        "actions": [
            {
                "type": "create_task",
                "data": {
                    "name": "Water garden",
                    "page": "hash:abcdefghijkl",
                    "due_date": "2026-10-02",
                },
            },
        ],
    }
    assert external_api._schema_errors(proposal, external, external, "$.proposal") == []
    proposal["actions"][0]["data"]["schedule"] = {"kind": "scheduled"}
    assert external_api._schema_errors(proposal, external, external, "$.proposal") == [
        {
            "code": "required",
            "path": "$.proposal.actions[0].data.schedule.mode",
            "message": "mode is required.",
            "expected": "present",
        }
    ]
    for field in ("task", "task_action"):
        assert "completed" in data["properties"][field]["description"]
    assert "create_model_task" in data["properties"]["model_action"]["description"]
    assert "create_page" in data["properties"]["page_action"]["description"]
    assert (
        provider
        == original
        == schema.report_proposal_response_schema(("create_task", "create_page"))
    )
    for include_values in (False, True):
        genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema.report_proposal_response_schema(
                include_submission_fields=include_values
            ),
        )


# @source lagniappe/core/tools/ai/external_api.py::plan_contract
# @matrix agent-api ai-report : proposal-contract
@pytest.mark.unit
def test_external_contract_reuses_known_guidance_and_exposes_canonical_scheduling(
    monkeypatch,
):
    actor = SimpleNamespace(
        page=SimpleNamespace(
            hash="personalpage",
            name="Personal",
            url="/pages/personal",
            allowed=lambda action, user=None: True,
        )
    )
    monkeypatch.setattr(
        external_api,
        "allowed_report_actions",
        lambda user: ("create_task", "create_page"),
    )
    monkeypatch.setattr(
        external_api,
        "report_action_permission_context",
        lambda user, allowed: {"allowed_actions": list(allowed)},
    )
    monkeypatch.setattr(
        external_api.dates,
        "user_today",
        lambda user: datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    for tool in ("create", "organize"):
        contract = external_api.plan_contract(
            SimpleNamespace(tool=tool, input_files=[]),
            actor,
            submit_url=f"https://example.test/api/v1/plans/{tool}/submit",
        )
        assert REPORT_TASK_SCHEDULING_GUIDELINES.strip() in contract["workflow_rules"]
        assert "guidelines" not in contract
        assert "already supplied" in contract["guidance_requirements"]["deduplication"]
        action_guidance = next(
            item
            for item in contract["guidance_requirements"]["conditional"]
            if item["request"]["task"] == "report_actions"
        )
        assert action_guidance["when"]["action_guidance_needed"] is True

    public = get_guidelines.execute_external_get_guidelines(
        {"task": "report_actions", "actions": ["create_task"]}, actor
    )
    assert REPORT_TASK_SCHEDULING_GUIDELINES.strip() in public["guidelines"]
    unrelated = get_guidelines.execute_external_get_guidelines(
        {"task": "report_actions", "actions": ["create_page"]}, actor
    )
    assert "Report Task Scheduling" not in unrelated["guidelines"]
